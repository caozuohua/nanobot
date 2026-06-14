"""Small helpers for passing the active LLM provider/model together."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TypeVar

from nanobot.providers.base import LLMProvider

T = TypeVar("T")


@dataclass(slots=True)
class LLMTurnGate:
    """Serialize provider requests and lifecycle changes for one agent loop."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _owner: asyncio.Task | None = field(default=None, init=False)
    _depth: int = field(default=0, init=False)

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        async with self.lock:
            self._owner = task
            self._depth = 1
            try:
                yield
            finally:
                self._depth = 0
                self._owner = None

    async def run(self, call: Callable[[], Awaitable[T]]) -> T:
        async with self.hold():
            return await call()


@dataclass(frozen=True)
class LLMRuntime:
    provider: LLMProvider
    model: str
    turn_gate: LLMTurnGate | None = None


LLMRuntimeResolver = Callable[[], LLMRuntime]


def static_llm_runtime(provider: LLMProvider, model: str) -> LLMRuntimeResolver:
    runtime = LLMRuntime(provider=provider, model=model)
    return lambda: runtime
