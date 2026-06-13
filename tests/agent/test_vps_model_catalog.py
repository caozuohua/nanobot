from nanobot.agent.vps_model_catalog import install_vps_model_catalog, load_vps_provider_snapshot
from nanobot.config.schema import Config


def test_vps_catalog_installs_vertex_and_ai_studio_presets() -> None:
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


def test_vps_snapshot_loader_injects_catalog_after_reloading_config(tmp_path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        '{"providers":{"vertex_ai":{"project":"demo","location":"us-central1"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "unused.json")

    snapshot = load_vps_provider_snapshot(path, preset_name="vertex-25-flash-lite")

    assert snapshot.model == "vertex_ai/gemini-2.5-flash-lite"
