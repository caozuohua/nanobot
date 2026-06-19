#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_DIR=/opt/nanobot
readonly APPROVED_REMOTE=https://github.com/caozuohua/nanobot.git
readonly APPROVED_REMOTE_SSH=git@github.com:caozuohua/nanobot.git
readonly APPROVED_BRANCH=main
readonly SERVICE_USER=nanobot
readonly SERVICE_NAME=nanobot.service
readonly VENV_PYTHON=/opt/nanobot/.venv/bin/python
readonly LOCK_FILE=/run/lock/nanobot-update.lock

die() {
  printf 'update-nanobot: %s\n' "$*" >&2
  exit 1
}

run_as_nanobot() {
  runuser -u "${SERVICE_USER}" -- "$@"
}

require_root_and_no_args() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "must run as root"
  [[ $# -eq 0 ]] || die "this command accepts no arguments"
}

validate_checkout() {
  [[ "$(readlink -f "${SOURCE_DIR}")" == "${SOURCE_DIR}" ]] || die "unexpected source path"
  [[ -d "${SOURCE_DIR}/.git" ]] || die "source checkout is unavailable"

  local remote branch dirty
  remote=$(run_as_nanobot git -C "${SOURCE_DIR}" config --get remote.origin.url)
  if [[ "${remote}" != "${APPROVED_REMOTE}" && "${remote}" != "${APPROVED_REMOTE_SSH}" ]]; then
    die "unexpected origin remote: ${remote}"
  fi

  branch=$(run_as_nanobot git -C "${SOURCE_DIR}" branch --show-current)
  [[ "${branch}" == "${APPROVED_BRANCH}" ]] || die "unexpected branch: ${branch}"

  dirty=$(run_as_nanobot git -C "${SOURCE_DIR}" status --porcelain)
  [[ -z "${dirty}" ]] || die "source checkout has local changes"
}

update_checkout() {
  run_as_nanobot git -C "${SOURCE_DIR}" fetch origin "${APPROVED_BRANCH}"
  run_as_nanobot git -C "${SOURCE_DIR}" merge-base --is-ancestor \
    HEAD "origin/${APPROVED_BRANCH}" \
    || die "local branch diverged from origin/${APPROVED_BRANCH}"
  run_as_nanobot git -C "${SOURCE_DIR}" merge --ff-only "origin/${APPROVED_BRANCH}"
}

refresh_runtime() {
  [[ -x "${VENV_PYTHON}" ]] || run_as_nanobot python3 -m venv /opt/nanobot/.venv
  run_as_nanobot "${VENV_PYTHON}" -m pip install --upgrade pip
  run_as_nanobot "${VENV_PYTHON}" -m pip install -e "${SOURCE_DIR}[dev]"
}

run_core_tests() {
  run_as_nanobot env NANOBOT_PROFILE=vps-lite "${VENV_PYTHON}" -m pytest -q \
    "${SOURCE_DIR}/tests/agent/test_dream.py" \
    "${SOURCE_DIR}/tests/agent/tools/test_long_task.py" \
    "${SOURCE_DIR}/tests/agent/tools/test_self_tool.py" \
    "${SOURCE_DIR}/tests/agent/test_mcp_connection.py" \
    "${SOURCE_DIR}/tests/channels/test_feishu_domain.py" \
    "${SOURCE_DIR}/tests/channels/test_feishu_lazy_import.py" \
    "${SOURCE_DIR}/tests/tools/test_tool_loader.py"
}

install_managed_files() {
  install -o root -g root -m 0755 \
    "${SOURCE_DIR}/deploy/nanobot-repo" /usr/local/sbin/nanobot-repo
  install -o root -g root -m 0755 \
    "${SOURCE_DIR}/deploy/update-vps-lite.sh" /usr/local/sbin/update-nanobot
  install -o root -g root -m 0644 \
    "${SOURCE_DIR}/deploy/nanobot.service" /etc/systemd/system/nanobot.service

  visudo -cf "${SOURCE_DIR}/deploy/nanobot-sudoers"
  install -o root -g root -m 0440 \
    "${SOURCE_DIR}/deploy/nanobot-sudoers" /etc/sudoers.d/nanobot
  visudo -cf "${SOURCE_DIR}/deploy/nanobot-update-sudoers"
  install -o root -g root -m 0440 \
    "${SOURCE_DIR}/deploy/nanobot-update-sudoers" /etc/sudoers.d/nanobot-update
  visudo -cf /etc/sudoers.d/nanobot
  visudo -cf /etc/sudoers.d/nanobot-update
  systemctl daemon-reload
}

restart_and_verify() {
  systemctl restart "${SERVICE_NAME}"
  systemctl is-active --quiet "${SERVICE_NAME}"
}

main() {
  require_root_and_no_args "$@"
  exec 9>"${LOCK_FILE}"
  flock -n 9 || die "another update is already running"

  validate_checkout
  update_checkout
  refresh_runtime
  run_core_tests
  install_managed_files
  restart_and_verify

  local deployed_commit
  deployed_commit=$(run_as_nanobot git -C "${SOURCE_DIR}" rev-parse --short HEAD)
  printf 'nanobot updated successfully to %s\n' "${deployed_commit}"
}

main "$@"
