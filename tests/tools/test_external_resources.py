import json

import httpx
import pytest

from nanobot.agent.tools.external_resources import ManagedRepoTool, PkbTool


@pytest.mark.asyncio
async def test_pkb_tool_searches_with_secret_header(monkeypatch) -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["header"] = request.headers["x-api-secret"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"items": [{"id": "n1"}]})

    monkeypatch.setenv("PKB_BASE_URL", "https://pkb.example")
    monkeypatch.setenv("PKB_API_SECRET", "secret")
    tool = PkbTool(transport=httpx.MockTransport(handler))

    result = json.loads(await tool.execute(action="search", query="nanobot", limit=3))

    assert result["items"][0]["id"] == "n1"
    assert seen == {
        "header": "secret",
        "body": {"query": "nanobot", "limit": 3, "action": "search"},
    }


@pytest.mark.asyncio
async def test_managed_repo_rejects_unknown_repository() -> None:
    tool = ManagedRepoTool()

    result = await tool.execute(action="status", repository="other")

    assert result.startswith("Error: repository must be one of")


@pytest.mark.asyncio
async def test_managed_repo_write_stays_inside_configured_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_REPO_BLOG", str(tmp_path))
    tool = ManagedRepoTool()

    result = await tool.execute(
        action="write",
        repository="blog",
        path="content/posts/test.md",
        content="# Test\n",
    )
    escaped = await tool.execute(
        action="write",
        repository="blog",
        path="../escape.md",
        content="bad",
    )

    assert result == "wrote content/posts/test.md"
    assert (tmp_path / "content/posts/test.md").read_text(encoding="utf-8") == "# Test\n"
    assert escaped.startswith("Error:")


@pytest.mark.asyncio
async def test_managed_repo_invokes_fixed_wrapper(monkeypatch) -> None:
    calls = []

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ok\n", b""

    async def create(*args, **kwargs):
        calls.append((args, kwargs))
        return Process()

    monkeypatch.setattr("asyncio.create_subprocess_exec", create)
    tool = ManagedRepoTool()

    result = await tool.execute(
        action="commit_push",
        repository="blog",
        message="docs: update post",
    )

    assert result == "ok"
    assert calls[0][0] == (
        "sudo", "-n", "/usr/local/sbin/nanobot-repo",
        "commit-push", "blog", "docs: update post",
    )
