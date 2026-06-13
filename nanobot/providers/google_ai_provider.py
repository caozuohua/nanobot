"""Native Google AI Studio provider using the Google Gen AI SDK."""

from __future__ import annotations

import asyncio
from typing import Any

from nanobot.providers.vertex_ai_provider import VertexAIProvider

try:
    from google import genai
except ImportError:
    genai = None


class GoogleAIProvider(VertexAIProvider):
    """Gemini API provider authenticated with an AI Studio API key."""

    def __init__(self, api_key: str | None, default_model: str) -> None:
        super().__init__(default_model=default_model)
        self.api_key = api_key or ""
        self._client_lock = asyncio.Lock()

    @staticmethod
    def _load_sdk() -> Any:
        global genai
        if genai is None:
            from google import genai as google_genai

            genai = google_genai
        return genai

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                if not self.api_key:
                    raise RuntimeError("Google AI Studio requires GEMINI_API_KEY")
                self._client = self._load_sdk().Client(api_key=self.api_key)
        return self._client

    @staticmethod
    def _request_model_name(model: str) -> str:
        if "/" not in model:
            return model
        prefix, routed_model = model.split("/", 1)
        return routed_model if prefix.lower() == "gemini" else model
