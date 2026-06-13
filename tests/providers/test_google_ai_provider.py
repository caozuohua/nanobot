from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.google_ai_provider import GoogleAIProvider


@pytest.mark.asyncio
async def test_google_ai_client_uses_api_key_without_vertex_settings(monkeypatch) -> None:
    import nanobot.providers.google_ai_provider as module

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace()))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(module, "genai", SimpleNamespace(Client=factory))
    provider = GoogleAIProvider(api_key="studio-key", default_model="gemini/gemini-2.5-flash")

    assert await provider._ensure_client() is client
    factory.assert_called_once_with(api_key="studio-key")


def test_factory_builds_native_google_ai_provider() -> None:
    config = Config.model_validate({
        "agents": {"defaults": {"provider": "gemini", "model": "gemini/gemini-2.5-flash"}},
        "providers": {"gemini": {"apiKey": "studio-key"}},
    })

    provider = make_provider(config, profile="vps-lite")

    assert isinstance(provider, GoogleAIProvider)
    assert provider.get_default_model() == "gemini/gemini-2.5-flash"
