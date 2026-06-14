"""Fixed model presets for the VPS Lite deployment."""

from __future__ import annotations

import os
from pathlib import Path

from nanobot.config.schema import Config, ModelPresetConfig

_TRUE_VALUES = {"", "1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}

MODELS = (
    ("35-flash", "gemini-3.5-flash"),
    ("31-flash-lite", "gemini-3.1-flash-lite"),
    ("25-pro", "gemini-2.5-pro"),
    ("25-flash", "gemini-2.5-flash"),
    ("25-flash-lite", "gemini-2.5-flash-lite"),
)


def vertex_enabled() -> bool:
    value = os.getenv("NANOBOT_VERTEX_ENABLED", "").strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ValueError(
        "Invalid NANOBOT_VERTEX_ENABLED value "
        f"{value!r}; expected one of: 1, true, yes, on, 0, false, no, off"
    )


def install_vps_model_catalog(config: Config) -> None:
    presets: dict[str, ModelPresetConfig] = {}
    sources = [("studio", "gemini", "AI Studio")]
    if vertex_enabled():
        sources.insert(0, ("vertex", "vertex_ai", "Vertex"))
    for source, provider, label in sources:
        for slug, model in MODELS:
            presets[f"{source}-{slug}"] = ModelPresetConfig(
                label=f"{label} · {model}",
                model=f"{provider}/{model}",
                provider=provider,
                max_tokens=8192,
                context_window_tokens=1_000_000,
                temperature=0.1,
            )
    config.model_presets = presets


def validate_vps_model_selection(config: Config, preset_name: str | None) -> None:
    if preset_name and preset_name.startswith("vertex-") and preset_name not in config.model_presets:
        raise ValueError(
            f"Vertex preset {preset_name!r} is unavailable because "
            "NANOBOT_VERTEX_ENABLED=false"
        )


def load_vps_provider_snapshot(
    config_path: Path | None = None,
    *,
    preset_name: str | None = None,
):
    from nanobot.config.loader import load_config, resolve_config_env_vars
    from nanobot.providers.factory import build_provider_snapshot

    config = resolve_config_env_vars(load_config(config_path))
    install_vps_model_catalog(config)
    return build_provider_snapshot(config, preset_name=preset_name, profile="vps-lite")
