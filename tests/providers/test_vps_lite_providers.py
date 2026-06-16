from __future__ import annotations

import pytest

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.google_ai_provider import GoogleAIProvider
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.vertex_ai_provider import VertexAIProvider
from nanobot.runtime_profile import VPS_LITE_PROFILE, RuntimeProfileError


def _config(
    provider: str,
    model: str,
    provider_config: dict[str, object],
) -> Config:
    return Config.model_validate({
        "agents": {
            "defaults": {
                "provider": provider,
                "model": model,
            }
        },
        "providers": {
            provider: provider_config,
        },
    })


def test_vps_lite_provider_allowlist_is_exact() -> None:
    assert VPS_LITE_PROFILE.providers == frozenset({
        "vertex_ai",
        "gemini",
        "openai",
        "custom",
    })


@pytest.mark.parametrize(
    ("provider_name", "model", "provider_config", "expected_type"),
    [
        (
            "vertex_ai",
            "vertex_ai/gemini-2.5-flash",
            {"project": "demo-project", "location": "us-central1"},
            VertexAIProvider,
        ),
        (
            "gemini",
            "gemini/gemini-2.5-flash",
            {"apiKey": "gemini-key"},
            GoogleAIProvider,
        ),
        (
            "openai",
            "openai/gpt-4.1-mini",
            {"apiKey": "openai-key"},
            OpenAICompatProvider,
        ),
        (
            "custom",
            "custom/local-model",
            {"apiBase": "https://models.example.test/v1"},
            OpenAICompatProvider,
        ),
    ],
)
def test_vps_lite_builds_each_allowed_provider(
    provider_name: str,
    model: str,
    provider_config: dict[str, object],
    expected_type: type,
) -> None:
    provider = make_provider(
        _config(provider_name, model, provider_config),
        profile=VPS_LITE_PROFILE,
    )

    assert isinstance(provider, expected_type)


def test_vps_lite_allows_dynamic_custom_provider_with_api_base() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "companyProxy",
                "model": "companyProxy/gpt-4.1-mini",
            }
        },
        "providers": {
            "companyProxy": {
                "apiBase": "https://company.example.test/v1",
            }
        },
    })

    provider = make_provider(config, profile="vps-lite")

    assert isinstance(provider, OpenAICompatProvider)


def test_vps_lite_dynamic_custom_provider_still_requires_api_base() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "companyProxy",
                "model": "companyProxy/gpt-4.1-mini",
            }
        },
        "providers": {
            "companyProxy": {
                "apiKey": "company-key",
            }
        },
    })

    with pytest.raises(ValueError, match="requires api_base"):
        make_provider(config, profile=VPS_LITE_PROFILE)


def test_vps_lite_rejects_forced_provider_outside_allowlist() -> None:
    config = _config(
        "anthropic",
        "anthropic/claude-sonnet-4-6",
        {"apiKey": "anthropic-key"},
    )

    with pytest.raises(
        RuntimeProfileError,
        match="Provider 'anthropic' is not available in runtime profile 'vps-lite'",
    ):
        make_provider(config, profile=VPS_LITE_PROFILE)


def test_vps_lite_rejects_auto_selected_provider_outside_allowlist() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "auto",
                "model": "anthropic/claude-sonnet-4-6",
            }
        },
        "providers": {
            "anthropic": {
                "apiKey": "anthropic-key",
            }
        },
    })

    with pytest.raises(
        RuntimeProfileError,
        match="Provider 'anthropic' is not available in runtime profile 'vps-lite'",
    ):
        make_provider(config, profile=VPS_LITE_PROFILE)


def test_vps_lite_rejects_fallback_provider_outside_allowlist_eagerly() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "openai",
                "model": "openai/gpt-4.1-mini",
                "fallbackModels": ["backup"],
            }
        },
        "modelPresets": {
            "backup": {
                "provider": "anthropic",
                "model": "anthropic/claude-sonnet-4-6",
            }
        },
        "providers": {
            "openai": {
                "apiKey": "openai-key",
            },
            "anthropic": {
                "apiKey": "anthropic-key",
            },
        },
    })

    with pytest.raises(
        RuntimeProfileError,
        match="Provider 'anthropic' is not available in runtime profile 'vps-lite'",
    ):
        make_provider(config, profile=VPS_LITE_PROFILE)


def test_make_provider_without_profile_preserves_full_behavior() -> None:
    config = _config(
        "anthropic",
        "anthropic/claude-sonnet-4-6",
        {"apiKey": "anthropic-key"},
    )

    provider = make_provider(config)

    assert provider.__class__.__name__ == "AnthropicProvider"
