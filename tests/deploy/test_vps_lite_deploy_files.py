from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"


def read_deploy_file(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def test_vps_lite_service_unit_has_expected_runtime_limits() -> None:
    text = read_deploy_file("nanobot.service")

    assert "[Service]" in text
    assert "User=nanobot" in text
    assert "Group=nanobot" in text
    assert "WorkingDirectory=/var/lib/nanobot" in text
    assert "EnvironmentFile=-/etc/nanobot/nanobot.env" in text
    assert (
        "ExecStart=/opt/nanobot/.venv/bin/nanobot gateway --profile vps-lite "
        "--config /var/lib/nanobot/config.json"
    ) in text
    assert "Restart=on-failure" in text
    assert "RestartSec=5s" in text
    assert "MemoryHigh=550M" in text
    assert "MemoryMax=700M" in text
    assert "TasksMax=128" in text
    assert "LogRateLimitIntervalSec=30s" in text
    assert "LogRateLimitBurst=1000" in text
    assert "NoNewPrivileges=yes" in text
    assert "ProtectSystem=strict" in text
    assert "ProtectHome=read-only" in text
    assert "PrivateTmp=yes" in text
    assert "ProtectKernelTunables=yes" in text
    assert "ProtectKernelModules=yes" in text
    assert "ProtectControlGroups=yes" in text
    assert "RestrictSUIDSGID=yes" in text
    assert "LockPersonality=yes" in text
    assert "ReadWritePaths=/var/lib/nanobot /etc/nanobot /var/www/blog /opt/workspace" in text
    assert "CapabilityBoundingSet=" in text
    assert "AmbientCapabilities=" in text
    assert "--port" not in text
    assert "--host" not in text


def test_vps_lite_env_example_lists_required_variables_without_secrets() -> None:
    text = read_deploy_file("nanobot.env.example")

    assert "service account JSON" in text
    assert "GOOGLE_APPLICATION_CREDENTIALS=" in text
    assert "GOOGLE_CLOUD_PROJECT=" in text
    assert "GOOGLE_CLOUD_LOCATION=" in text
    assert "GEMINI_API_KEY=" in text
    assert "OPENAI_API_KEY=" in text
    assert "LARK_APP_ID=" in text
    assert "LARK_APP_SECRET=" in text
    assert "TELEGRAM_TOKEN=" in text
    assert "DISCORD_TOKEN=" in text
    assert "your-token-here" not in text
    assert "sk-" not in text
    assert "xoxb-" not in text


def test_vps_lite_install_script_is_safe_and_does_not_cut_over() -> None:
    text = read_deploy_file("install-vps-lite.sh")

    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    assert "groupadd" in text
    assert "useradd" in text
    assert "install -d -o" in text
    assert "python3 -m venv" in text
    assert "--force-reinstall" in text
    assert "gateway --help" in text
    assert "validate_runtime_profile" in text
    assert 'resolve_runtime_profile("vps-lite")' in text
    assert "install -D -m 0644" in text
    assert "install -D -m 0640" in text
    assert "systemctl daemon-reload" in text
    assert "systemctl enable --now" not in text
    assert "systemctl start" not in text
    assert "systemctl stop" not in text
    assert "systemctl disable luck-agent" not in text
    assert "luck-agent" not in text
    assert "cutover" not in text.lower()


def test_vps_lite_privileged_assets_are_narrow_and_validatable() -> None:
    repo = read_deploy_file("nanobot-repo")
    packages = read_deploy_file("nanobot-package")
    sudoers = read_deploy_file("nanobot-sudoers")

    assert "reset --hard" not in repo
    assert "push --force" not in repo
    assert "pull --ff-only" in repo
    assert "blog)" in repo
    assert "newsletter)" in repo
    assert "fd-find|ripgrep|git|gh|jq|curl|sqlite3|hugo" in packages
    assert "/usr/local/sbin/nanobot-repo *" in sudoers
    assert "/usr/local/sbin/nanobot-package *" in sudoers
    assert "apt-get *" not in sudoers
    assert "/usr/bin/tee" not in sudoers
