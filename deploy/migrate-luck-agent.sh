#!/usr/bin/env bash
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "run as root" >&2; exit 1; }
install -d -o root -g nanobot -m 0750 /etc/nanobot
install -d -o nanobot -g nanobot -m 0700 /opt/nanobot/.ssh

if [[ -f /opt/luck-agent/credentials.json ]]; then
  install -o root -g nanobot -m 0640 \
    /opt/luck-agent/credentials.json /etc/nanobot/google-service-account.json
fi
if [[ -f /home/luck-agent/.ssh/id_ed25519 ]]; then
  install -o nanobot -g nanobot -m 0600 \
    /home/luck-agent/.ssh/id_ed25519 /opt/nanobot/.ssh/id_ed25519
  install -o nanobot -g nanobot -m 0644 \
    /home/luck-agent/.ssh/id_ed25519.pub /opt/nanobot/.ssh/id_ed25519.pub
  install -o nanobot -g nanobot -m 0600 \
    /home/luck-agent/.ssh/known_hosts /opt/nanobot/.ssh/known_hosts
fi

python3 - <<'PY'
from pathlib import Path

source = Path("/opt/luck-agent/.env")
target = Path("/etc/nanobot/nanobot.env")
allowed = {
    "GCP_PROJECT", "GCP_LOCATION", "GEMINI_MODEL", "GEMINI_API_KEY",
    "GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_USER",
    "TAVILY_API_KEY", "TAVILY_API_KEY_2",
}
values = {}
for path in (source, target):
    if not path.exists():
        continue
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
for key in allowed:
    if key in values:
        values[key] = values[key]
values["GOOGLE_APPLICATION_CREDENTIALS"] = "/etc/nanobot/google-service-account.json"
values["NANOBOT_REPO_BLOG"] = "/var/www/blog"
values["NANOBOT_REPO_NEWSLETTER"] = "/opt/workspace/ai-daily-newsletter-repo"
target.write_text("\n".join(f"{key}={value}" for key, value in sorted(values.items())) + "\n")
PY
chown root:nanobot /etc/nanobot/nanobot.env
chmod 0640 /etc/nanobot/nanobot.env
