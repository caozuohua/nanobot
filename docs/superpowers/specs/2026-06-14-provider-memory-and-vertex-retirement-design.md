# Provider Memory and Vertex Retirement Design

## Goal

Reduce long-running nanobot memory growth while preserving the current Vertex AI and
Google AI Studio model sources. Make Vertex removable after the Google Cloud credit
expires without another code change.

## Provider Lifecycle

All LLM providers expose an asynchronous close operation. Google providers close their
underlying `google-genai` clients, including temporary global-location clients.

When `/model` replaces the active provider, nanobot installs the validated replacement
first and then closes the old provider. A failed model probe leaves the active provider
untouched. Gateway shutdown also closes the active provider.

Provider cleanup errors are logged and do not revert an otherwise successful model
switch or prevent gateway shutdown.

## Google SDK Loading

Vertex AI and Google AI Studio continue to use the official `google-genai` package.
Neither provider imports the SDK at module import time. The SDK and client are created
only on the first request or explicit model probe.

Vertex model requests that require the global endpoint reuse one lazily created global
client instead of constructing a client per request.

## Background Tasks

Memory consolidation and other internal turns use the active provider snapshot unless
they have an explicitly configured preset. The VPS Lite deployment will not switch to
AI Studio merely because a background task starts.

This avoids retaining separate Vertex and AI Studio clients during routine maintenance.

## Vertex Feature Gate

The VPS Lite model catalog reads `NANOBOT_VERTEX_ENABLED`.

- Missing, empty, `1`, `true`, `yes`, or `on`: Vertex presets remain available.
- `0`, `false`, `no`, or `off`: Vertex presets are omitted.
- Any other value is a configuration error and prevents startup.

The gate applies only to the VPS Lite profile. Full-profile behavior remains unchanged.

When Vertex is disabled:

- `/model` displays only AI Studio presets.
- Selecting a Vertex preset or provider fails explicitly.
- No Vertex client or ADC credential probe is performed.
- AI Studio never silently falls back to Vertex.

## Persisted Model Recovery

If the persisted active preset is a Vertex preset while Vertex is disabled, startup
atomically replaces it with `studio-35-flash` before building the provider.

The gateway records a warning containing the disabled preset and the replacement preset.
If `studio-35-flash` cannot be configured or probed, startup fails instead of falling
back to another source.

No automatic change occurs while Vertex remains enabled.

## Deployment Transition

During the Google Cloud credit period:

```env
NANOBOT_VERTEX_ENABLED=true
```

After the credit expires:

```env
NANOBOT_VERTEX_ENABLED=false
```

The operator restarts nanobot and verifies that `/model` lists only AI Studio entries.
Vertex service-account files and environment variables may then be removed from
`/etc/nanobot/`; `google-genai` stays installed because AI Studio uses the same SDK.

## Verification

Automated tests cover:

- lazy Google SDK loading for both providers;
- closing active, replaced, temporary, and shutdown clients;
- successful switches close only the old provider;
- failed switches preserve the old provider;
- background turns reuse the active provider by default;
- parsing valid and invalid Vertex feature-gate values;
- Vertex catalog omission and explicit rejection while disabled;
- persisted Vertex selection recovery to `studio-35-flash`;
- failure when the replacement AI Studio preset is unavailable;
- canonical `/model` output with Vertex enabled and disabled.

VPS validation records cold-start PSS, post-Lark-connect PSS, and PSS after repeated
Vertex/AI Studio switches. It also verifies Lark WebSocket reconnection, model
persistence, service state, and the absence of Vertex initialization when disabled.

## Expected Result

The change is intended to prevent provider-switch memory accumulation rather than remove
the approximately 100 MiB baseline cost of importing `google-genai`. Stable VPS memory
should remain closer to the post-start baseline instead of growing after background
tasks and model switches.
