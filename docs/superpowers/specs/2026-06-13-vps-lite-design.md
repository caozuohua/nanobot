# VPS Lite Distribution Design

## Goal

Create a maintainable `vps-lite` distribution profile for nanobot that can replace the
currently running `luck-agent` process on Google Compute Engine instance
`instance-20260413-080555` without running both agents concurrently.

The target is an `e2-micro` instance with 2 vCPUs, 954 MiB RAM, a 2 GiB swap file,
approximately 477 MiB zram, and a 28 GiB root disk. The deployment must keep nanobot's
steady-state resource use predictable while preserving the upstream source layout.

## Scope

### Channels

The Lite distribution supports only:

- Lark international through the Feishu/Lark WebSocket long-connection API
- Telegram
- Discord

The generic nanobot WebSocket channel is not included. Lark uses an outbound connection,
so the deployment does not expose a public HTTP or WebSocket listener.

### Providers

The Lite distribution supports only:

- Vertex AI
- Gemini
- OpenAI-compatible HTTP APIs

Provider discovery and configuration must reject or ignore providers outside this
allowlist when the Lite profile is active. The full distribution retains its current
provider behavior.

### Agent Capabilities

The Lite distribution retains:

- Session memory and normal context construction
- Workspace-restricted file read, write, edit, and listing
- Workspace-restricted shell execution
- Web search and fetch with existing SSRF protection
- Cron scheduling
- Remote MCP clients using HTTP, SSE, or streamable HTTP transports

The Lite runtime excludes:

- Image generation and audio transcription
- Subagent spawning
- Sustained goals and long-running task orchestration
- Self-modification
- Notebook and office-document editing
- Local Node/NPX or other subprocess-hosted MCP servers

Remote MCP endpoints remain subject to `validate_url_target` and the explicit SSRF
whitelist. Public MCP connectivity must not weaken the current network security boundary.

### Skills

The built-in Lite skill set contains only:

- `memory`
- `cron`

Web and MCP capabilities are exposed through their tools and do not require extra built-in
instructional skills. Workspace-installed skills remain supported, subject to the existing
disabled-skills configuration.

### Excluded Surfaces

The Lite artifact does not include:

- The React WebUI source or compiled assets
- `nanobot/web/` static assets
- WebUI backend modules and the generic WebSocket channel
- The OpenAI-compatible inbound API server
- The TypeScript bridge bundle
- Unsupported built-in channels and their dependencies
- Unsupported providers and their dependencies
- Office document libraries and other dependencies used only by excluded capabilities

## Architecture

### Profile-Based Selection

The upstream source tree remains intact. A single explicit Lite profile controls runtime
and packaging allowlists instead of deleting unrelated source modules.

The profile defines:

- Enabled built-in channel module names
- Enabled built-in provider identifiers
- Enabled built-in tool module names
- Included built-in skill names
- Packaging include and exclude rules

Dynamic discovery must consume these allowlists before importing modules. This prevents
unused modules from loading optional dependencies or increasing startup work. External
entry-point plugins remain disabled in Lite mode unless explicitly added to the profile.

The existing default installation remains backward compatible and continues to discover
the full supported feature set.

### Packaging

`pyproject.toml` gains a `vps-lite` optional dependency group containing only the
dependencies needed by the selected channels, providers, tools, and CLI runtime.

A dedicated Lite build path produces an artifact that omits WebUI assets, bridge files,
excluded skills, and excluded runtime packages. The regular wheel and source distribution
retain their current contents and behavior.

The Lite dependency closure must not install channel SDKs for DingTalk, Slack, QQ, Matrix,
WeCom, Weixin, MS Teams, or other excluded channels. It must also omit office document,
image, audio, and unrelated cloud-provider SDKs.

### Configuration

Lite mode is explicit rather than inferred from missing packages. The service sets the
Lite profile through a stable CLI option or environment variable. Configuration loading
continues to use the existing Pydantic schema and camelCase aliases.

Unsupported configured channels, providers, tools, or plugin entry points produce a clear
startup error naming the unsupported component. Invalid configuration must not be silently
corrected.

