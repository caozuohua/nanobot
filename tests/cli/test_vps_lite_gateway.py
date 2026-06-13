from __future__ import annotations

import asyncio
import builtins
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import nanobot.cli.commands as commands
from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import Config
from nanobot.cron.types import CronJob, CronPayload
from nanobot.providers.factory import ProviderSnapshot
from nanobot.runtime_profile import FULL_PROFILE, VPS_LITE_PROFILE

runner = CliRunner()


def _lite_config(tmp_path: Path) -> Config:
    return Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "workspace": str(tmp_path / "workspace"),
                    "provider": "openai",
                    "model": "openai/gpt-4.1-mini",
                    "dream": {"enabled": False},
                }
            },
            "gateway": {"heartbeat": {"enabled": False}},
            "providers": {"openai": {"apiKey": "test-key"}},
            "tools": {
                "my": {"enable": False},
                "imageGeneration": {"enabled": False},
                "cliApps": {"enable": False},
            },
        }
    )


def test_gateway_explicit_profile_overrides_environment(monkeypatch, tmp_path: Path) -> None:
    config = _lite_config(tmp_path)
    seen: list[object] = []
    monkeypatch.setenv("NANOBOT_PROFILE", "vps-lite")
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args: config)
    monkeypatch.setattr(
        commands,
        "_run_gateway",
        lambda _config, **kwargs: seen.append(kwargs["profile"]),
    )

    result = runner.invoke(commands.app, ["gateway", "--profile", "full"])

    assert result.exit_code == 0
    assert seen == [FULL_PROFILE]


def test_gateway_uses_environment_profile_and_resolves_it_once(
    monkeypatch, tmp_path: Path
) -> None:
    config = _lite_config(tmp_path)
    seen: list[object] = []
    calls: list[str | None] = []
    monkeypatch.setenv("NANOBOT_PROFILE", "vps-lite")
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args: config)

    def _resolve(name: str | None = None):
        calls.append(name)
        return VPS_LITE_PROFILE

    monkeypatch.setattr("nanobot.runtime_profile.resolve_runtime_profile", _resolve)
    monkeypatch.setattr(
        commands,
        "_run_gateway",
        lambda _config, **kwargs: seen.append(kwargs["profile"]),
    )

    result = runner.invoke(commands.app, ["gateway"])

    assert result.exit_code == 0
    assert calls == [None]
    assert seen == [VPS_LITE_PROFILE]


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda config: setattr(
                config.channels,
                "slack",
                {"enabled": True, "allowFrom": ["*"]},
            ),
            "Channel 'slack' is not available in runtime profile 'vps-lite'",
        ),
        (
            lambda config: (
                setattr(config.agents.defaults, "provider", "anthropic"),
                setattr(config.agents.defaults, "model", "anthropic/claude-sonnet-4-6"),
            ),
            "Provider 'anthropic' is not available in runtime profile 'vps-lite'",
        ),
        (
            lambda config: setattr(config.tools.my, "enable", True),
            "tools.my.enable",
        ),
    ],
)
def test_gateway_rejects_unsupported_lite_components_before_runtime(
    monkeypatch,
    tmp_path: Path,
    mutate,
    expected: str,
) -> None:
    config = _lite_config(tmp_path)
    mutate(config)
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args: config)
    monkeypatch.setattr(
        commands,
        "_run_gateway",
        lambda *_args, **_kwargs: pytest.fail("runtime must not start"),
    )

    result = runner.invoke(commands.app, ["gateway", "--profile", "vps-lite"])

    assert result.exit_code == 1
    assert expected in result.stdout


