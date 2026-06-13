from dataclasses import FrozenInstanceError

import pytest

import nanobot.runtime_profile as runtime_profile
from nanobot.runtime_profile import get_runtime_profile, resolve_runtime_profile


def test_public_profile_constants_are_used_by_lookup():
    assert get_runtime_profile("full") is runtime_profile.FULL_PROFILE
    assert get_runtime_profile("vps-lite") is runtime_profile.VPS_LITE_PROFILE


def test_full_profile_is_unrestricted_and_permits_plugins_and_stdio_mcp():
    profile = get_runtime_profile("full")

    assert profile.name == "full"
    assert profile.channels is None
    assert profile.providers is None
    assert profile.tools is None
    assert profile.skills is None
    assert profile.allow_entrypoint_plugins is True
    assert profile.allow_stdio_mcp is True


def test_vps_lite_profile_has_explicit_runtime_allowlists():
    profile = get_runtime_profile("vps-lite")

    assert profile.name == "vps-lite"
    assert profile.channels == frozenset({"feishu", "telegram", "discord"})
    assert profile.providers == frozenset({"vertex_ai", "gemini", "openai", "custom"})
    assert profile.tools == frozenset({
        "filesystem",
        "apply_patch",
        "shell",
        "web",
        "cron",
        "message",
        "external_resources",
    })
    assert profile.skills == frozenset({"memory", "cron"})
    assert profile.allow_entrypoint_plugins is False
    assert profile.allow_stdio_mcp is False


def test_runtime_profiles_are_immutable():
    profile = get_runtime_profile("vps-lite")

    with pytest.raises(FrozenInstanceError):
        profile.name = "full"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (" FULL ", "full"),
        (" VPS-LITE ", "vps-lite"),
    ],
)
def test_get_runtime_profile_normalizes_whitespace_and_case(name, expected):
    assert get_runtime_profile(name).name == expected


def test_get_runtime_profile_rejects_unknown_name():
    with pytest.raises(ValueError, match=r"Unknown runtime profile 'minimal'.*full.*vps-lite"):
        get_runtime_profile("minimal")


def test_resolve_runtime_profile_prefers_explicit_name(monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILE", "vps-lite")

    assert resolve_runtime_profile("full").name == "full"


def test_resolve_runtime_profile_uses_environment(monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILE", " VPS-LITE ")

    assert resolve_runtime_profile().name == "vps-lite"


@pytest.mark.parametrize("name", ["", "   "])
def test_resolve_runtime_profile_rejects_explicit_blank_name(name, monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILE", "vps-lite")

    with pytest.raises(ValueError, match="Runtime profile name cannot be blank"):
        resolve_runtime_profile(name)


@pytest.mark.parametrize("name", ["", "   "])
def test_resolve_runtime_profile_rejects_blank_environment_name(name, monkeypatch):
    monkeypatch.setenv("NANOBOT_PROFILE", name)

    with pytest.raises(ValueError, match="Runtime profile name cannot be blank"):
        resolve_runtime_profile()


def test_resolve_runtime_profile_defaults_to_full(monkeypatch):
    monkeypatch.delenv("NANOBOT_PROFILE", raising=False)

    assert resolve_runtime_profile().name == "full"
