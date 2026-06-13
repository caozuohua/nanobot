from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from nanobot.config.schema import Config
from nanobot.providers.factory import make_provider
from nanobot.providers.vertex_ai_provider import VertexAIProvider


def _response(
    *,
    text: str | None = None,
    function_call: object | None = None,
    finish_reason: str = "STOP",
) -> SimpleNamespace:
    part = SimpleNamespace(text=text, function_call=function_call)
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=[part]),
                finish_reason=finish_reason,
            )
        ],
        usage_metadata=SimpleNamespace(
            prompt_token_count=7,
            candidates_token_count=3,
            total_token_count=10,
            cached_content_token_count=2,
        ),
    )


@pytest.mark.asyncio
async def test_client_is_created_lazily_with_vertex_project_and_location(monkeypatch) -> None:
    import nanobot.providers.vertex_ai_provider as vertex_module

    sdk_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace()))
    client_factory = MagicMock(return_value=sdk_client)
    monkeypatch.setattr(vertex_module, "genai", SimpleNamespace(Client=client_factory))

    provider = VertexAIProvider(
        project="demo-project",
        location="us-central1",
        default_model="gemini-2.5-flash",
    )

    assert provider._client is None
    assert await provider._ensure_client() is sdk_client
    client_factory.assert_called_once_with(
        vertexai=True,
        project="demo-project",
        location="us-central1",
    )


@pytest.mark.asyncio
async def test_chat_returns_text_and_usage_from_async_sdk() -> None:
    generate_content = AsyncMock(return_value=_response(text="Hello from Vertex"))
    provider = VertexAIProvider(
        project="demo-project",
        location="us-central1",
        default_model="vertex_ai/gemini-2.5-flash",
    )
    provider._client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content),
        )
    )

    result = await provider.chat(
        messages=[
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": "Hello"},
        ],
        max_tokens=256,
        temperature=0.2,
    )

    assert result.content == "Hello from Vertex"
    assert result.finish_reason == "stop"
    assert result.usage == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
        "cached_tokens": 2,
    }
    kwargs = generate_content.await_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    assert kwargs["config"]["system_instruction"] == "Be concise."
    assert kwargs["config"]["max_output_tokens"] == 256
    assert kwargs["config"]["temperature"] == 0.2
    assert kwargs["contents"][0]["role"] == "user"


@pytest.mark.asyncio
async def test_vertex_3x_models_use_global_location(monkeypatch) -> None:
    import nanobot.providers.vertex_ai_provider as vertex_module

    response = _response(text="ok")
    global_client = SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=response)))
    )
    factory = MagicMock(return_value=global_client)
    monkeypatch.setattr(vertex_module, "genai", SimpleNamespace(Client=factory))
    provider = VertexAIProvider(
        project="demo-project",
        location="us-central1",
        default_model="vertex_ai/gemini-3.1-flash-lite",
    )

    result = await provider.chat(messages=[{"role": "user", "content": "hello"}])

    assert result.content == "ok"
    factory.assert_called_once_with(
        vertexai=True,
        project="demo-project",
        location="global",
    )


@pytest.mark.asyncio
async def test_chat_returns_function_calls() -> None:
    function_call = SimpleNamespace(
        id="call-123",
        name="read_file",
        args={"path": "README.md"},
    )
    generate_content = AsyncMock(return_value=_response(function_call=function_call))
    provider = VertexAIProvider(default_model="gemini-2.5-flash")
    provider._client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content),
        )
    )

    result = await provider.chat(
        messages=[{"role": "user", "content": "Read the README"}],
        tools=[{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
        }],
        tool_choice="required",
    )

    assert result.content is None
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].id == "call-123"
    assert result.tool_calls[0].name == "read_file"
    assert result.tool_calls[0].arguments == {"path": "README.md"}
    config = generate_content.await_args.kwargs["config"]
    assert config["tools"][0]["function_declarations"][0]["name"] == "read_file"
    assert config["tool_config"]["function_calling_config"]["mode"] == "ANY"


def test_tool_history_replays_function_call_without_synthetic_text() -> None:
    _, contents = VertexAIProvider._convert_messages([
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call-123",
                "type": "function",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call-123",
            "content": '{"text":"contents"}',
        },
    ])

    assert contents[0] == {
        "role": "model",
        "parts": [{
            "function_call": {
                "id": "call-123",
                "name": "read_file",
                "args": {"path": "README.md"},
            }
        }],
    }
    assert contents[1]["parts"][0]["function_response"]["name"] == "read_file"


def test_parse_and_replay_preserves_thought_signature() -> None:
    signature = b"opaque-thought-signature"
    function_call = SimpleNamespace(
        id="call-123",
        name="web_search",
        args={"query": "nanobot"},
    )
    response = _response(function_call=function_call)
    response.candidates[0].content.parts[0].thought_signature = signature

    parsed = VertexAIProvider._parse_response(response)
    payload = parsed.tool_calls[0].to_openai_tool_call()
    _, contents = VertexAIProvider._convert_messages([{
        "role": "assistant",
        "content": None,
        "tool_calls": [payload],
    }])

    assert parsed.tool_calls[0].extra_content == {
        "google": {
            "thought_signature": base64.b64encode(signature).decode("ascii"),
        }
    }
    assert contents[0]["parts"][0]["thought_signature"] == signature


def test_factory_builds_vertex_provider_with_project_and_location() -> None:
    config = Config.model_validate({
        "agents": {
            "defaults": {
                "provider": "vertex_ai",
                "model": "vertex_ai/gemini-2.5-flash",
            }
        },
        "providers": {
            "vertex_ai": {
                "project": "demo-project",
                "location": "us-central1",
            }
        },
    })

    provider = make_provider(config)

    assert isinstance(provider, VertexAIProvider)
    assert provider.project == "demo-project"
    assert provider.location == "us-central1"
    assert provider.get_default_model() == "vertex_ai/gemini-2.5-flash"
