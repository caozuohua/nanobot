import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.runner import AgentRunSpec
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
from nanobot.providers.base import LLMResponse
from nanobot.providers.factory import ProviderSnapshot, load_provider_snapshot
from nanobot.webui.settings_api import update_agent_settings


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(max_tokens=max_tokens)
    provider.aclose = AsyncMock()
    return provider


@pytest.mark.asyncio
async def test_model_preset_switch_closes_old_provider_once(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    await loop.set_model_preset("fast")

    assert loop.provider is new_provider
    old_provider.aclose.assert_awaited_once_with()
    new_provider.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_model_preset_application_preserves_old_provider_and_closes_candidate(
    tmp_path: Path,
) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )
    loop.subagents.set_provider = MagicMock(
        side_effect=[RuntimeError("apply failed"), None],
    )

    with pytest.raises(RuntimeError, match="apply failed"):
        await loop.set_model_preset("fast")

    assert loop.provider is old_provider
    assert loop.model == "old-model"
    old_provider.aclose.assert_not_awaited()
    new_provider.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_model_preset_cleanup_error_does_not_undo_successful_switch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old_provider = _provider("old-model")
    old_provider.aclose.side_effect = RuntimeError("close failed")
    log_exception = MagicMock()
    monkeypatch.setattr("nanobot.agent.loop.logger.exception", log_exception)
    new_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    await loop.set_model_preset("fast")

    assert loop.provider is new_provider
    old_provider.aclose.assert_awaited_once_with()
    log_exception.assert_called_once_with("Failed to close {} provider", "replaced")


@pytest.mark.asyncio
async def test_stop_closes_active_provider_once_and_ignores_cleanup_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider("model")
    provider.aclose.side_effect = RuntimeError("close failed")
    log_exception = MagicMock()
    monkeypatch.setattr("nanobot.agent.loop.logger.exception", log_exception)
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)

    await loop.stop()
    await loop.stop()

    assert loop._running is False
    provider.aclose.assert_awaited_once_with()
    log_exception.assert_called_once_with("Failed to close {} provider", "active")


@pytest.mark.asyncio
async def test_provider_refresh_updates_all_model_dependents(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model", max_tokens=456)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        context_window_tokens=1000,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    await loop._refresh_provider_snapshot()

    assert loop.provider is new_provider
    assert loop.model == "new-model"
    assert loop.context_window_tokens == 2000
    assert loop.runner.provider is new_provider
    assert loop.subagents.provider is new_provider
    assert loop.subagents.model == "new-model"
    assert loop.subagents.runner.provider is new_provider
    assert loop.consolidator.provider is new_provider
    assert loop.consolidator.model == "new-model"
    assert loop.consolidator.context_window_tokens == 2000
    assert loop.consolidator.max_completion_tokens == 456


@pytest.mark.asyncio
async def test_llm_runtime_refreshes_provider_snapshot(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model", max_tokens=456)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model="old-model",
        context_window_tokens=1000,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    runtime = await loop.llm_runtime()

    assert runtime.provider is new_provider
    assert runtime.model == "new-model"
    assert loop.provider is new_provider
    assert loop.runner.provider is new_provider


@pytest.mark.asyncio
async def test_settings_context_window_refreshes_runtime_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.json"
    config = Config()
    config.agents.defaults.workspace = str(tmp_path / "workspace")
    config.agents.defaults.model = "openai/gpt-4o"
    config.agents.defaults.provider = "openai"
    config.agents.defaults.context_window_tokens = 65_536
    config.providers.openai.api_key = "sk-test"
    save_config(config, config_path)
    monkeypatch.setattr("nanobot.config.loader._current_config_path", config_path)

    def loader(*, preset_name: str | None = None) -> ProviderSnapshot:
        return load_provider_snapshot(config_path, preset_name=preset_name)

    loop = AgentLoop.from_config(config, provider_snapshot_loader=loader)

    payload = update_agent_settings({"context_window_tokens": ["262144"]})
    await loop._refresh_provider_snapshot()

    assert payload["requires_restart"] is False
    assert loop.context_window_tokens == 262_144
    assert loop.consolidator.context_window_tokens == 262_144


@pytest.mark.asyncio
async def test_provider_refresh_closes_replaced_provider(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    await loop._refresh_provider_snapshot()

    old_provider.aclose.assert_awaited_once_with()
    new_provider.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_refresh_closes_unchanged_candidate(tmp_path: Path) -> None:
    active_provider = _provider("model")
    candidate_provider = _provider("model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=active_provider,
        workspace=tmp_path,
        provider_signature=("same",),
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=candidate_provider,
            model="model",
            context_window_tokens=1000,
            signature=("same",),
        ),
    )

    await loop._refresh_provider_snapshot()

    assert loop.provider is active_provider
    candidate_provider.aclose.assert_awaited_once_with()
    active_provider.aclose.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_provider_refresh_preserves_old_provider_and_closes_candidate(
    tmp_path: Path,
) -> None:
    old_provider = _provider("old-model")
    candidate_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        provider_snapshot_loader=lambda: ProviderSnapshot(
            provider=candidate_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )
    loop.subagents.set_provider = MagicMock(
        side_effect=[RuntimeError("apply failed"), None],
    )

    await loop._refresh_provider_snapshot()

    assert loop.provider is old_provider
    assert loop.model == "old-model"
    old_provider.aclose.assert_not_awaited()
    candidate_provider.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_two_sessions_serialize_llm_requests(tmp_path: Path) -> None:
    provider = _provider("model")
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    active = 0
    max_active = 0

    async def chat_with_retry(**_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if not first_started.is_set():
            first_started.set()
            await release_first.wait()
        active -= 1
        return LLMResponse(content="done")

    provider.chat_with_retry = AsyncMock(side_effect=chat_with_retry)
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    tools = ToolRegistry()

    first = asyncio.create_task(loop.runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "one"}],
        tools=tools,
        model="model",
        max_iterations=1,
        max_tool_result_chars=1000,
        session_key="cli:one",
    )))
    await first_started.wait()
    second = asyncio.create_task(loop.runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "two"}],
        tools=tools,
        model="model",
        max_iterations=1,
        max_tool_result_chars=1000,
        session_key="cli:two",
    )))
    await asyncio.sleep(0)

    assert provider.chat_with_retry.await_count == 1
    release_first.set()
    await asyncio.gather(first, second)
    assert max_active == 1


