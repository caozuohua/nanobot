#!/usr/bin/env bash
set -euo pipefail

# Usage: sudo ./deploy/setup_systemd.sh
# Run from repository root. This script will create system user, directories,
# copy service and example env to /etc and /var, and enable the systemd service.

SERVICE_NAME=nanobot
APP_DIR=/opt/nanobot
FILES_DIR=/var/lib/nanobot/files
ENV_DIR=/etc/nanobot
ENV_FILE=${ENV_DIR}/nanobot.env
SA_DEST=${ENV_DIR}/sa.json
UNIT_SRC=deploy/nanobot.service
UNIT_DST=/etc/systemd/system/${SERVICE_NAME}.service

# create system user
if ! id -u ${SERVICE_NAME} >/dev/null 2>&1; then
  useradd --system --home ${APP_DIR} --shell /usr/sbin/nologin ${SERVICE_NAME}
  echo "Created system user ${SERVICE_NAME}"
fi

# create directories
mkdir -p ${APP_DIR}
mkdir -p ${FILES_DIR}
mkdir -p ${ENV_DIR}
chown -R ${SERVICE_NAME}:${SERVICE_NAME} ${APP_DIR} ${FILES_DIR}
chmod 750 ${FILES_DIR}

# Copy systemd unit
if [ -f "${UNIT_SRC}" ]; then
  cp "${UNIT_SRC}" "${UNIT_DST}"
  chmod 644 "${UNIT_DST}"
  echo "Installed systemd unit to ${UNIT_DST}"
else
  echo "Unit source ${UNIT_SRC} not found. Are you running from repo root?"
  exit 1
fi

# Install example env if not present
if [ ! -f "${ENV_FILE}" ]; then
  cp deploy/nanobot.env.example "${ENV_FILE}"
  chown root:${SERVICE_NAME} "${ENV_FILE}"
  chmod 640 "${ENV_FILE}"
  echo "Copied example env to ${ENV_FILE} - edit it and add your credentials (service account path, etc.)"
else
  echo "Env file ${ENV_FILE} already exists; not overwriting."
fi

# Reload systemd and enable service
systemctl daemon-reload
systemctl enable --now ${SERVICE_NAME}.service

echo "Setup complete. Check service status: systemctl status ${SERVICE_NAME}.service"
