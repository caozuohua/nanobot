from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import AgentDefaults
from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest

_MAX_TOOL_RESULT_CHARS = AgentDefaults().max_tool_result_chars


def test_action_gate_classifies_high_confidence_action_requests() -> None:
    from nanobot.agent.action_gate import (
        classify_final_response,
        classify_user_intent,
        should_continue_for_action_guard,
    )

    assert classify_user_intent("请检查日志并修复问题") == "action"
    assert classify_user_intent("push to github and deploy") == "action"
    assert classify_user_intent("为什么会这样？") == "answer"
    assert classify_final_response("我会检查 VPS 日志。") == "promise"
    assert classify_final_response("已修复并通过测试。") == "completed"
    assert classify_final_response("我无法执行，因为缺少 SSH 权限。") == "blocker"
    assert should_continue_for_action_guard(
        "action",
        "promise",
        [],
        already_retried=False,
    ) is True


@pytest.mark.asyncio
async def test_action_gate_continues_when_action_request_only_promises() -> None:
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    calls: list[list[dict]] = []

    async def chat_with_retry(*, messages, **kwargs):
        calls.append([dict(message) for message in messages])
        if len(calls) == 1:
            return LLMResponse(content="我会检查日志。", tool_calls=[], usage={})
        if len(calls) == 2:
            return LLMResponse(
                content="checking",
                tool_calls=[
                    ToolCallRequest(
                        id="call_1",
                        name="list_dir",
                        arguments={"path": "."},
                    )
                ],
                usage={},
            )
        return LLMResponse(
            content="已经检查日志，服务正常。",
            tool_calls=[],
            usage={},
        )

    provider.chat_with_retry = chat_with_retry
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="logs ok")

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "请检查日志"}],
        tools=tools,
        model="test-model",
        max_iterations=4,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert len(calls) == 3
    assert calls[1][-1]["role"] == "user"
    assert "no tools were used" in calls[1][-1]["content"]
    assert result.final_content == "已经检查日志，服务正常。"
    assert result.tools_used == ["list_dir"]
    assert result.action_guard["guard_result"] == "continued"


@pytest.mark.asyncio
async def test_action_gate_allows_successful_tool_evidence() -> None:
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(side_effect=[
        LLMResponse(
            content="checking",
            tool_calls=[
                ToolCallRequest(id="call_1", name="list_dir", arguments={"path": "."})
            ],
            usage={},
        ),
        LLMResponse(content="检查完成。", tool_calls=[], usage={}),
    ])
    tools = MagicMock()
    tools.get_definitions.return_value = []
    tools.execute = AsyncMock(return_value="ok")

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "检查目录"}],
        tools=tools,
        model="test-model",
        max_iterations=3,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "检查完成。"
    assert result.action_guard["guard_result"] == "tool_evidence"


@pytest.mark.asyncio
async def test_action_gate_allows_concrete_blocker_without_tools() -> None:
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="我无法执行，因为缺少 SSH 权限。",
        tool_calls=[],
        usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "ssh 到 VPS 检查日志"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "我无法执行，因为缺少 SSH 权限。"
    assert result.action_guard["guard_result"] == "allowed_blocker"


@pytest.mark.asyncio
async def test_action_gate_does_not_apply_to_explanatory_questions() -> None:
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="这是因为压缩策略会保留最近上下文。",
        tool_calls=[],
        usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "为什么会这样？"}],
        tools=tools,
        model="test-model",
        max_iterations=2,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert result.final_content == "这是因为压缩策略会保留最近上下文。"
    assert provider.chat_with_retry.await_count == 1
    assert result.action_guard["guard_result"] == "not_actionable"


@pytest.mark.asyncio
async def test_action_gate_retries_at_most_once() -> None:
    from nanobot.agent.runner import AgentRunner, AgentRunSpec

    provider = MagicMock(spec=LLMProvider)
    provider.chat_with_retry = AsyncMock(return_value=LLMResponse(
        content="我会检查。",
        tool_calls=[],
        usage={},
    ))
    tools = MagicMock()
    tools.get_definitions.return_value = []

    result = await AgentRunner(provider).run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "检查日志"}],
        tools=tools,
        model="test-model",
        max_iterations=4,
        max_tool_result_chars=_MAX_TOOL_RESULT_CHARS,
    ))

    assert provider.chat_with_retry.await_count == 2
    assert result.final_content == "我会检查。"
    assert result.action_guard["guard_result"] == "retry_exhausted"
