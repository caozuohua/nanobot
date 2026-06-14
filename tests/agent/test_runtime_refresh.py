from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.config.loader import save_config
from nanobot.config.schema import Config
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