def test_vps_lite_gateway_omits_webui_and_public_listener_and_threads_profile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _lite_config(tmp_path)
    provider = MagicMock()
    provider.generation.max_tokens = 4096
    snapshot = ProviderSnapshot(
        provider=provider,
        model=config.agents.defaults.model,
        context_window_tokens=config.agents.defaults.context_window_tokens,
        signature=("lite",),
    )
    seen: dict[str, object] = {}
    forbidden_imports: list[str] = []
    original_import = builtins.__import__

    def _guarded_import(name, *args, **kwargs):
        if name.startswith("nanobot.webui") or name in {
            "nanobot.session.webui_turns",
            "nanobot.channels.websocket",
        }:
            forbidden_imports.append(name)
            raise AssertionError(f"unexpected Lite import: {name}")
        return original_import(name, *args, **kwargs)

    def _build_snapshot(_config, *, profile=None):
        seen["snapshot_profile"] = profile
        return snapshot

    def _load_snapshot(config_path=None, *, preset_name=None, profile=None):
        seen["loader_call"] = (config_path, preset_name, profile)
        return snapshot

    class _FakeSessions:
        sessions_dir = tmp_path / "sessions"

        def list_sessions(self):
            return []

        def flush_all(self) -> int:
            return 0

    class _FakeAgent:
        model = snapshot.model
        provider = snapshot.provider
        tools: dict[str, object] = {}
        sessions = _FakeSessions()

        @classmethod
        def from_config(cls, _config, _bus=None, **kwargs):
            seen["agent_kwargs"] = kwargs
            return cls()

        async def run(self) -> None:
            return None

        async def submit_cron_turn(self, msg) -> OutboundMessage:
            seen["cron_message"] = msg
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Cron completed.",
            )

        async def close_mcp(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _FakeChannels:
        enabled_channels = ["feishu"]

        def __init__(self, _config, _bus, **kwargs) -> None:
            seen["channel_kwargs"] = kwargs

        async def start_all(self) -> None:
            return None

        async def stop_all(self) -> None:
            return None

    class _FakeCron:
        def __init__(self, _path: Path) -> None:
            self.on_job = None
            seen["cron"] = self

        async def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def status(self) -> dict[str, int]:
            return {"jobs": 0}

        def register_system_job(self, _job) -> None:
            return None

        def write_run_record(self, run_id: str, record: dict[str, object]) -> None:
            seen.setdefault("run_records", []).append((run_id, record))

    def _no_listener(*_args, **_kwargs):
        raise AssertionError("vps-lite must not start a health/public listener")

    monkeypatch.setattr(builtins, "__import__", _guarded_import)
    monkeypatch.setattr(commands, "sync_workspace_templates", lambda _path: None)
    monkeypatch.setattr(commands, "is_default_workspace", lambda _path: False)
    monkeypatch.setattr(commands, "AgentLoop", _FakeAgent)
    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", _build_snapshot)
    monkeypatch.setattr("nanobot.providers.factory.load_provider_snapshot", _load_snapshot)
    monkeypatch.setattr("nanobot.channels.manager.ChannelManager", _FakeChannels)
    monkeypatch.setattr("nanobot.cron.service.CronService", _FakeCron)
    monkeypatch.setattr("asyncio.start_server", _no_listener)

    commands._run_gateway(config, profile=VPS_LITE_PROFILE)

    assert forbidden_imports == []
    assert seen["snapshot_profile"] is VPS_LITE_PROFILE
    agent_kwargs = seen["agent_kwargs"]
    assert isinstance(agent_kwargs, dict)
    assert agent_kwargs["profile"] is VPS_LITE_PROFILE
    assert agent_kwargs["hooks"] == []
    agent_kwargs["provider_snapshot_loader"](Path("config.json"), preset_name="fast")
    assert seen["loader_call"] == (Path("config.json"), "fast", VPS_LITE_PROFILE)
    channel_kwargs = seen["channel_kwargs"]
    assert isinstance(channel_kwargs, dict)
    assert channel_kwargs == {"runtime_profile": VPS_LITE_PROFILE}

    cron = seen["cron"]
    assert isinstance(cron, _FakeCron)
    response = asyncio.run(
        cron.on_job(
            CronJob(
                id="lite-cron",
                name="Lite reminder",
                payload=CronPayload(
                    kind="agent_turn",
                    message="Check the VPS.",
                    session_key="telegram:user-1",
                    origin_channel="telegram",
                    origin_chat_id="user-1",
                ),
            )
        )
    )

    assert response == "Cron completed."
    assert seen["cron_message"].channel == "telegram"
    assert forbidden_imports == []
