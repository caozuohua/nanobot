from typing import Any

import pytest

from nanobot.providers.base import LLMProvider, LLMResponse


class MinimalProvider(LLMProvider):
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="")

    def get_default_model(self) -> str:
        return "test-model"


@pytest.mark.asyncio
async def test_aclose_is_safe_async_noop() -> None:
    provider = MinimalProvider()

    assert await provider.aclose() is None