Telegram and Discord may remain disabled in configuration until credentials are supplied.
Lark is configured for the international endpoint and WebSocket long connection.

## Deployment

### Filesystem and User

- Application checkout: `/opt/nanobot`
- Virtual environment: `/opt/nanobot/.venv`
- Dedicated service account: `nanobot`
- Runtime workspace and persistent state: `/var/lib/nanobot`
- Environment file: a root-owned file readable by the `nanobot` service user and not by
  other users

Secrets are supplied through environment variables referenced by the nanobot configuration.
They are not committed to Git.

### systemd

`nanobot.service` runs the Lite profile from the project virtual environment with:

- `MemoryHigh=550M`
- `MemoryMax=700M`
- `TasksMax=128`
- Automatic restart on failure with bounded retry delay
- Bounded journal retention or rate limiting
- A non-root service user
- A working directory under `/var/lib/nanobot`

The service must not bind a public listening port. Existing swap and zram remain enabled.

### Cutover

Deployment order:

1. Validate the local Lite build and tests.
2. Install and validate nanobot on the VPS without starting it.
3. Stop `luck-agent.service`.
4. Do not disable or delete `luck-agent.service`.
5. Start `nanobot.service`.
6. Validate providers, channels, resource usage, logs, and process ownership.

The old `/opt/luck-agent` checkout and its service definition remain unchanged for rollback.

### Rollback

If nanobot fails validation:

1. Stop `nanobot.service`.
2. Start `luck-agent.service`.
3. Verify `luck-agent.service` is active and inspect its recent logs.

No repository reset, cleanup, service deletion, or credential migration is part of rollback.

## Error Handling

- Missing optional credentials keep the corresponding Telegram or Discord channel disabled.
- Lark configuration or connection failures must be visible in service logs and must not
  cause an uncontrolled restart loop.
- Unsupported Lite components fail startup with a component-specific error.
- MCP network targets continue through SSRF validation, including redirects.
- Memory-limit termination is handled by systemd restart policy and is visible in journal
  output.
- A failed pre-start validation must occur before `luck-agent.service` is stopped.

## Testing

### Unit and Integration Tests

- Verify Lite channel discovery imports only `feishu`, `telegram`, and `discord`.
- Verify Lite provider resolution permits Vertex AI, Gemini, and OpenAI-compatible providers
  and rejects unsupported providers.
- Verify Lite tool discovery exposes only the approved lightweight tools and remote MCP.
- Verify Lite skill loading includes only `memory` and `cron` built-ins while still allowing
  workspace skills.
- Verify external entry-point plugins are not loaded in Lite mode.
- Verify normal full-profile discovery remains unchanged.
- Verify unsupported Lite configuration produces clear startup errors.
- Verify stdio/subprocess MCP configuration is rejected in Lite mode and remote MCP
  configuration retains SSRF checks.

### Clean Environment Test

Install the Lite artifact into a clean Python virtual environment and verify:

- The CLI starts and loads the Lite profile.
- Lark, Telegram, and Discord channel classes import successfully.
- Vertex AI, Gemini, and OpenAI-compatible providers initialize with test configuration.
- Excluded channel SDKs, office libraries, WebUI assets, and bridge files are absent.
- No import of an excluded module is required during startup.

### VPS Acceptance

After cutover:

- `luck-agent.service` is stopped but remains installed and enabled state is unchanged.
- `nanobot.service` runs as the `nanobot` user.
- Lark WebSocket long connection reaches its ready state.
- Telegram and Discord start successfully when configured.
- Each retained provider passes a minimal request or configuration probe.
- The process exposes no public listening socket.
- Peak service memory remains below `700M`.
- Journal output is bounded and contains no repeated import or restart failures.
- A controlled service restart returns to the ready state.

## Success Criteria

The work is complete when the Lite artifact installs in a clean environment, all Lite and
full-profile regression tests pass, the VPS runs nanobot without `luck-agent` concurrently,
Lark connects without an inbound public endpoint, retained providers and tools work, and
systemd keeps the service below the defined memory ceiling with a tested rollback path.
