#!/usr/bin/env bash
set -euo pipefail

readonly SOURCE_DIR=/opt/workspace/nanobot/nanobot_repo
readonly APPROVED_REMOTE=git@github.com:caozuohua/nanobot.git
readonly APPROVED_BRANCH=codex/vps-lite
readonly SERVICE_USER=nanobot
readonly SERVICE_NAME=nanobot.service
readonly VENV_PYTHON=/opt/nanobot/.venv/bin/python
readonly LOCK_FILE=/run/lock/nanobot-update.lock

BUILD_ROOT=""
BUILT_WHEEL=""

die() {
  printf 'update-nanobot: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  case "${BUILD_ROOT}" in
    /var/tmp/nanobot-update.*)
      rm -rf -- "${BUILD_ROOT}"
      ;;
  esac
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
  [[ "${remote}" == "${APPROVED_REMOTE}" ]] || die "unexpected origin remote: ${remote}"

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

build_and_test() {
  local build_root=$1
  local build_venv="${build_root}/venv"
  local wheel_dir="${build_root}/wheel"

  install -d -o "${SERVICE_USER}" -g "${SERVICE_USER}" -m 0700 \
    "${build_root}" "${build_root}/tmp" "${wheel_dir}"
  run_as_nanobot python3 -m venv "${build_venv}"
  run_as_nanobot "${build_venv}/bin/python" -m pip install --quiet \
    --upgrade pip build hatchling packaging pytest pytest-asyncio >&2

  run_as_nanobot env NANOBOT_BUILD_PROFILE=vps-lite \
    "${build_venv}/bin/python" -m build --wheel --outdir "${wheel_dir}" \
    "${SOURCE_DIR}" >&2

  local wheel
  wheel=$(find "${wheel_dir}" -maxdepth 1 -type f -name 'nanobot_ai-*.whl' -print -quit)
  [[ -n "${wheel}" ]] || die "vps-lite wheel was not produced"

  run_as_nanobot "${build_venv}/bin/python" -m pip install --quiet \
    --force-reinstall "${wheel}" >&2
  run_as_nanobot env \
    NANOBOT_PROFILE=vps-lite \
    NANOBOT_VPS_LITE_WHEEL="${wheel}" \
    "${build_venv}/bin/python" -m pytest -q \
    "${SOURCE_DIR}/tests/build/test_vps_lite_artifact.py" \
    "${SOURCE_DIR}/tests/providers/test_vertex_ai_provider.py" \
    "${SOURCE_DIR}/tests/tools/test_external_resources.py" \
    "${SOURCE_DIR}/tests/deploy/test_vps_lite_deploy_files.py" >&2

  BUILT_WHEEL="${wheel}"
}

install_runtime() {
  local wheel=$1
  "${VENV_PYTHON}" -m pip install --no-deps --force-reinstall "${wheel}"

  install -o root -g root -m 0755 \
    "${SOURCE_DIR}/deploy/nanobot-repo" /usr/local/sbin/nanobot-repo
  install -o root -g root -m 0755 \
    "${SOURCE_DIR}/deploy/nanobot-package" /usr/local/sbin/nanobot-package
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
  systemctl is-enabled --quiet "${SERVICE_NAME}"
  ! systemctl is-active --quiet luck-agent.service
  ! systemctl is-enabled --quiet luck-agent.service
}

main() {
  require_root_and_no_args "$@"
  exec 9>"${LOCK_FILE}"
  flock -n 9 || die "another update is already running"

  validate_checkout
  update_checkout
  cd "${SOURCE_DIR}"

  local deployed_commit
  BUILD_ROOT=$(mktemp -d /var/tmp/nanobot-update.XXXXXX)
  trap cleanup EXIT
  export TMPDIR="${BUILD_ROOT}/tmp"
  build_and_test "${BUILD_ROOT}"

  install_runtime "${BUILT_WHEEL}"
  restart_and_verify

  deployed_commit=$(run_as_nanobot git -C "${SOURCE_DIR}" rev-parse --short HEAD)
  printf 'nanobot updated successfully to %s\n' "${deployed_commit}"
}

main "$@"
