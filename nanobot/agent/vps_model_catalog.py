"""Fixed model presets for the VPS Lite deployment."""

from __future__ import annotations

from nanobot.config.schema import Config, ModelPresetConfig

MODELS = (
    ("35-flash", "gemini-3.5-flash"),
    ("31-flash-lite", "gemini-3.1-flash-lite"),
    ("25-pro", "gemini-2.5-pro"),
    ("25-flash", "gemini-2.5-flash"),
    ("25-flash-lite", "gemini-2.5-flash-lite"),
)


def install_vps_model_catalog(config: Config) -> None:
    presets: dict[str, ModelPresetConfig] = {}
    for source, provider, label in (
        ("vertex", "vertex_ai", "Vertex"),
        ("studio", "gemini", "AI Studio"),
    ):
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
