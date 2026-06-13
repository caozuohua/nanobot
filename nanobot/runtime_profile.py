"""Runtime profile selection for constrained deployments."""

from __future__ import annotations

from enum import Enum
from typing import Any

_LITE_TOOL_MODULES = frozenset({
    "filesystem",
    "apply_patch",
    "shell",
    "web",
    "cron",
    "message",
})

_LITE_BUILTIN_SKILLS = frozenset({
    "clawhub",
    "cron",
    "github",
    "memory",
    "skill-creator",
    "summarize",
    "tmux",
    "update-setup",
    "weather",
})


class RuntimeProfileError(RuntimeError):
    """Raised when a runtime profile cannot support the requested capability."""


class RuntimeProfile(str, Enum):
    """Supported runtime profiles."""

    FULL = "full"
    VPS_LITE = "vps-lite"

    @classmethod
    def coerce(cls, value: "RuntimeProfile | str | None") -> "RuntimeProfile":
        """Normalize profile names from config, CLI, or direct construction."""
        if isinstance(value, cls):
            return value
        if value is None:
            return cls.FULL
        normalized = str(value).strip().lower().replace("_", "-")
        if normalized in {"full", "default"}:
            return cls.FULL
        if normalized in {"lite", "vps-lite"}:
            return cls.VPS_LITE
        raise ValueError(f"Unknown runtime profile: {value!r}")

    @property
    def is_lite(self) -> bool:
        return self is self.VPS_LITE

    @property
    def tool_module_allowlist(self) -> frozenset[str] | None:
        return _LITE_TOOL_MODULES if self.is_lite else None

    @property
    def builtin_skill_allowlist(self) -> frozenset[str] | None:
        return _LITE_BUILTIN_SKILLS if self.is_lite else None

    @property
    def entrypoint_plugins_enabled(self) -> bool:
        return not self.is_lite

    def validate_tools_config(self, tools_config: Any) -> None:
        """Fail fast when lite mode is asked to load unsupported configured tools."""
        if not self.is_lite:
            return

        blocked: list[str] = []
        my_cfg = getattr(tools_config, "my", None)
        if getattr(my_cfg, "enable", False):
            blocked.append("tools.my.enable")

        image_cfg = getattr(tools_config, "image_generation", None)
        if getattr(image_cfg, "enabled", False):
            blocked.append("tools.image_generation.enabled")

        cli_cfg = getattr(tools_config, "cli_apps", None)
        if getattr(cli_cfg, "enable", False):
            blocked.append("tools.cli_apps.enable")

        if not blocked:
            return

        joined = ", ".join(blocked)
        raise RuntimeProfileError(
            f"Runtime profile {self.value!r} does not support: {joined}. "
            "Disable those capabilities or switch to the full profile."
        )
