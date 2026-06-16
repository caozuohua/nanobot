import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.google_ai_provider import GoogleAIProvider


def test_google_ai_module_does_not_import_sdk() -> None:
    script = (
        "import builtins\n"
        "original_import = builtins.__import__\n"
        "def guarded_import(name, *args, **kwargs):\n"
        "    if name == 'google': raise RuntimeError('eager Google SDK import')\n"
        "    return original_import(name, *args, **kwargs)\n"
        "builtins.__import__ = guarded_import\n"
        "import nanobot.providers.google_ai_provider"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [os.getcwd(), env.get("PYTHONPATH")])
    )

    subprocess.run([sys.executable, "-c", script], check=True, env=env)


@pytest.mark.asyncio
async def test_google_ai_client_uses_api_key_without_vertex_settings(monkeypatch) -> None:
    import nanobot.providers.google_ai_provider as module

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace()))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(module, "genai", SimpleNamespace(Client=factory))
    provider = GoogleAIProvider(api_key="studio-key", default_model="gemini/gemini-2.5-flash")

    assert await provider._ensure_client() is client
    factory.assert_called_once_with(api_key="studio-key")


@pytest.mark.asyncio
async def test_google_ai_client_cannot_be_created_after_close(monkeypatch) -> None:
    import nanobot.providers.google_ai_provider as module

    factory = MagicMock()
    monkeypatch.setattr(module, "genai", SimpleNamespace(Client=factory))
    provider = GoogleAIProvider(api_key="studio-key", default_model="gemini-2.5-flash")
    await provider._client_lock.acquire()
    ensure_task = asyncio.create_task(provider._ensure_client())
    await asyncio.sleep(0)
    close_task = asyncio.create_task(provider.aclose())
    await asyncio.sleep(0)

    provider._client_lock.release()

    with pytest.raises(RuntimeError, match="closed"):
        await ensure_task
    await close_task
    factory.assert_not_called()


def test_factory_builds_native_google_ai_provider() -> None:
    config = Config.model_validate({
        "agents": {"defaults": {"provider": "gemini", "model": "gemini/gemini-2.5-flash"}},
        "providers": {"gemini": {"apiKey": "studio-key"}},
    })

    provider = make_provider(config, profile="vps-lite")

    assert isinstance(provider, GoogleAIProvider)
    assert provider.get_default_model() == "gemini/gemini-2.5-flash"
