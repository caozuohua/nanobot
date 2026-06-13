"""PKB and managed repository tools for VPS Lite."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search", "save", "get", "list", "update", "delete", "restore", "health"],
        },
        "query": {"type": "string"},
        "note_id": {"type": "string"},
        "content": {"type": "string"},
        "note_type": {"type": "string", "enum": ["fact", "idea", "task", "question", "code"]},
        "topics": {"type": "array", "items": {"type": "string"}},
        "limit": {"type": "integer", "minimum": 1, "maximum": 100},
    },
    "required": ["action"],
})
class PkbTool(Tool):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    @property
    def name(self) -> str:
        return "pkb"

    @property
    def description(self) -> str:
        return "Search, save, list, update, delete, restore, or health-check the personal knowledge base."

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        base = os.getenv("PKB_BASE_URL", "").rstrip("/")
        secret = os.getenv("PKB_API_SECRET", "")
        if not base or (action != "health" and not secret):
            return "Error: PKB_BASE_URL and PKB_API_SECRET are required"
        note_id = quote(str(kwargs.get("note_id") or ""), safe="")
        method, path, body, params = self._request(action, note_id, kwargs)
        headers = {} if action == "health" else {"x-api-secret": secret}
        try:
            async with httpx.AsyncClient(timeout=10, transport=self.transport) as client:
                response = await client.request(
                    method, f"{base}{path}", headers=headers, json=body, params=params
                )
                response.raise_for_status()
                return json.dumps(response.json(), ensure_ascii=False)
        except (httpx.HTTPError, ValueError) as exc:
            return f"Error: PKB request failed: {exc}"

    @staticmethod
    def _request(
        action: str, note_id: str, values: dict[str, Any]
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]:
        if action == "search":
            return "POST", "/api/pkb/search", {
                "query": values.get("query", ""),
                "limit": values.get("limit", 5),
                "action": "search",
            }, None
        if action == "save":
            return "POST", "/api/pkb", {
                "content": values.get("content", ""),
                "source": "nanobot",
                "type": values.get("note_type", "fact"),
                "topics": values.get("topics", []),
            }, None
        if action == "list":
            return "GET", "/api/pkb/list", None, {"limit": values.get("limit", 50)}
        if action == "health":
            return "GET", "/api/pkb/health", None, None
        if not note_id:
            raise ValueError("note_id is required")
        path = f"/api/pkb/{note_id}"
        if action == "get":
            return "GET", path, None, None
        if action == "delete":
            return "DELETE", path, None, None
        if action == "restore":
            return "POST", f"{path}/restore", None, None
        return "PATCH", path, {
            key: values[key]
            for key in ("content", "topics")
            if values.get(key) is not None
        } | ({"type": values["note_type"]} if values.get("note_type") else {}), None


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["status", "pull", "read", "write", "commit_push", "publish"],
        },
        "repository": {
            "type": "string",
            "enum": ["blog", "pkb", "newsletter"],
        },
        "message": {"type": "string", "maxLength": 200},
        "path": {"type": "string"},
        "content": {"type": "string"},
    },
    "required": ["action", "repository"],
})
class ManagedRepoTool(Tool):
    @property
    def name(self) -> str:
        return "managed_repo"

    @property
    def description(self) -> str:
        return "Inspect, update, commit and push approved VPS repositories; publish the blog."

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        repository = kwargs["repository"]
        allowed = {"blog", "pkb", "newsletter"}
        if repository not in allowed:
            return f"Error: repository must be one of {', '.join(sorted(allowed))}"
        if action in {"read", "write"}:
            return self._file_action(action, repository, kwargs)
        argv = [
            "sudo", "-n", "/usr/local/sbin/nanobot-repo",
            action.replace("_", "-"), repository,
        ]
        if action == "commit_push":
            message = str(kwargs.get("message") or "").strip()
            if not message:
                return "Error: message is required for commit_push"
            argv.append(message)
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        text = (stdout if process.returncode == 0 else stderr).decode(errors="replace").strip()
        return text or ("ok" if process.returncode == 0 else f"Error: exit {process.returncode}")

    @staticmethod
    def _file_action(action: str, repository: str, values: dict[str, Any]) -> str:
        root_value = os.getenv(f"NANOBOT_REPO_{repository.upper()}", "")
        relative = str(values.get("path") or "")
        if not root_value or not relative:
            return "Error: repository root and path are required"
        root = Path(root_value).resolve()
        target = (root / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return "Error: path escapes repository root"
        if action == "read":
            try:
                return target.read_text(encoding="utf-8")
            except OSError as exc:
                return f"Error: {exc}"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(values.get("content") or ""), encoding="utf-8")
        return f"wrote {relative}"
