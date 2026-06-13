# VPS Lite Deployment

`vps-lite` is the reduced nanobot runtime for small Linux VPS instances. It keeps
Lark WebSocket, Telegram, Discord, Vertex AI, Google AI Studio, OpenAI-compatible
providers, remote HTTP/SSE MCP, filesystem/shell/web tools, PKB and managed
repositories. It does not ship the WebUI or open a public listener.

## Models

The fixed catalog contains five Gemini models for both Vertex AI and AI Studio.
Run `/model` to see the numbered list and `/model 4` or `/model vertex-25-flash`
to switch globally. The selection is stored under the nanobot workspace and
survives service restarts.

Vertex uses ADC with `GOOGLE_APPLICATION_CREDENTIALS`, `GCP_PROJECT` and
`GCP_LOCATION`. AI Studio uses `GEMINI_API_KEY`. A failed switch leaves the
current model unchanged; providers do not silently cross-fallback.

## PKB and repositories

The `pkb` tool uses `PKB_BASE_URL` and `PKB_API_SECRET`. The `managed_repo` tool
can read and write approved repository paths and delegates pull, commit, push
and blog publication to `/usr/local/sbin/nanobot-repo`.

Approved repositories are configured with `NANOBOT_REPO_BLOG`,
`NANOBOT_REPO_PKB` and `NANOBOT_REPO_NEWSLETTER`. The privileged wrapper checks
the repository name, local path, remote and action. It never force-pushes or
resets a worktree.

## Install and migrate

```bash
sudo deploy/install-vps-lite.sh dist/vps-lite/nanobot_ai-*.whl
sudo deploy/migrate-luck-agent.sh
sudo systemctl daemon-reload
sudo systemctl enable --now nanobot.service
sudo systemctl disable --now luck-agent.service
```

Secrets live in `/etc/nanobot/nanobot.env` or dedicated files owned by
`root:nanobot` with mode `0640`. The service account remains `nologin`.
`install-vps-lite.sh` replaces the old broad sudoers file with validated,
root-owned wrappers and creates an `fd` alias for Debian's `fdfind`.

## Verification and rollback

Validate both providers with real requests, run `/model`, query and save a PKB
note, and push a harmless repository commit before considering migration
complete. Confirm Lark reports a WebSocket long connection and `ss -lntp` shows
no nanobot listener.

Rollback keeps all luck-agent files and credentials:

```bash
sudo systemctl disable --now nanobot.service
sudo systemctl enable --now luck-agent.service
```
