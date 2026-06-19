from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import typer
from typer.testing import CliRunner

import nanobot.cli.commands as commands
from nanobot.bus.events import OutboundMessage
from nanobot.config.schema import Config
from nanobot.cron.types import CronJob, CronPayload
from nanobot.providers.factory import ProviderSnapshot
from nanobot.runtime_profile import FULL_PROFILE, VPS_LITE_PROFILE

runner = CliRunner()


class _StopGatewayError(RuntimeError):
    pass


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
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args, **_kwargs: config)
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
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args, **_kwargs: config)

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
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        commands,
        "_run_gateway",
        lambda *_args, **_kwargs: pytest.fail("runtime must not start"),
    )

    result = runner.invoke(commands.app, ["gateway", "--profile", "vps-lite"])

    assert result.exit_code == 1
    assert expected in result.stdout


def test_gateway_allows_self_tool_in_vps_lite(monkeypatch, tmp_path: Path) -> None:
    config = _lite_config(tmp_path)
    config.tools.my.enable = True
    seen: list[object] = []
    monkeypatch.setattr(commands, "_load_runtime_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        commands,
        "_run_gateway",
        lambda _config, **kwargs: seen.append(kwargs["profile"]),
    )

    result = runner.invoke(commands.app, ["gateway", "--profile", "vps-lite"])

    assert result.exit_code == 0
    assert seen == [VPS_LITE_PROFILE]


@pytest.mark.parametrize("selection_source", ["persisted", "default"])
def test_vps_lite_gateway_recovers_disabled_vertex_selection_before_provider_construction(
    monkeypatch,
    tmp_path: Path,
    selection_source: str,
) -> None:
    from nanobot.agent.model_selection import load_model_selection, save_model_selection
    from nanobot.config.loader import save_config, set_config_path

    config = _lite_config(tmp_path)
    config_file = tmp_path / "config.json"
    config.providers.gemini.api_key = "studio-key"
    config.agents.defaults.model_preset = (
        "vertex-25-flash" if selection_source == "default" else "studio-25-flash"
    )
    save_config(config, config_file)
    set_config_path(config_file)
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    if selection_source == "persisted":
        save_model_selection(
            config.workspace_path / ".runtime" / "model-selection.json",
            "vertex-25-flash",
        )
    warnings: list[str] = []

    def _build_provider(recovered, *, profile=None):
        assert profile is VPS_LITE_PROFILE
        assert recovered.agents.defaults.model_preset == "studio-35-flash"
        persisted = json.loads(config_file.read_text(encoding="utf-8"))
        assert persisted["agents"]["defaults"]["modelPreset"] == "studio-35-flash"
        assert load_model_selection(
            config.workspace_path / ".runtime" / "model-selection.json"
        ) == "studio-35-flash"
        assert set(recovered.model_presets) == {
            "studio-35-flash",
            "studio-31-flash-lite",
            "studio-25-pro",
            "studio-25-flash",
            "studio-25-flash-lite",
        }
        raise _StopGatewayError("stop")

    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", _build_provider)
    monkeypatch.setattr(commands.logger, "warning", lambda message: warnings.append(message))

    with pytest.raises(_StopGatewayError):
        commands._run_gateway(config, profile=VPS_LITE_PROFILE)

    assert len(warnings) == 1
    assert "vertex-25-flash" in warnings[0]
    assert "studio-35-flash" in warnings[0]
    persisted = json.loads(config_file.read_text(encoding="utf-8"))
    assert persisted["providers"]["gemini"]["apiKey"] == "studio-key"


def test_vps_lite_gateway_recovery_preserves_env_secret_placeholder(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.json"
    workspace = tmp_path / "workspace"
    secret = "resolved-studio-secret"
    config_file.write_text(
        json.dumps(
            {
                "agents": {
                    "defaults": {
                        "workspace": str(workspace),
                        "modelPreset": "vertex-25-flash",
                        "dream": {"enabled": False},
                    }
                },
                "providers": {"gemini": {"apiKey": "${GEMINI_API_KEY}"}},
                "modelPresets": {
                    "vertex-25-flash": {
                        "model": "vertex_ai/gemini-2.5-flash",
                        "provider": "vertex_ai",
                    },
                    "custom-local": {
                        "model": "openai/custom-model",
                        "provider": "openai",
                        "temperature": 0.42,
                    },
                },
                "channels": {"unknownSentinel": {"keep": ["exactly", 7]}},
                "gateway": {"heartbeat": {"enabled": False}},
                "tools": {
                    "my": {"enable": False},
                    "imageGeneration": {"enabled": False},
                    "cliApps": {"enable": False},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")

    def _build_provider(runtime_config, *, profile=None):
        assert profile is VPS_LITE_PROFILE
        assert runtime_config.providers.gemini.api_key == secret
        saved_text = config_file.read_text(encoding="utf-8")
        saved = json.loads(saved_text)
        assert saved["agents"]["defaults"]["modelPreset"] == "studio-35-flash"
        assert saved["providers"]["gemini"]["apiKey"] == "${GEMINI_API_KEY}"
        assert secret not in saved_text
        assert saved["channels"]["unknownSentinel"] == {"keep": ["exactly", 7]}
        assert saved["modelPresets"] == {
            "vertex-25-flash": {
                "model": "vertex_ai/gemini-2.5-flash",
                "provider": "vertex_ai",
            },
            "custom-local": {
                "model": "openai/custom-model",
                "provider": "openai",
                "temperature": 0.42,
            },
        }
        assert "studio-35-flash" not in saved["modelPresets"]
        raise _StopGatewayError("stop")

    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", _build_provider)

    result = runner.invoke(
        commands.app,
        ["gateway", "--config", str(config_file), "--profile", "vps-lite"],
    )

    assert isinstance(result.exception, _StopGatewayError)
    restarted = runner.invoke(
        commands.app,
        ["gateway", "--config", str(config_file), "--profile", "vps-lite"],
    )
    assert isinstance(restarted.exception, _StopGatewayError)


def test_vps_lite_gateway_reports_missing_env_before_provider_construction(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config = _lite_config(tmp_path)
    config.providers.gemini.api_key = "${MISSING_GEMINI_API_KEY}"
    monkeypatch.delenv("MISSING_GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(
        "nanobot.providers.factory.build_provider_snapshot",
        lambda *_args, **_kwargs: pytest.fail("provider construction must not be reached"),
    )

    with pytest.raises(typer.Exit):
        commands._run_gateway(config, profile=VPS_LITE_PROFILE)


def test_vps_lite_gateway_failed_studio_provider_does_not_try_vertex(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from nanobot.config.loader import set_config_path

    config = _lite_config(tmp_path)
    config.agents.defaults.model_preset = "vertex-25-flash"
    set_config_path(tmp_path / "config.json")
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    attempts: list[str | None] = []

    def _build_provider(recovered, *, profile=None):
        attempts.append(recovered.resolve_preset().provider)
        raise ValueError("AI Studio credentials invalid")

    monkeypatch.setattr("nanobot.providers.factory.build_provider_snapshot", _build_provider)

    with pytest.raises(typer.Exit):
        commands._run_gateway(config, profile=VPS_LITE_PROFILE)

    assert attempts == ["gemini"]


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

        async def stop(self) -> None:
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
    monkeypatch.setattr(
        "nanobot.agent.vps_model_catalog.load_vps_provider_snapshot",
        _load_snapshot,
    )
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
    assert seen["loader_call"] == (Path("config.json"), "fast", None)
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
