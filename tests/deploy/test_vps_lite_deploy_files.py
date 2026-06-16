from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"
DOCS = ROOT / "docs"


def read_deploy_file(name: str) -> str:
    return (DEPLOY / name).read_text(encoding="utf-8")


def read_doc_file(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_vps_lite_service_unit_has_expected_runtime_limits() -> None:
    text = read_deploy_file("nanobot.service")

    assert "[Service]" in text
    assert "User=nanobot" in text
    assert "Group=nanobot" in text
    assert "WorkingDirectory=/var/lib/nanobot" in text
    assert "EnvironmentFile=-/etc/nanobot/nanobot.env" in text
    assert "Environment=NANOBOT_PROFILE=vps-lite" in text
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
    assert "NoNewPrivileges=no" in text
    assert "ProtectSystem=strict" in text
    assert "ProtectHome=read-only" in text
    assert "PrivateTmp=yes" in text
    assert "ProtectKernelTunables=yes" in text
    assert "ProtectKernelModules=yes" in text
    assert "ProtectControlGroups=yes" in text
    assert "RestrictSUIDSGID=yes" in text
    assert "LockPersonality=yes" in text
    assert "ReadWritePaths=/var/lib/nanobot /etc/nanobot /var/www/blog /opt/workspace" in text
    assert "CapabilityBoundingSet=" not in text
    assert "AmbientCapabilities=" in text
    assert "--port" not in text
    assert "--host" not in text


def test_vps_lite_env_example_lists_required_variables_without_secrets() -> None:
    text = read_deploy_file("nanobot.env.example")

    assert "service account JSON" in text
    assert "NANOBOT_VERTEX_ENABLED=true" in text
    assert "default" in text
    assert "Vertex and AI Studio" in text
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


def test_vps_lite_docs_define_vertex_gate_and_retirement_contract() -> None:
    text = read_doc_file("vps-lite.md")

    assert "`NANOBOT_VERTEX_ENABLED=true`" in text
    assert "default" in text
    assert "Vertex and AI Studio" in text
    assert "Invalid values fail" in text
    assert "no silent fallback" in text
    assert "`google-genai`" in text
    assert "global LLM turns are serialized" in text
    assert "`/goal`" in text

    retirement = text[text.index("## Retire Vertex after credits"):]
    steps = [
        "NANOBOT_VERTEX_ENABLED=false",
        "systemctl restart nanobot.service",
        "journalctl -u nanobot.service",
        "`/model`",
        "Studio",
        "`studio-35-flash`",
        "AI Studio call",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "google-service-account.json",
    ]
    positions = [retirement.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "only after the AI Studio call succeeds" in retirement
    assert "NANOBOT_VERTEX_ENABLED=true" in text[text.index("Rollback"):]


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
    assert "/usr/local/sbin/nanobot-repo" in sudoers
    assert "/usr/local/sbin/nanobot-package" in sudoers
    assert "apt-get *" not in sudoers
    assert "/usr/bin/tee" not in sudoers


def test_vps_lite_service_keeps_capabilities_required_by_sudo_wrapper() -> None:
    unit = read_deploy_file("nanobot.service")

    assert "NoNewPrivileges=no" in unit
    assert "CapabilityBoundingSet=" not in unit


def test_vps_updater_is_fixed_safe_and_validates_before_install() -> None:
    text = read_deploy_file("update-vps-lite.sh")

    assert text.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in text
    assert "SOURCE_DIR=/opt/workspace/nanobot/nanobot_repo" in text
    assert "APPROVED_REMOTE=git@github.com:caozuohua/nanobot.git" in text
    assert "APPROVED_BRANCH=main" in text
    assert "flock -n" in text
    assert "status --porcelain" in text
    assert 'fetch origin "${APPROVED_BRANCH}"' in text
    assert "merge-base --is-ancestor" in text
    assert "merge --ff-only" in text
    assert "NANOBOT_BUILD_PROFILE=vps-lite" in text
    assert "tests/build/test_vps_lite_artifact.py" in text
    assert "tests/providers/test_vertex_ai_provider.py" in text
    assert "tests/tools/test_external_resources.py" in text
    assert "tests/deploy/test_vps_lite_deploy_files.py" in text
    assert "pip install --no-deps --force-reinstall" in text
    assert 'systemctl restart "${SERVICE_NAME}"' in text
    assert 'systemctl is-active --quiet "${SERVICE_NAME}"' in text
    assert 'systemctl is-enabled --quiet "${SERVICE_NAME}"' in text
    assert "luck-agent.service" in text
    assert "reset --hard" not in text
    assert "push --force" not in text
    assert "git clean" not in text


def test_vps_updater_registration_grants_only_exact_command() -> None:
    updater = read_deploy_file("update-vps-lite.sh")
    sudoers = read_deploy_file("nanobot-update-sudoers")
    installer = read_deploy_file("install-vps-lite.sh")

    assert '[[ $# -eq 0 ]]' in updater
    assert (
        "caozuohua99 ALL=(root) NOPASSWD: /usr/local/sbin/update-nanobot"
        in sudoers
    )
    assert "caozuohua99 ALL=(ALL)" not in sudoers
    assert "update-nanobot *" not in sudoers
    assert "UPDATE_SRC=${SCRIPT_DIR}/update-vps-lite.sh" in installer
    assert "UPDATE_SUDOERS_SRC=${SCRIPT_DIR}/nanobot-update-sudoers" in installer
    assert "/usr/local/sbin/update-nanobot" in installer
    assert "/etc/sudoers.d/nanobot-update" in installer


def test_vps_updater_runs_tests_from_accessible_checkout_and_fails_closed() -> None:
    text = read_deploy_file("update-vps-lite.sh")

    assert 'cd "${SOURCE_DIR}"' in text
    assert 'build_and_test "${BUILD_ROOT}"' in text
    assert "wheel=$(build_and_test" not in text
    assert 'BUILT_WHEEL="${wheel}"' in text
    assert 'install_runtime "${BUILT_WHEEL}"' in text


def test_vps_updater_cleanup_uses_guarded_global_temp_directory() -> None:
    text = read_deploy_file("update-vps-lite.sh")

    assert 'BUILD_ROOT=""' in text
    assert "cleanup() {" in text
    assert "/var/tmp/nanobot-update.*" in text
    assert 'rm -rf -- "${BUILD_ROOT}"' in text
    assert "trap cleanup EXIT" in text
    assert "trap 'rm -rf" not in text
    assert 'install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0700 \\' in text
    assert '"${build_root}" "${build_root}/tmp" "${wheel_dir}"' in text
    assert 'export TMPDIR="${BUILD_ROOT}/tmp"' in text
