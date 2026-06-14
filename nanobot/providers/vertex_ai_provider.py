"""Vertex AI provider backed by the optional Google Gen AI SDK."""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
import uuid
from typing import Any

from nanobot.providers.base import (
    LLMProvider,
    LLMResponse,
    ToolCallRequest,
    tool_arguments_object_for_replay,
)

genai: Any = None


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


class VertexAIProvider(LLMProvider):
    """Google Vertex AI Gemini provider using ADC authentication."""

    def __init__(
        self,
        *,
        project: str | None = None,
        location: str | None = None,
        default_model: str = "gemini-2.5-flash",
    ) -> None:
        super().__init__()
        self.project = project
        self.location = location
        self.default_model = default_model
        self._client: Any = None
        self._client_lock = asyncio.Lock()
        self._global_client: Any = None
        self._global_client_lock = asyncio.Lock()

    @staticmethod
    def _load_sdk() -> Any:
        global genai
        if genai is None:
            try:
                from google import genai as google_genai
            except ImportError as exc:
                raise RuntimeError(
                    "Vertex AI requires the 'google-genai' package. "
                    "Install it with: pip install google-genai"
                ) from exc
            genai = google_genai
        return genai

    async def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                sdk = self._load_sdk()
                self._client = sdk.Client(
                    vertexai=True,
                    project=self.project,
                    location=self.location,
                )
        return self._client

    async def _client_for_model(self, model: str) -> Any:
        requested = self._request_model_name(model)
        if requested.startswith(("gemini-3.", "gemini-3-")) and self.location != "global":
            if self._global_client is not None:
                return self._global_client
            async with self._global_client_lock:
                if self._global_client is None:
                    sdk = self._load_sdk()
                    self._global_client = sdk.Client(
                        vertexai=True,
                        project=self.project,
                        location="global",
                    )
            return self._global_client
        return await self._ensure_client()

    async def aclose(self) -> None:
        clients = (self._client, self._global_client)
        self._client = None
        self._global_client = None

        closed: set[int] = set()
        for client in clients:
            if client is None or id(client) in closed:
                continue
            closed.add(id(client))
            close = getattr(client, "aclose", None) or getattr(client, "close", None)
            if close is None:
                continue
            result = close()
            if inspect.isawaitable(result):
                await result

    @staticmethod
    def _request_model_name(model: str) -> str:
        if "/" not in model:
            return model
        prefix, routed_model = model.split("/", 1)
        if prefix.lower().replace("-", "_") == "vertex_ai":
            return routed_model
        return model

    @staticmethod
    def _content_parts(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"text": content or "(empty)"}]
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, str):
                    parts.append({"text": block})
                elif isinstance(block, dict) and block.get("type") in {
                    "text",
                    "input_text",
                    "output_text",
                }:
                    if block.get("text"):
                        parts.append({"text": block["text"]})
            return parts or [{"text": "(empty)"}]
        if content is None:
            return [{"text": "(empty)"}]
        return [{"text": str(content)}]

    @classmethod
    def _convert_messages(
        cls,
        messages: list[dict[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []
        tool_names: dict[str, str] = {}

        for message in messages:
            role = message.get("role")
            if role == "system":
                content = message.get("content")
                if isinstance(content, str) and content:
                    system_parts.append(content)
                continue

            if role == "tool":
                name = tool_names.get(str(message.get("tool_call_id") or ""))
                name = name or str(message.get("name") or "tool")
                raw_content = message.get("content")
                if isinstance(raw_content, str):
                    try:
                        parsed = json.loads(raw_content)
                    except (TypeError, ValueError):
                        parsed = raw_content
                else:
                    parsed = raw_content
                response = parsed if isinstance(parsed, dict) else {"result": parsed}
                part = {"function_response": {"name": name, "response": response}}
                if (
                    contents
                    and contents[-1]["role"] == "user"
                    and all("function_response" in item for item in contents[-1]["parts"])
                ):
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({
                        "role": "user",
                        "parts": [part],
                    })
                continue

            tool_calls = message.get("tool_calls") or []
            parts = (
                []
                if role == "assistant" and tool_calls and message.get("content") is None
                else cls._content_parts(message.get("content"))
            )
            if role == "assistant":
                for tool_call in tool_calls:
                    function = _get(tool_call, "function", {})
                    call_id = str(_get(tool_call, "id", "") or "")
                    name = str(_get(function, "name", "") or "")
                    if call_id:
                        tool_names[call_id] = name
                    part = {
                        "function_call": {
                            "id": call_id or None,
                            "name": name,
                            "args": tool_arguments_object_for_replay(
                                _get(function, "arguments", {})
                            ),
                        }
                    }
                    extra_content = _get(tool_call, "extra_content", {}) or {}
                    google_extra = _get(extra_content, "google", {}) or {}
                    encoded_signature = _get(google_extra, "thought_signature")
                    if isinstance(encoded_signature, str) and encoded_signature:
                        try:
                            part["thought_signature"] = base64.b64decode(
                                encoded_signature,
                                validate=True,
                            )
                        except ValueError:
                            pass
                    parts.append(part)
            contents.append({
                "role": "model" if role == "assistant" else "user",
                "parts": parts,
            })

        return ("\n\n".join(system_parts) or None), contents

    @staticmethod
    def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        declarations = []
        for tool in tools:
            function = tool.get("function", tool)
            declarations.append({
                "name": function.get("name"),
                "description": function.get("description"),
                "parameters_json_schema": function.get("parameters") or {
                    "type": "object",
                    "properties": {},
                },
            })
        return [{"function_declarations": declarations}]

    @staticmethod
    def _tool_config(tool_choice: str | dict[str, Any] | None) -> dict[str, Any] | None:
        if tool_choice in (None, "auto"):
            return None
        mode = "ANY" if tool_choice == "required" or isinstance(tool_choice, dict) else "NONE"
        function_config: dict[str, Any] = {"mode": mode}
        if isinstance(tool_choice, dict):
            function = tool_choice.get("function", tool_choice)
            if function.get("name"):
                function_config["allowed_function_names"] = [function["name"]]
        return {"function_calling_config": function_config}

    @staticmethod
    def _extract_usage(response: Any) -> dict[str, int]:
        usage = _get(response, "usage_metadata")
        if not usage:
            return {}
        result = {
            "prompt_tokens": int(_get(usage, "prompt_token_count", 0) or 0),
            "completion_tokens": int(_get(usage, "candidates_token_count", 0) or 0),
            "total_tokens": int(_get(usage, "total_token_count", 0) or 0),
        }
        cached = int(_get(usage, "cached_content_token_count", 0) or 0)
        if cached:
            result["cached_tokens"] = cached
        return result

    @classmethod
    def _parse_response(cls, response: Any) -> LLMResponse:
        candidates = _get(response, "candidates", []) or []
        if not candidates:
            return LLMResponse(content="Error: Vertex AI returned no candidates.", finish_reason="error")

        candidate = candidates[0]
        content = _get(candidate, "content")
        parts = _get(content, "parts", []) or []
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for part in parts:
            text = _get(part, "text")
            if text:
                text_parts.append(str(text))
            function_call = _get(part, "function_call")
            if function_call:
                thought_signature = _get(part, "thought_signature")
                extra_content = None
                if isinstance(thought_signature, bytes) and thought_signature:
                    extra_content = {
                        "google": {
                            "thought_signature": base64.b64encode(
                                thought_signature
                            ).decode("ascii"),
                        }
                    }
                tool_calls.append(ToolCallRequest(
                    id=str(_get(function_call, "id") or f"call_{uuid.uuid4().hex}"),
                    name=str(_get(function_call, "name") or ""),
                    arguments=_get(function_call, "args", {}) or {},
                    extra_content=extra_content,
                ))

        finish_value = _get(candidate, "finish_reason", "STOP")
        finish_name = str(getattr(finish_value, "value", finish_value) or "STOP").upper()
        if tool_calls:
            finish_reason = "tool_calls"
        elif finish_name == "MAX_TOKENS":
            finish_reason = "length"
        elif finish_name == "STOP":
            finish_reason = "stop"
        else:
            finish_reason = finish_name.lower()

        response_text = "".join(text_parts) or None
        if tool_calls and response_text and response_text.strip().lower() == "(empty)":
            response_text = None

        return LLMResponse(
            content=response_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=cls._extract_usage(response),
        )

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
        _ = reasoning_effort
        system_instruction, contents = self._convert_messages(messages)
        config: dict[str, Any] = {
            "max_output_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if system_instruction:
            config["system_instruction"] = system_instruction
        if tools:
            config["tools"] = self._convert_tools(tools)
            if tool_config := self._tool_config(tool_choice):
                config["tool_config"] = tool_config

        try:
            requested_model = model or self.default_model
            client = await self._client_for_model(requested_model)
            response = await client.aio.models.generate_content(
                model=self._request_model_name(requested_model),
                contents=contents,
                config=config,
            )
            return self._parse_response(response)
        except Exception as exc:
            return LLMResponse(
                content=f"Error calling Vertex AI: {exc}",
                finish_reason="error",
            )

    def get_default_model(self) -> str:
        return self.default_model
