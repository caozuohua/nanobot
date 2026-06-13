from nanobot.agent.vps_model_catalog import install_vps_model_catalog
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
