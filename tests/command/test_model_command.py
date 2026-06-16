from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.agent.vps_model_catalog import install_vps_model_catalog
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.command.builtin import (
    build_help_text,
    builtin_command_palette,
    cmd_goal,
    cmd_model,
    register_builtin_commands,
)
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.config.schema import ModelPresetConfig


def _provider(default_model: str, max_tokens: int = 123) -> MagicMock:
    provider = MagicMock()
    provider.get_default_model.return_value = default_model
    provider.generation = SimpleNamespace(
        max_tokens=max_tokens,
        temperature=0.1,
        reasoning_effort=None,
    )
    return provider


def _make_loop(tmp_path) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_provider("base-model", max_tokens=123),
        workspace=tmp_path,
        model="base-model",
        context_window_tokens=1000,
        model_presets={
            "default": ModelPresetConfig(
                model="base-model",
                max_tokens=123,
                context_window_tokens=1000,
            ),
            "fast": ModelPresetConfig(
                model="openai/gpt-4.1",
                max_tokens=4096,
                context_window_tokens=32_768,
            ),
        },
    )


def _ctx(loop: AgentLoop, raw: str, args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(msg=msg, session=None, key=msg.session_key, raw=raw, args=args, loop=loop)


def _ctx_session(loop: AgentLoop, raw: str, args: str = "") -> CommandContext:
    msg = InboundMessage(channel="cli", sender_id="user", chat_id="direct", content=raw)
    return CommandContext(
        msg=msg, session=MagicMock(), key=msg.session_key, raw=raw, args=args, loop=loop,
    )


@pytest.mark.asyncio
async def test_model_command_lists_current_and_available_presets(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    out = await cmd_model(_ctx(loop, "/model"))

    assert "Current model: `base-model`" in out.content
    assert "Current preset: `default`" in out.content
    assert "Available presets: `default`, `fast`" in out.content
    assert "`fast`" in out.content
    assert out.metadata == {"render_as": "text"}


@pytest.mark.asyncio
async def test_model_command_lists_numbered_presets_and_switches_by_number(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    status = await cmd_model(_ctx(loop, "/model"))
    switched = await cmd_model(_ctx(loop, "/model 2", args="2"))

    assert "1. * `default`" in status.content
    assert "2. `fast`" in status.content
    assert "Switched model preset to `fast`." in switched.content
    assert loop.model_preset == "fast"


@pytest.mark.asyncio
async def test_model_command_persists_successful_global_selection(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    persisted: list[str] = []
    loop.model_selection_persister = persisted.append

    await cmd_model(_ctx(loop, "/model fast", args="fast"))

    assert persisted == ["fast"]


@pytest.mark.asyncio
async def test_model_command_switches_preset(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    out = await cmd_model(_ctx(loop, "/model fast", args="fast"))

    assert "Switched model preset to `fast`." in out.content
    assert "Model: `openai/gpt-4.1`" in out.content
    assert loop.model_preset == "fast"
    assert loop.model == "openai/gpt-4.1"
    assert loop.subagents.model == "openai/gpt-4.1"
    assert loop.consolidator.model == "openai/gpt-4.1"


@pytest.mark.asyncio
async def test_model_command_switches_back_to_default(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    await loop.set_model_preset("fast")

    out = await cmd_model(_ctx(loop, "/model default", args="default"))

    assert "Switched model preset to `default`." in out.content
    assert loop.model_preset == "default"
    assert loop.model == "base-model"
    assert loop.context_window_tokens == 1000


@pytest.mark.asyncio
async def test_model_command_unknown_preset_keeps_old_state(tmp_path) -> None:
    loop = _make_loop(tmp_path)

    out = await cmd_model(_ctx(loop, "/model missing", args="missing"))

    assert "Could not switch model preset" in out.content
    assert "\"model_preset" not in out.content
    assert "Available presets: `default`, `fast`" in out.content
    assert loop.model_preset is None
    assert loop.model == "base-model"


@pytest.mark.asyncio
async def test_model_command_omits_disabled_vertex_presets(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    config = SimpleNamespace(model_presets={})
    install_vps_model_catalog(config)
    loop = _make_loop(tmp_path)
    loop.model_presets = config.model_presets

    out = await cmd_model(_ctx(loop, "/model"))
    rejected = await cmd_model(_ctx(loop, "/model vertex-35-flash", args="vertex-35-flash"))

    assert "Vertex" not in out.content
    assert "vertex-" not in out.content
    assert "`studio-35-flash`" in out.content
    assert "Could not switch model preset" in rejected.content
    assert "vertex-35-flash" in rejected.content


@pytest.mark.asyncio
async def test_model_command_does_not_depend_on_my_allow_set(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    assert loop.tools_config.my.allow_set is False

    await cmd_model(_ctx(loop, "/model fast", args="fast"))

    assert loop.model_preset == "fast"


@pytest.mark.asyncio
async def test_model_command_registered_as_exact_and_prefix(tmp_path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    loop = _make_loop(tmp_path)

    out = await router.dispatch(_ctx(loop, "/model fast"))

    assert out is not None
    assert out.channel == "cli"
    assert out.chat_id == "direct"
    assert out.metadata == {"render_as": "text"}
    assert out.content == "\n".join([
        "Switched model preset to `fast`.",
        "- Model: `openai/gpt-4.1`",
        "- Context window: 32768",
        "- Max output tokens: 4096",
    ])
    assert loop.model_preset == "fast"


def test_model_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()

    assert any(item["command"] == "/model" and item["arg_hint"] == "[preset]" for item in palette)
    assert "/model [preset]" in build_help_text()


@pytest.mark.asyncio
async def test_goal_command_shows_usage_without_args(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    out = await cmd_goal(_ctx(loop, "/goal"))
    assert out is not None
    assert out.channel == "cli"
    assert out.chat_id == "direct"
    assert out.metadata == {"render_as": "text"}
    assert out.content == "Usage: /goal <long-running task description>"


@pytest.mark.asyncio
async def test_goal_command_rejects_mid_turn_without_session(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    out = await cmd_goal(_ctx(loop, "/goal do work", args="do work"))
    assert out is not None
    assert out.channel == "cli"
    assert out.chat_id == "direct"
    assert out.metadata == {"render_as": "text"}
    assert out.content == (
        "A task is already running for this chat. "
        "Use `/stop` first, then send `/goal <long-running task description>` again."
    )


@pytest.mark.asyncio
async def test_goal_command_rewrites_to_agent_prompt(tmp_path) -> None:
    loop = _make_loop(tmp_path)
    ctx = _ctx_session(loop, "/goal audit the repo", args="audit the repo")
    out = await cmd_goal(ctx)
    assert out is None
    assert "audit the repo" in ctx.msg.content
    assert "long_task" in ctx.msg.content
    assert ctx.msg.metadata.get("original_command") == "/goal"
    assert ctx.msg.metadata.get("original_content") == "/goal audit the repo"
    assert isinstance(ctx.msg.metadata.get("goal_started_at"), int | float)


@pytest.mark.asyncio
async def test_goal_command_registered_on_router(tmp_path) -> None:
    router = CommandRouter()
    register_builtin_commands(router)
    loop = _make_loop(tmp_path)
    ctx = _ctx_session(loop, "/goal ship it", args="ship it")
    out = await router.dispatch(ctx)
    assert out is None
    assert "ship it" in ctx.msg.content


def test_goal_command_in_help_and_palette() -> None:
    palette = builtin_command_palette()
    assert any(item["command"] == "/goal" and item["arg_hint"] == "<goal>" for item in palette)
    assert "/goal <goal>" in build_help_text()
