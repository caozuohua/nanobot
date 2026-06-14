"""Runtime feature allowlists for full and reduced nanobot distributions."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


class RuntimeProfileError(RuntimeError):
    """Raised when a runtime profile cannot support a requested capability."""


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

    @classmethod
    def coerce(cls, value: RuntimeProfile | str | None) -> RuntimeProfile:
        """Normalize a profile object or name."""
        if isinstance(value, cls):
            return value
        return resolve_runtime_profile(value)

    @property
    def is_lite(self) -> bool:
        return self.name == "vps-lite"

    @property
    def tool_module_allowlist(self) -> frozenset[str] | None:
        return self.tools

    @property
    def builtin_skill_allowlist(self) -> frozenset[str] | None:
        return self.skills

    @property
    def entrypoint_plugins_enabled(self) -> bool:
        return self.allow_entrypoint_plugins

    def validate_tools_config(self, tools_config: Any) -> None:
        """Fail fast when the profile cannot support configured tools."""
        if not self.is_lite or tools_config is None:
            return

        blocked: list[str] = []
        checks = (
            ("my", "enable"),
            ("image_generation", "enabled"),
            ("cli_apps", "enable"),
        )
        for section_name, flag_name in checks:
            section = getattr(tools_config, section_name, None)
            if getattr(section, flag_name, False):
                blocked.append(f"tools.{section_name}.{flag_name}")

        if blocked:
            raise RuntimeProfileError(
                f"Runtime profile {self.name!r} does not support: {', '.join(blocked)}. "
                "Disable those capabilities or switch to the full profile."
            )


FULL_PROFILE = RuntimeProfile(
    name="full",
    channels=None,
    providers=None,
    tools=None,
    skills=None,
    allow_entrypoint_plugins=True,
    allow_stdio_mcp=True,
)

VPS_LITE_PROFILE = RuntimeProfile(
    name="vps-lite",
    channels=frozenset({"feishu", "telegram", "discord"}),
    providers=frozenset({"vertex_ai", "gemini", "openai", "custom"}),
    tools=frozenset({
        "filesystem", "apply_patch", "shell", "web", "cron", "message",
        "external_resources", "long_task",
    }),
    skills=frozenset({"memory", "cron"}),
    allow_entrypoint_plugins=False,
    allow_stdio_mcp=False,
)

_PROFILES = {
    FULL_PROFILE.name: FULL_PROFILE,
    VPS_LITE_PROFILE.name: VPS_LITE_PROFILE,
}


def get_runtime_profile(name: str) -> RuntimeProfile:
    """Return a named runtime profile."""
    normalized = name.strip().lower().replace("_", "-")
    if not normalized:
        raise ValueError("Runtime profile name cannot be blank")
    aliases = {"default": "full", "lite": "vps-lite"}
    normalized = aliases.get(normalized, normalized)
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
    return FULL_PROFILE if selected is None else get_runtime_profile(selected)