@pytest.mark.asyncio
async def test_model_switch_waits_for_active_turn_before_closing_old_provider(
    tmp_path: Path,
) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model")
    turn_started = asyncio.Event()
    release_turn = asyncio.Event()

    async def chat_with_retry(**_kwargs):
        turn_started.set()
        await release_turn.wait()
        return LLMResponse(content="done")

    old_provider.chat_with_retry = AsyncMock(side_effect=chat_with_retry)
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )
    turn = asyncio.create_task(loop.runner.run(AgentRunSpec(
        initial_messages=[{"role": "user", "content": "work"}],
        tools=ToolRegistry(),
        model="old-model",
        max_iterations=1,
        max_tool_result_chars=1000,
        session_key="cli:one",
    )))
    await turn_started.wait()

    switch = asyncio.create_task(loop.set_model_preset("fast"))
    await asyncio.sleep(0)

    assert loop.provider is old_provider
    old_provider.aclose.assert_not_awaited()
    release_turn.set()
    await asyncio.gather(turn, switch)
    assert loop.provider is new_provider
    old_provider.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_cancelled_model_switch_closes_waiting_candidate_and_preserves_cancel(
    tmp_path: Path,
) -> None:
    old_provider = _provider("old-model")
    candidate_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=candidate_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )

    async with loop._llm_turn_gate.hold():
        switch = asyncio.create_task(loop.set_model_preset("fast"))
        await asyncio.sleep(0)
        switch.cancel()
        with pytest.raises(asyncio.CancelledError):
            await switch

    assert loop.provider is old_provider
    old_provider.aclose.assert_not_awaited()
    candidate_provider.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_stop_closes_provider_when_mcp_cleanup_raises(tmp_path: Path) -> None:
    provider = _provider("model")
    loop = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path)
    loop.close_mcp = AsyncMock(side_effect=RuntimeError("mcp cleanup failed"))

    await loop.stop()

    loop.close_mcp.assert_awaited_once_with()
    provider.aclose.assert_awaited_once_with()


def test_sync_model_preset_setter_rejects_before_constructing_candidate(tmp_path: Path) -> None:
    loader = MagicMock()
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider("model"),
        workspace=tmp_path,
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=loader,
    )

    with pytest.raises(RuntimeError, match="must be awaited"):
        loop.model_preset = "fast"

    loader.assert_not_called()


def test_loop_shares_one_llm_gate_across_all_provider_callers(tmp_path: Path) -> None:
    loop = AgentLoop(
        bus=MessageBus(),
        provider=_provider("model"),
        workspace=tmp_path,
    )

    assert loop.runner._llm_turn_gate is loop._llm_turn_gate
    assert loop.subagents.runner._llm_turn_gate is loop._llm_turn_gate
    assert loop.consolidator._llm_turn_gate is loop._llm_turn_gate


@pytest.mark.asyncio
async def test_rollback_failure_preserves_original_application_error(tmp_path: Path) -> None:
    old_provider = _provider("old-model")
    new_provider = _provider("new-model")
    loop = AgentLoop(
        bus=MessageBus(),
        provider=old_provider,
        workspace=tmp_path,
        model_presets={"fast": Config().resolve_default_preset()},
        preset_snapshot_loader=lambda _name: ProviderSnapshot(
            provider=new_provider,
            model="new-model",
            context_window_tokens=2000,
            signature=("new-model",),
        ),
    )
    loop.subagents.set_provider = MagicMock(
        side_effect=[ValueError("apply failed"), RuntimeError("rollback failed")],
    )

    with pytest.raises(ValueError, match="apply failed"):
        await loop.set_model_preset("fast")

    new_provider.aclose.assert_awaited_once_with()
