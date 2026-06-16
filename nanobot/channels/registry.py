"""Auto-discovery for built-in channel modules and external plugins."""
from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.channels.base import BaseChannel
    from nanobot.runtime_profile import RuntimeProfile

_INTERNAL = frozenset({"base", "manager", "registry"})


def discover_channel_names(profile: RuntimeProfile | None = None) -> list[str]:
    """Return all built-in channel module names by scanning the package (zero imports)."""
    import nanobot.channels as pkg

    return [
        name
        for _, name, ispkg in pkgutil.iter_modules(pkg.__path__)
        if (
            name not in _INTERNAL
            and not ispkg
            and (profile is None or profile.channels is None or name in profile.channels)
        )
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """Import *module_name* and return the first BaseChannel subclass found."""
    from nanobot.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"nanobot.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in nanobot.channels.{module_name}")


def discover_plugins(
    enabled_names: set[str] | None = None,
    *,
    profile: RuntimeProfile | None = None,
) -> dict[str, type[BaseChannel]]:
    """Discover external channel plugins registered via entry_points."""
    if profile is not None and not profile.allow_entrypoint_plugins:
        return {}

    from importlib.metadata import entry_points

    plugins: dict[str, type[BaseChannel]] = {}
    for ep in entry_points(group="nanobot.channels"):
        if enabled_names is not None and ep.name not in enabled_names:
            continue
        try:
            cls = ep.load()
            plugins[ep.name] = cls
        except Exception as e:
            logger.warning("Failed to load channel plugin '{}': {}", ep.name, e)
    return plugins


def discover_enabled(
    enabled_names: set[str],
    *,
    _names: list[str] | None = None,
    _include_all_external: bool = False,
    profile: RuntimeProfile | None = None,
) -> dict[str, type[BaseChannel]]:
    """Return channels whose module names are in *enabled_names*.

    Uses cheap ``pkgutil.iter_modules`` to list names, then imports only
    those that match — skipping the heavy third-party SDK imports of
    unneeded channels.
    """
    names = _names if _names is not None else discover_channel_names(profile)
    if profile is not None and profile.channels is not None:
        names = [name for name in names if name in profile.channels]

    result: dict[str, type[BaseChannel]] = {}
    for modname in names:
        if modname not in enabled_names:
            continue
        try:
            result[modname] = load_channel_class(modname)
        except ImportError as e:
            logger.debug("Skipping built-in channel '{}': {}", modname, e)

    external = discover_plugins(
        None if _include_all_external else enabled_names,
        profile=profile,
    )
    shadowed = set(external) & set(result)
    if shadowed:
        logger.warning("Plugin(s) shadowed by built-in channels (ignored): {}", shadowed)
    if _include_all_external:
        result.update({k: v for k, v in external.items() if k not in shadowed})
    else:
        result.update({k: v for k, v in external.items() if k not in shadowed and k in enabled_names})

    return result


def discover_all(profile: RuntimeProfile | None = None) -> dict[str, type[BaseChannel]]:
    """Return all channels: built-in (pkgutil) merged with external (entry_points).

    Built-in channels take priority — an external plugin cannot shadow a built-in name.
    """
    names = discover_channel_names(profile)
    return discover_enabled(
        set(names),
        _names=names,
        _include_all_external=True,
        profile=profile,
    )
