# VPS Lite Deployment

`vps-lite` is the reduced nanobot runtime for small Linux VPS instances. It keeps
Lark international WebSocket, Discord, Vertex AI, Google AI Studio,
OpenAI-compatible providers, remote HTTP/SSE MCP, filesystem/shell/web tools,
Dream memory, custom self-inspection, `/goal`, cron, and subagent execution. It
does not run the WebUI, desktop surface, Telegram, or other non-target channels.

## Models and commands

The fixed catalog contains five Gemini models from each enabled source.
`NANOBOT_VERTEX_ENABLED=true` is the current and default mode: `/model` shows
both Vertex and AI Studio. False-like values (`0`, `false`, `no`, `off`) leave
AI Studio only. Invalid values fail startup; they are not guessed.

Use `/model`, `/model <number>`, or `/model <preset>` to inspect or switch the
global selection. The restored `/goal` command accepts `/goal <goal>` for a
sustained task. The selection survives restarts. For safety, global LLM turns are serialized.
This keeps model switching and provider cleanup safe, but one slow turn delays
other chats.

Vertex uses ADC with `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`
and `GOOGLE_CLOUD_LOCATION`. AI Studio uses `GEMINI_API_KEY`. Providers have no silent fallback:
a failed call or switch stays failed and visible.
Keep the shared `google-genai` package installed for AI Studio after Vertex is
disabled.

## Retire Vertex after credits

Do this in order:

1. Set `NANOBOT_VERTEX_ENABLED=false` in `/etc/nanobot/nanobot.env`.
2. Run `sudo systemctl restart nanobot.service`.
3. Inspect `journalctl -u nanobot.service -n 100 --no-pager`.
4. Run `/model`; it should show only Studio presets.
5. If the saved model was Vertex, confirm it auto-recovers to
   `studio-35-flash`.
6. Send a real AI Studio call and confirm the response succeeds.
7. Remove credentials only after the AI Studio call succeeds:
   `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, then
   `GOOGLE_CLOUD_LOCATION` from the env file and delete
   `/etc/nanobot/google-service-account.json`.

Restart once more after removing credentials. Do not uninstall `google-genai`.

Rollback: restore `NANOBOT_VERTEX_ENABLED=true`, restore the three Google
environment values and service account file, then restart the service.

## Managed repositories

The `managed_repo` tool can read and write approved repository paths and delegates
pull, commit, push and blog publication to `/usr/local/sbin/nanobot-repo`.

Approved repositories are configured with `NANOBOT_REPO_BLOG`
and `NANOBOT_REPO_NEWSLETTER`. The privileged wrapper checks the repository
name, local path, remote and action. It never force-pushes or resets a worktree.

## Install and migrate

```bash
sudo deploy/install-vps-lite.sh https://github.com/caozuohua/nanobot.git main
sudo deploy/migrate-luck-agent.sh
sudo systemctl daemon-reload
sudo systemctl enable --now nanobot.service
sudo systemctl disable --now luck-agent.service
```

The installer creates or updates `/opt/nanobot` as a Git checkout, installs the
runtime into `/opt/nanobot/.venv`, writes the systemd unit, and validates the
`vps-lite` profile before starting. Secrets live in `/etc/nanobot/nanobot.env`,
`/etc/nanobot/config.json`, or dedicated files owned by `root:nanobot` with mode
`0640`. The service account remains `nologin`. Lark international is configured
as `channels.feishu.domain="lark"`.

## Verification and rollback

Validate both providers with real requests, run `/model`, and push a harmless
repository commit before considering migration complete. Confirm Lark reports a
WebSocket long connection and `ss -lntp` shows no nanobot listener.

Rollback keeps all luck-agent files and credentials:

```bash
sudo systemctl disable --now nanobot.service
sudo systemctl enable --now luck-agent.service
```

## Updating From GitHub On The VPS

The registered updater follows only `origin/main` from `/opt/nanobot`. After
pushing Windows development changes to GitHub, log in as `caozuohua99` and run:

```bash
sudo -n /usr/local/sbin/update-nanobot
```

The updater refuses arguments, a dirty worktree, an unexpected remote or branch,
and divergent history. It fetches and fast-forwards the fixed branch, refreshes
the editable venv install, runs the VPS core tests, refreshes the systemd unit,
then restarts nanobot.

Build or test failures leave the installed runtime and running service
unchanged. Check the source checkout before retrying:

```bash
sudo -u nanobot git -C /opt/nanobot status --short --branch
sudo -u nanobot git -C /opt/nanobot remote -v
journalctl -u nanobot.service -n 100 --no-pager
```
