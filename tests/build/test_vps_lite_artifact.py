from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

import pytest
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[2]

LITE_DEPENDENCIES = {
    "chardet",
    "croniter",
    "ddgs",
    "discord-py",
    "filelock",
    "google-genai",
    "httpx",
    "jinja2",
    "json-repair",
    "lark-oapi",
    "loguru",
    "lxml-html-clean",
    "mcp",
    "openai",
    "prompt-toolkit",
    "pydantic",
    "pydantic-settings",
    "python-telegram-bot",
    "pyyaml",
    "readability-lxml",
    "rich",
    "tiktoken",
    "typer",
}

EXCLUDED_DEPENDENCIES = {
    "anthropic",
    "boto3",
    "dingtalk-stream",
    "matrix-nio",
    "openpyxl",
    "pypdf",
    "python-docx",
    "python-pptx",
    "qq-botpy",
    "slack-sdk",
    "slackify-markdown",
}

SUPPORTED_CHANNEL_MODULES = {
    "__init__.py",
    "base.py",
    "discord.py",
    "feishu.py",
    "manager.py",
    "registry.py",
    "telegram.py",
}
SUPPORTED_PROVIDER_MODULES = {
    "__init__.py",
    "base.py",
    "factory.py",
    "fallback_provider.py",
    "openai_compat_provider.py",
    "registry.py",
    "vertex_ai_provider.py",
}


def _build_wheel(output_dir: Path, profile: str | None) -> Path:
    env = os.environ.copy()
    env.pop("NANOBOT_BUILD_PROFILE", None)
    env["NANOBOT_SKIP_WEBUI_BUILD"] = "1"
    if profile is not None:
        env["NANOBOT_BUILD_PROFILE"] = profile

    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(output_dir),
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(output_dir.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture(scope="module")
def lite_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    configured = os.environ.get("NANOBOT_VPS_LITE_WHEEL")
    if configured:
        wheel = Path(configured).resolve()
        assert wheel.is_file()
        return wheel
    return _build_wheel(tmp_path_factory.mktemp("vps-lite-wheel"), "vps-lite")


def _metadata(wheel: Path):
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))
        return Parser().parsestr(archive.read(metadata_name).decode("utf-8"))


def _dependency_names(wheel: Path) -> set[str]:
    return {
        Requirement(value).name.lower().replace("_", "-").replace(".", "-")
        for value in _metadata(wheel).get_all("Requires-Dist", [])
    }


def test_vps_lite_metadata_has_installable_runtime_dependencies(lite_wheel: Path) -> None:
    dependency_names = _dependency_names(lite_wheel)

    assert LITE_DEPENDENCIES <= dependency_names
    assert dependency_names.isdisjoint(EXCLUDED_DEPENDENCIES)


def test_vps_lite_wheel_contains_only_supported_runtime_surfaces(lite_wheel: Path) -> None:
    with zipfile.ZipFile(lite_wheel) as archive:
        files = set(archive.namelist())

    assert "nanobot/cli/commands.py" in files
    assert "nanobot/agent/tools/web.py" in files
    assert "nanobot/agent/tools/mcp.py" in files
    assert "nanobot/providers/openai_responses/parsing.py" in files
    assert "nanobot/skills/memory/SKILL.md" in files
    assert "nanobot/skills/cron/SKILL.md" in files

    assert not any(name.startswith("nanobot/webui/") for name in files)
    assert not any(name.startswith("nanobot/web/") for name in files)
    assert not any(name.startswith("nanobot/bridge/") for name in files)

    channel_modules = {
        Path(name).name
        for name in files
        if name.startswith("nanobot/channels/") and name.endswith(".py")
    }
    assert channel_modules == SUPPORTED_CHANNEL_MODULES

    provider_modules = {
        Path(name).name
        for name in files
        if name.startswith("nanobot/providers/")
        and name.count("/") == 2
        and name.endswith(".py")
    }
    assert provider_modules == SUPPORTED_PROVIDER_MODULES

    skill_files = {
        name for name in files if name.startswith("nanobot/skills/") and name.endswith("/SKILL.md")
    }
    assert skill_files == {
        "nanobot/skills/cron/SKILL.md",
        "nanobot/skills/memory/SKILL.md",
    }


def test_vps_lite_wheel_exposes_nanobot_cli(lite_wheel: Path) -> None:
    with zipfile.ZipFile(lite_wheel) as archive:
        entry_points_name = next(
            name for name in archive.namelist() if name.endswith(".dist-info/entry_points.txt")
        )
        entry_points = archive.read(entry_points_name).decode("utf-8")

    assert "[console_scripts]" in entry_points
    assert "nanobot = nanobot.cli.commands:app" in entry_points


def test_default_wheel_keeps_full_dependency_metadata(
    tmp_path: Path,
) -> None:
    wheel = _build_wheel(tmp_path, None)
    dependency_names = _dependency_names(wheel)

    assert EXCLUDED_DEPENDENCIES <= dependency_names
