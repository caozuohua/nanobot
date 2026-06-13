#!/usr/bin/env bash
set -euo pipefail

readonly SERVICE_NAME=nanobot
readonly APP_DIR=/opt/nanobot
readonly STATE_DIR=/var/lib/nanobot
readonly ETC_DIR=/etc/nanobot
readonly CONFIG_FILE=${STATE_DIR}/config.json
readonly VENV_DIR=${APP_DIR}/.venv
readonly VENV_PYTHON=${VENV_DIR}/bin/python
readonly VENV_CLI=${VENV_DIR}/bin/nanobot

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly UNIT_SRC=${SCRIPT_DIR}/nanobot.service
readonly ENV_SRC=${SCRIPT_DIR}/nanobot.env.example
readonly REPO_WRAPPER_SRC=${SCRIPT_DIR}/nanobot-repo
readonly PACKAGE_WRAPPER_SRC=${SCRIPT_DIR}/nanobot-package
readonly SUDOERS_SRC=${SCRIPT_DIR}/nanobot-sudoers
readonly UNIT_DST=/etc/systemd/system/${SERVICE_NAME}.service
readonly ENV_DST=${ETC_DIR}/nanobot.env

usage() {
  printf 'Usage: sudo %s /path/to/nanobot-vps-lite.whl\n' "${BASH_SOURCE[0]}" >&2
  exit 1
}

require_root() {
  if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
    printf 'Run this installer as root (or via sudo).\n' >&2
    exit 1
  fi
}

ensure_group() {
  if ! getent group "${SERVICE_NAME}" >/dev/null; then
    groupadd --system "${SERVICE_NAME}"
  fi
}

ensure_user() {
  if ! id -u "${SERVICE_NAME}" >/dev/null 2>&1; then
    useradd \
      --system \
      --gid "${SERVICE_NAME}" \
      --home-dir "${APP_DIR}" \
      --create-home \
      --shell /usr/sbin/nologin \
      "${SERVICE_NAME}"
  fi
}

ensure_directories() {
  install -d -o "${SERVICE_NAME}" -g "${SERVICE_NAME}" -m 0755 "${APP_DIR}"
  install -d -o "${SERVICE_NAME}" -g "${SERVICE_NAME}" -m 0750 "${STATE_DIR}"
  install -d -o root -g "${SERVICE_NAME}" -m 0750 "${ETC_DIR}"
}

ensure_venv() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    python3 -m venv "${VENV_DIR}"
  fi
  "${VENV_PYTHON}" -m pip install --upgrade pip
}

install_wheel() {
  local wheel_path=$1
  "${VENV_PYTHON}" -m pip install --upgrade --force-reinstall "${wheel_path}"
}

install_env_template() {
  if [[ ! -f "${ENV_DST}" ]]; then
    install -D -m 0640 -o root -g "${SERVICE_NAME}" "${ENV_SRC}" "${ENV_DST}"
  else
    chown root:"${SERVICE_NAME}" "${ENV_DST}"
    chmod 0640 "${ENV_DST}"
  fi
}

install_unit() {
  install -D -m 0644 "${UNIT_SRC}" "${UNIT_DST}"
}

install_privileged_assets() {
  install -o root -g root -m 0755 "${REPO_WRAPPER_SRC}" /usr/local/sbin/nanobot-repo
  install -o root -g root -m 0755 "${PACKAGE_WRAPPER_SRC}" /usr/local/sbin/nanobot-package
  visudo -cf "${SUDOERS_SRC}"
  install -o root -g root -m 0440 "${SUDOERS_SRC}" /etc/sudoers.d/nanobot
  visudo -cf /etc/sudoers.d/nanobot
  rm -f /etc/sudoers.d/bot
  if [[ -x /usr/bin/fdfind && ! -e /usr/local/bin/fd ]]; then
    ln -s /usr/bin/fdfind /usr/local/bin/fd
  fi
}

validate_cli() {
  "${VENV_CLI}" gateway --help >/dev/null
}

validate_config_and_profile() {
  if [[ ! -f "${CONFIG_FILE}" ]]; then
    printf 'Skipping runtime validation; missing config file: %s\n' "${CONFIG_FILE}" >&2
    return 0
  fi

  (
    if [[ -f "${ENV_DST}" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "${ENV_DST}"
      set +a
    fi

    "${VENV_PYTHON}" - <<'PY'
from pathlib import Path

from nanobot.config.loader import load_config
from nanobot.runtime_profile import resolve_runtime_profile

config_path = Path("/var/lib/nanobot/config.json")
config = load_config(config_path)
config.validate_runtime_profile(resolve_runtime_profile("vps-lite"))
print("Validated vps-lite config and profile.")
PY
  )
}

main() {
  require_root

  if [[ $# -ne 1 ]]; then
    usage
  fi

  local wheel_path=$1
  if [[ ! -f "${wheel_path}" ]]; then
    printf 'Wheel not found: %s\n' "${wheel_path}" >&2
    exit 1
  fi

  ensure_group
  ensure_user
  ensure_directories
  ensure_venv
  install_wheel "${wheel_path}"
  chown -R "${SERVICE_NAME}:${SERVICE_NAME}" "${APP_DIR}" "${STATE_DIR}"
  install_env_template
  install_unit
  install_privileged_assets
  systemctl daemon-reload
  validate_cli
  validate_config_and_profile

  printf 'Installed %s systemd unit at %s\n' "${SERVICE_NAME}" "${UNIT_DST}"
  printf 'Daemon reloaded; service was not started.\n'
}

main "$@"
