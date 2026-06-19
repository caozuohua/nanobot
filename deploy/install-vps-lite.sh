#!/usr/bin/env bash
set -euo pipefail

readonly SERVICE_NAME=nanobot
readonly APP_DIR=/opt/nanobot
readonly STATE_DIR=/var/lib/nanobot
readonly WORKSPACE_DIR=${STATE_DIR}/workspace
readonly ETC_DIR=/etc/nanobot
readonly CONFIG_FILE=${ETC_DIR}/config.json
readonly VENV_DIR=${APP_DIR}/.venv
readonly VENV_PYTHON=${VENV_DIR}/bin/python
readonly VENV_CLI=${VENV_DIR}/bin/nanobot
readonly DEFAULT_REPO=https://github.com/caozuohua/nanobot.git
readonly DEFAULT_BRANCH=main

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly UNIT_SRC=${SCRIPT_DIR}/nanobot.service
readonly ENV_SRC=${SCRIPT_DIR}/nanobot.env.example
readonly REPO_WRAPPER_SRC=${SCRIPT_DIR}/nanobot-repo
readonly SUDOERS_SRC=${SCRIPT_DIR}/nanobot-sudoers
readonly UPDATE_SRC=${SCRIPT_DIR}/update-vps-lite.sh
readonly UPDATE_SUDOERS_SRC=${SCRIPT_DIR}/nanobot-update-sudoers
readonly UNIT_DST=/etc/systemd/system/${SERVICE_NAME}.service
readonly ENV_DST=${ETC_DIR}/nanobot.env

usage() {
  printf 'Usage: sudo %s [repo-url] [branch]\n' "${BASH_SOURCE[0]}" >&2
  exit 1
}

die() {
  printf 'install-vps-lite: %s\n' "$*" >&2
  exit 1
}

run_as_nanobot() {
  runuser -u "${SERVICE_NAME}" -- "$@"
}

require_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "run this installer as root or via sudo"
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
  install -d -o "${SERVICE_NAME}" -g "${SERVICE_NAME}" -m 0750 "${STATE_DIR}" "${WORKSPACE_DIR}"
  install -d -o root -g "${SERVICE_NAME}" -m 0750 "${ETC_DIR}"
}

ensure_checkout() {
  local repo_url=$1
  local branch=$2

  if [[ -d "${APP_DIR}/.git" ]]; then
    local dirty
    dirty=$(run_as_nanobot git -C "${APP_DIR}" status --porcelain)
    [[ -z "${dirty}" ]] || die "${APP_DIR} has local changes"
    run_as_nanobot git -C "${APP_DIR}" remote set-url origin "${repo_url}"
    run_as_nanobot git -C "${APP_DIR}" fetch origin "${branch}"
    run_as_nanobot git -C "${APP_DIR}" checkout "${branch}"
    run_as_nanobot git -C "${APP_DIR}" merge --ff-only "origin/${branch}"
    return
  fi

  if find "${APP_DIR}" -mindepth 1 -maxdepth 1 | read -r _; then
    die "${APP_DIR} exists but is not a Git checkout"
  fi

  run_as_nanobot git clone --branch "${branch}" --single-branch "${repo_url}" "${APP_DIR}"
}

ensure_venv() {
  if [[ ! -x "${VENV_PYTHON}" ]]; then
    run_as_nanobot python3 -m venv "${VENV_DIR}"
  fi
  run_as_nanobot "${VENV_PYTHON}" -m pip install --upgrade pip
  run_as_nanobot "${VENV_PYTHON}" -m pip install -e "${APP_DIR}[dev]"
}

install_env_template() {
  if [[ ! -f "${ENV_DST}" ]]; then
    install -D -m 0640 -o root -g "${SERVICE_NAME}" "${ENV_SRC}" "${ENV_DST}"
  else
    chown root:"${SERVICE_NAME}" "${ENV_DST}"
    chmod 0640 "${ENV_DST}"
  fi
}

