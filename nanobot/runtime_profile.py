"""Runtime feature allowlists for full and reduced nanobot distributions."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeProfile:
    """Immutable runtime and packaging feature selection."""

    name: str
    channels: frozenset[str] | None
    providers: frozenset[str] | None
    tools: frozenset[str] | None
    skills: frozenset[str] | None
    allow_entrypoint_plugins: bool
    allow_stdio_mcp: bool


_PROFILES = {
    "full": RuntimeProfile(
        name="full",
        channels=None,
        providers=None,
        tools=None,
        skills=None,
        allow_entrypoint_plugins=True,
        allow_stdio_mcp=True,
    ),
    "vps-lite": RuntimeProfile(
        name="vps-lite",
        channels=frozenset({"feishu", "telegram", "discord"}),
        providers=frozenset({"vertex_ai", "gemini", "openai", "custom"}),
        tools=frozenset({"filesystem", "apply_patch", "shell", "web", "cron", "message"}),
        skills=frozenset({"memory", "cron"}),
        allow_entrypoint_plugins=False,
        allow_stdio_mcp=False,
    ),
}


def get_runtime_profile(name: str) -> RuntimeProfile:
    """Return a named runtime profile."""
    normalized = name.strip().lower()
    try:
        return _PROFILES[normalized]
    except KeyError:
        available = ", ".join(sorted(_PROFILES))
        raise ValueError(
            f"Unknown runtime profile {normalized!r}. Available profiles: {available}"
        ) from None


def resolve_runtime_profile(name: str | None = None) -> RuntimeProfile:
    """Resolve an explicit profile, then NANOBOT_PROFILE, then the full profile."""
    selected = name if name is not None else os.environ.get("NANOBOT_PROFILE")
    return get_runtime_profile(selected or "full")
