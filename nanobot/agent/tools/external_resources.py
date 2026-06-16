"""Managed repository tools for VPS Lite."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from nanobot.agent.tools.base import Tool, tool_parameters


@tool_parameters({
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["status", "pull", "read", "write", "commit_push", "publish"],
        },
        "repository": {
            "type": "string",
            "enum": ["blog", "newsletter"],
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
        allowed = {"blog", "newsletter"}
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
