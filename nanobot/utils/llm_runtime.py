"""Small helpers for passing the active LLM provider/model together."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TypeVar

from nanobot.providers.base import LLMProvider

T = TypeVar("T")
_HELD_LLM_GATES: ContextVar[frozenset[int]] = ContextVar(
    "nanobot_held_llm_gates",
    default=frozenset(),
)


@dataclass(slots=True)
class LLMTurnGate:
    """Serialize provider requests and lifecycle changes for one agent loop."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @asynccontextmanager
    async def hold(self) -> AsyncIterator[None]:
        gate_id = id(self)
        held = _HELD_LLM_GATES.get()
        if gate_id in held:
            yield
            return
        async with self.lock:
            token = _HELD_LLM_GATES.set(held | {gate_id})
            try:
                yield
            finally:
                _HELD_LLM_GATES.reset(token)

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