install_config_template() {
  if [[ -f "${CONFIG_FILE}" ]]; then
    chown root:"${SERVICE_NAME}" "${CONFIG_FILE}"
    chmod 0640 "${CONFIG_FILE}"
    return
  fi

  cat >"${CONFIG_FILE}" <<'JSON'
{
  "agents": {
    "defaults": {
      "workspace": "/var/lib/nanobot/workspace",
      "modelPreset": "vertex-25-flash"
    }
  },
  "providers": {
    "vertexAi": {
      "project": "${GOOGLE_CLOUD_PROJECT}",
      "location": "${GOOGLE_CLOUD_LOCATION}"
    },
    "gemini": {
      "apiKey": "${GEMINI_API_KEY}"
    }
  },
  "channels": {
    "feishu": {
      "enabled": false,
      "domain": "lark",
      "appId": "${LARK_APP_ID}",
      "appSecret": "${LARK_APP_SECRET}"
    },
    "discord": {
      "enabled": false,
      "token": "${DISCORD_TOKEN}"
    }
  }
}
JSON
  chown root:"${SERVICE_NAME}" "${CONFIG_FILE}"
  chmod 0640 "${CONFIG_FILE}"
}

install_unit() {
  install -D -m 0644 "${UNIT_SRC}" "${UNIT_DST}"
}

install_privileged_assets() {
  install -o root -g root -m 0755 "${REPO_WRAPPER_SRC}" /usr/local/sbin/nanobot-repo
  install -o root -g root -m 0755 "${UPDATE_SRC}" /usr/local/sbin/update-nanobot
  visudo -cf "${SUDOERS_SRC}"
  install -o root -g root -m 0440 "${SUDOERS_SRC}" /etc/sudoers.d/nanobot
  visudo -cf "${UPDATE_SUDOERS_SRC}"
  install -o root -g root -m 0440 "${UPDATE_SUDOERS_SRC}" /etc/sudoers.d/nanobot-update
  visudo -cf /etc/sudoers.d/nanobot
  visudo -cf /etc/sudoers.d/nanobot-update
  if [[ -x /usr/bin/fdfind && ! -e /usr/local/bin/fd ]]; then
    ln -s /usr/bin/fdfind /usr/local/bin/fd
  fi
}

validate_runtime() {
  "${VENV_CLI}" gateway --help >/dev/null
  (
    if [[ -f "${ENV_DST}" ]]; then
      set -a
      # shellcheck disable=SC1090
      source "${ENV_DST}"
      set +a
    fi
    run_as_nanobot env NANOBOT_PROFILE=vps-lite "${VENV_PYTHON}" - <<'PY'
from pathlib import Path

from nanobot.config.loader import load_config
from nanobot.runtime_profile import resolve_runtime_profile

config = load_config(Path("/etc/nanobot/config.json"))
config.validate_runtime_profile(resolve_runtime_profile("vps-lite"))
print("Validated vps-lite config and profile.")
PY
  )
}

main() {
  require_root
  [[ $# -le 2 ]] || usage

  local repo_url=${1:-${DEFAULT_REPO}}
  local branch=${2:-${DEFAULT_BRANCH}}

  ensure_group
  ensure_user
  ensure_directories
  ensure_checkout "${repo_url}" "${branch}"
  ensure_venv
  chown -R "${SERVICE_NAME}:${SERVICE_NAME}" "${APP_DIR}" "${STATE_DIR}"
  install_env_template
  install_config_template
  install_unit
  install_privileged_assets
  systemctl daemon-reload
  validate_runtime

  printf 'Installed %s from %s (%s) into %s\n' \
    "${SERVICE_NAME}" "${repo_url}" "${branch}" "${APP_DIR}"
  printf 'Edit %s and %s, then run: sudo systemctl enable --now %s.service\n' \
    "${ENV_DST}" "${CONFIG_FILE}" "${SERVICE_NAME}"
}

main "$@"
