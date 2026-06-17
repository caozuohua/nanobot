import pytest

from nanobot.agent.vps_model_catalog import (
    install_vps_model_catalog,
    load_vps_provider_snapshot,
    recover_vps_model_selection,
    vertex_enabled,
)
from nanobot.config.schema import Config


@pytest.mark.parametrize("value", [None, "", "1", "true", "TRUE", "yes", "Yes", "on", "ON"])
def test_vertex_enabled_accepts_true_values(monkeypatch, value) -> None:
    if value is None:
        monkeypatch.delenv("NANOBOT_VERTEX_ENABLED", raising=False)
    else:
        monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", value)

    assert vertex_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "No", "off", "OFF"])
def test_vertex_enabled_accepts_false_values(monkeypatch, value) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", value)

    assert vertex_enabled() is False


def test_vertex_enabled_rejects_invalid_value(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "sometimes")

    with pytest.raises(
        ValueError,
        match="NANOBOT_VERTEX_ENABLED.*sometimes.*1, true, yes, on.*0, false, no, off",
    ):
        vertex_enabled()


def test_vps_catalog_installs_vertex_and_ai_studio_presets(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_VERTEX_ENABLED", raising=False)
    config = Config()

    install_vps_model_catalog(config)

    assert list(config.model_presets) == [
        "vertex-35-flash",
        "vertex-31-flash-lite",
        "vertex-25-pro",
        "vertex-25-flash",
        "vertex-25-flash-lite",
        "studio-35-flash",
        "studio-31-flash-lite",
        "studio-25-pro",
        "studio-25-flash",
        "studio-25-flash-lite",
    ]
    assert config.model_presets["vertex-25-flash"].provider == "vertex_ai"
    assert config.model_presets["studio-25-flash"].provider == "gemini"
    assert config.agents.defaults.fallback_models == [
        "studio-35-flash",
        "studio-31-flash-lite",
    ]


def test_vps_catalog_preserves_user_fallback_models(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_VERTEX_ENABLED", raising=False)
    config = Config.model_validate(
        {
            "agents": {"defaults": {"fallbackModels": ["studio-25-flash"]}},
            "modelPresets": {
                "studio-25-flash": {
                    "model": "gemini/gemini-2.5-flash",
                    "provider": "gemini",
                },
            },
        }
    )

    install_vps_model_catalog(config)

    assert config.agents.defaults.fallback_models == ["studio-25-flash"]


def test_vps_catalog_default_fallbacks_skip_active_studio_preset(monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_VERTEX_ENABLED", raising=False)
    config = Config()
    config.agents.defaults.model_preset = "studio-35-flash"

    install_vps_model_catalog(config)

    assert config.agents.defaults.fallback_models == ["studio-31-flash-lite"]


def test_vps_catalog_omits_vertex_and_retains_all_studio_presets(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "off")
    config = Config()

    install_vps_model_catalog(config)

    assert list(config.model_presets) == [
        "studio-35-flash",
        "studio-31-flash-lite",
        "studio-25-pro",
        "studio-25-flash",
        "studio-25-flash-lite",
    ]
    assert all(preset.provider == "gemini" for preset in config.model_presets.values())


def test_vps_selection_recovers_disabled_vertex_to_available_studio(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    config = Config()
    install_vps_model_catalog(config)

    recovered = recover_vps_model_selection(config, "vertex-25-flash")

    assert recovered == ("vertex-25-flash", "studio-35-flash")
    assert config.agents.defaults.model_preset == "studio-35-flash"
    assert "studio-35-flash" in config.model_presets


def test_vps_selection_leaves_studio_selection_unchanged(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    config = Config()
    install_vps_model_catalog(config)

    recovered = recover_vps_model_selection(config, "studio-25-flash")

    assert recovered is None
    assert config.agents.defaults.model_preset == "studio-25-flash"


def test_vps_snapshot_loader_injects_catalog_after_reloading_config(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("NANOBOT_VERTEX_ENABLED", raising=False)
    path = tmp_path / "config.json"
    path.write_text(
        '{"providers":{"vertex_ai":{"project":"demo","location":"us-central1"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "unused.json")

    snapshot = load_vps_provider_snapshot(path, preset_name="vertex-25-flash-lite")

    assert snapshot.model == "vertex_ai/gemini-2.5-flash-lite"


def test_vps_snapshot_loader_rejects_disabled_vertex_without_building_provider(
    tmp_path, monkeypatch,
) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    monkeypatch.setattr(
        "nanobot.providers.factory.make_provider",
        lambda *args, **kwargs: pytest.fail("provider construction must not be reached"),
    )

    with pytest.raises(KeyError, match="vertex-25-flash-lite"):
        load_vps_provider_snapshot(path, preset_name="vertex-25-flash-lite")
