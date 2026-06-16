# Provider Memory and Vertex Retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Google provider resources accumulating across model switches and allow VPS Lite to retire Vertex through one environment variable.

**Architecture:** Add a common asynchronous provider lifecycle, make both Google backends fully lazy, and close replaced providers only after a replacement snapshot is ready. Keep model availability and persisted-preset recovery in the VPS model catalog so the gateway and `/model` share one source of truth.

**Tech Stack:** Python 3.11+, asyncio, google-genai, Pydantic, pytest, systemd, Bash

---

## File Map

- `nanobot/providers/base.py`: common no-op provider close contract.
- `nanobot/providers/vertex_ai_provider.py`: lazy primary/global clients and deterministic cleanup.
- `nanobot/providers/google_ai_provider.py`: remove eager SDK import and reuse Google cleanup.
- `nanobot/agent/loop.py`: close replaced and shutdown providers.
- `nanobot/agent/vps_model_catalog.py`: parse the Vertex gate, filter presets, and recover persisted selection.
- `nanobot/cli/commands.py`: apply recovery before initial provider construction and log it.
- `nanobot/config/loader.py`: atomically persist recovered VPS model selection using the existing config path.
- `nanobot/agent/memory.py`: use the active provider unless a maintenance preset is explicitly configured.
- `deploy/nanobot.env.example`: document the transition switch.
- `docs/vps-lite.md`: document credit-expiry migration and memory verification.
- Provider, agent, command, and deployment tests: prove lifecycle, feature-gate, recovery, and documentation behavior.

### Task 1: Common Provider Cleanup Contract

**Files:**
- Modify: `nanobot/providers/base.py`
- Test: `tests/providers/test_provider_base.py`

- [ ] **Step 1: Write the failing lifecycle test**

```python
import pytest

from nanobot.providers.base import LLMProvider


class MinimalProvider(LLMProvider):
    async def chat(self, messages, tools=None, model=None, **kwargs):
        raise NotImplementedError

    def get_default_model(self) -> str:
        return "test/model"


@pytest.mark.asyncio
async def test_base_provider_close_is_a_safe_noop() -> None:
    provider = MinimalProvider()
    await provider.aclose()
```

- [ ] **Step 2: Verify the test fails**

Run:

```bash
pytest tests/providers/test_provider_base.py::test_base_provider_close_is_a_safe_noop -v
```

Expected: `AttributeError` because `LLMProvider.aclose` does not exist.

- [ ] **Step 3: Add the minimal base implementation**

Add to `LLMProvider`:

```python
async def aclose(self) -> None:
    """Release provider-owned clients and transports."""
```

- [ ] **Step 4: Run the focused test**

Run:

```bash
pytest tests/providers/test_provider_base.py::test_base_provider_close_is_a_safe_noop -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add nanobot/providers/base.py tests/providers/test_provider_base.py
git commit -m "feat: add provider cleanup lifecycle"
```

### Task 2: Lazy and Reusable Google Clients

**Files:**
- Modify: `nanobot/providers/vertex_ai_provider.py`
- Modify: `nanobot/providers/google_ai_provider.py`
- Test: `tests/providers/test_vertex_ai_provider.py`
- Test: `tests/providers/test_google_ai_provider.py`

- [ ] **Step 1: Write failing Vertex client tests**

Add tests that use fake clients with synchronous `close()` methods:

```python
@pytest.mark.asyncio
async def test_vertex_reuses_global_client_and_closes_all_clients(monkeypatch) -> None:
    clients = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.closed = False
            clients.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(vertex_module.VertexAIProvider, "_load_sdk", lambda: SimpleNamespace(Client=FakeClient))
    provider = VertexAIProvider(project="demo", location="us-central1")

    first = await provider._client_for_model("gemini-3.5-flash")
    second = await provider._client_for_model("gemini-3.5-flash")
    primary = await provider._client_for_model("gemini-2.5-flash")

    assert first is second
    assert first is not primary
    await provider.aclose()
    assert all(client.closed for client in clients)
```

- [ ] **Step 2: Write the failing AI Studio import/cleanup test**

```python
@pytest.mark.asyncio
async def test_google_ai_loads_sdk_on_demand_and_closes_client(monkeypatch) -> None:
    assert google_module.genai is None
    client = FakeClient()
    monkeypatch.setattr(
        GoogleAIProvider,
        "_load_sdk",
        staticmethod(lambda: SimpleNamespace(Client=lambda **kwargs: client)),
    )
    provider = GoogleAIProvider(api_key="key", default_model="gemini/gemini-3.5-flash")

    assert provider._client is None
    await provider._ensure_client()
    await provider.aclose()

    assert client.closed is True
```

- [ ] **Step 3: Verify both tests fail**

Run:

```bash
pytest \
  tests/providers/test_vertex_ai_provider.py::test_vertex_reuses_global_client_and_closes_all_clients \
  tests/providers/test_google_ai_provider.py::test_google_ai_loads_sdk_on_demand_and_closes_client \
  -v
```

Expected: global clients differ, cleanup is missing, or AI Studio imported the SDK eagerly.

- [ ] **Step 4: Implement reusable clients and cleanup**

In `VertexAIProvider.__init__`, add:

```python
self._global_client: Any = None
```

Update `_client_for_model` so Gemini 3 global routing is protected by the existing lock and stores one `_global_client`. Add:

```python
async def aclose(self) -> None:
    clients = [self._client, self._global_client]
    self._client = None
    self._global_client = None
    for client in clients:
        if client is None:
            continue
        close = getattr(client, "close", None)
        if close is None:
            close = getattr(client, "aclose", None)
        if close is None:
            continue
        result = close()
        if inspect.isawaitable(result):
            await result
```

Remove the module-level `try: from google import genai` from `google_ai_provider.py`; retain only `genai: Any = None` and its lazy `_load_sdk`.

- [ ] **Step 5: Run Google provider tests**

Run:

```bash
pytest tests/providers/test_vertex_ai_provider.py tests/providers/test_google_ai_provider.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nanobot/providers/vertex_ai_provider.py nanobot/providers/google_ai_provider.py \
  tests/providers/test_vertex_ai_provider.py tests/providers/test_google_ai_provider.py
git commit -m "fix: release and reuse Google provider clients"
```

### Task 3: Close Providers During Switch and Shutdown

**Files:**
- Modify: `nanobot/agent/loop.py`
- Test: `tests/agent/test_model_switching.py`
- Test: `tests/agent/test_loop_lifecycle.py`

- [ ] **Step 1: Write the failing successful-switch test**

```python
@pytest.mark.asyncio
async def test_successful_model_switch_closes_previous_provider(loop) -> None:
    old = ClosingProvider("old")
    new = ClosingProvider("new")
    loop.provider = old
    loop._provider_snapshot_loader = lambda **kwargs: snapshot(new)

    await loop.switch_model_preset("studio-35-flash")

    assert loop.provider is new
    assert old.close_calls == 1
    assert new.close_calls == 0
```

- [ ] **Step 2: Write the failing rejected-switch test**

```python
@pytest.mark.asyncio
async def test_failed_model_switch_keeps_previous_provider_open(loop) -> None:
    old = ClosingProvider("old")
    loop.provider = old

    async def failing_probe(provider):
        raise RuntimeError("probe failed")

    loop._probe_provider = failing_probe
    loop._provider_snapshot_loader = lambda **kwargs: snapshot(ClosingProvider("new"))

    with pytest.raises(RuntimeError, match="probe failed"):
        await loop.switch_model_preset("studio-35-flash")

    assert loop.provider is old
    assert old.close_calls == 0
```

- [ ] **Step 3: Write the failing shutdown test**

```python
@pytest.mark.asyncio
async def test_stop_closes_active_provider(loop) -> None:
    provider = ClosingProvider("active")
    loop.provider = provider

    await loop.stop()

    assert provider.close_calls == 1
```

- [ ] **Step 4: Run the focused tests and confirm failure**

Run:

```bash
pytest tests/agent/test_model_switching.py tests/agent/test_loop_lifecycle.py -q
```

Expected: close counters remain zero.

- [ ] **Step 5: Make provider replacement asynchronous**

Convert the snapshot application/switch path to await replacement probing and then:

```python
old_provider = self.provider
self.provider = snapshot.provider
self.runner.provider = snapshot.provider
try:
    await old_provider.aclose()
except Exception:
    logger.exception("Failed to close replaced provider")
```

On a failed probe, close the candidate provider and leave `old_provider` installed. In `stop()`, close the active provider after agent work has stopped and log cleanup errors without blocking shutdown.

- [ ] **Step 6: Update synchronous callers**

Update startup refresh and command handlers to await the new asynchronous switch/apply methods. Do not schedule cleanup as an untracked background task.

- [ ] **Step 7: Run lifecycle tests**

Run:

```bash
pytest tests/agent/test_model_switching.py tests/agent/test_loop_lifecycle.py tests/command/test_builtin.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add nanobot/agent/loop.py tests/agent/test_model_switching.py \
  tests/agent/test_loop_lifecycle.py tests/command/test_builtin.py
git commit -m "fix: close providers across model lifecycle"
```

### Task 4: Vertex Feature Gate and Catalog Filtering

**Files:**
- Modify: `nanobot/agent/vps_model_catalog.py`
- Test: `tests/agent/test_vps_model_catalog.py`
- Test: `tests/command/test_mobile_help.py`

- [ ] **Step 1: Write gate parsing tests**

```python
@pytest.mark.parametrize("value", [None, "", "1", "true", "YES", "on"])
def test_vertex_enabled_values(monkeypatch, value) -> None:
    if value is None:
        monkeypatch.delenv("NANOBOT_VERTEX_ENABLED", raising=False)
    else:
        monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", value)
    assert vertex_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "NO", "off"])
def test_vertex_disabled_values(monkeypatch, value) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", value)
    assert vertex_enabled() is False


def test_invalid_vertex_gate_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "sometimes")
    with pytest.raises(ValueError, match="NANOBOT_VERTEX_ENABLED"):
        vertex_enabled()
```

- [ ] **Step 2: Write disabled-catalog tests**

```python
def test_disabled_vertex_catalog_contains_only_studio(monkeypatch, config) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    install_vps_model_catalog(config)

    assert config.model_presets
    assert all(name.startswith("studio-") for name in config.model_presets)
    assert "studio-35-flash" in config.model_presets
    assert "vertex-35-flash" not in config.model_presets
```

- [ ] **Step 3: Verify the tests fail**

Run:

```bash
pytest tests/agent/test_vps_model_catalog.py -q
```

Expected: `vertex_enabled` is missing and Vertex presets remain present.

- [ ] **Step 4: Implement strict environment parsing**

Add:

```python
_TRUE_VALUES = {"", "1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def vertex_enabled(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    value = source.get("NANOBOT_VERTEX_ENABLED")
    normalized = "" if value is None else value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise ValueError(
        "NANOBOT_VERTEX_ENABLED must be one of true/false, yes/no, on/off, or 1/0"
    )
```

Make `install_vps_model_catalog` skip the Vertex source when false.

- [ ] **Step 5: Run catalog and model-display tests**

Run:

```bash
pytest tests/agent/test_vps_model_catalog.py tests/command/test_mobile_help.py \
  tests/command/test_builtin.py -q
```

Expected: all tests pass and disabled mode exposes only Studio presets.

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/vps_model_catalog.py tests/agent/test_vps_model_catalog.py \
  tests/command/test_mobile_help.py tests/command/test_builtin.py
git commit -m "feat: add VPS Vertex feature gate"
```

### Task 5: Persisted Vertex Recovery

**Files:**
- Modify: `nanobot/agent/vps_model_catalog.py`
- Modify: `nanobot/cli/commands.py`
- Modify: `nanobot/config/loader.py`
- Test: `tests/agent/test_vps_model_catalog.py`
- Test: `tests/cli/test_vps_lite_gateway.py`
- Test: `tests/config/test_loader.py`

- [ ] **Step 1: Write the recovery decision tests**

```python
def test_disabled_vertex_recovers_persisted_vertex_preset(monkeypatch, config) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    config.agents.defaults.model_preset = "vertex-35-flash"

    recovery = recover_disabled_vertex_preset(config)

    assert recovery == ("vertex-35-flash", "studio-35-flash")
    assert config.agents.defaults.model_preset == "studio-35-flash"


def test_disabled_vertex_does_not_change_studio_preset(monkeypatch, config) -> None:
    monkeypatch.setenv("NANOBOT_VERTEX_ENABLED", "false")
    config.agents.defaults.model_preset = "studio-31-flash-lite"

    assert recover_disabled_vertex_preset(config) is None
```

- [ ] **Step 2: Write the atomic persistence test**

Use a temporary config path and monkeypatch `os.replace`:

```python
def test_save_config_atomically_replaces_destination(tmp_path, monkeypatch) -> None:
    replacements = []
    monkeypatch.setattr(os, "replace", lambda src, dst: replacements.append((src, dst)))

    save_config(config, tmp_path / "config.json")

    assert len(replacements) == 1
    assert replacements[0][1] == tmp_path / "config.json"
```

- [ ] **Step 3: Write the gateway recovery test**

Invoke the VPS gateway with Vertex disabled and a persisted Vertex preset. Stub provider construction, then assert:

```python
assert saved_config.agents.defaults.model_preset == "studio-35-flash"
assert "Vertex preset vertex-35-flash is disabled; switched to studio-35-flash" in caplog.text
```

Add a second test where Studio credentials/probe fail and assert gateway startup fails without constructing Vertex.

- [ ] **Step 4: Verify focused tests fail**

Run:

```bash
pytest tests/agent/test_vps_model_catalog.py tests/config/test_loader.py \
  tests/cli/test_vps_lite_gateway.py -q
```

Expected: recovery and atomic save APIs are absent.

- [ ] **Step 5: Implement recovery and persistence**

Add:

```python
VERTEX_RETIREMENT_FALLBACK = "studio-35-flash"


def recover_disabled_vertex_preset(config: Config) -> tuple[str, str] | None:
    if vertex_enabled():
        return None
    selected = config.agents.defaults.model_preset
    if not selected or not selected.startswith("vertex-"):
        return None
    if VERTEX_RETIREMENT_FALLBACK not in config.model_presets:
        raise ValueError("AI Studio fallback preset studio-35-flash is unavailable")
    config.agents.defaults.model_preset = VERTEX_RETIREMENT_FALLBACK
    return selected, VERTEX_RETIREMENT_FALLBACK
```

Use the repository's existing config serialization, but write to a sibling temporary file, flush and `fsync`, then `os.replace`. Apply recovery before initial provider construction, persist it, and log one warning.

- [ ] **Step 6: Run recovery tests**

Run:

```bash
pytest tests/agent/test_vps_model_catalog.py tests/config/test_loader.py \
  tests/cli/test_vps_lite_gateway.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/vps_model_catalog.py nanobot/cli/commands.py \
  nanobot/config/loader.py tests/agent/test_vps_model_catalog.py \
  tests/config/test_loader.py tests/cli/test_vps_lite_gateway.py
git commit -m "feat: recover disabled Vertex model selection"
```

### Task 6: Background Tasks Reuse the Active Provider

**Files:**
- Modify: `nanobot/agent/memory.py`
- Modify: `nanobot/config/schema.py`
- Test: `tests/agent/test_memory.py`

- [ ] **Step 1: Write the failing default-reuse test**

```python
@pytest.mark.asyncio
async def test_memory_consolidation_reuses_active_provider_by_default(memory, active_provider) -> None:
    memory.provider = active_provider
    memory.provider_snapshot_loader = Mock()

    await memory.consolidate(...)

    memory.provider_snapshot_loader.assert_not_called()
    assert memory.runner.provider is active_provider
```

- [ ] **Step 2: Write the explicit maintenance-preset test**

```python
@pytest.mark.asyncio
async def test_memory_consolidation_uses_explicit_maintenance_preset(memory) -> None:
    memory.config.memory.model_preset = "studio-31-flash-lite"

    await memory.consolidate(...)

    memory.provider_snapshot_loader.assert_called_once_with(
        preset_name="studio-31-flash-lite"
    )
```

- [ ] **Step 3: Verify both tests fail**

Run:

```bash
pytest tests/agent/test_memory.py -q
```

Expected: the loader is called in default mode or no explicit setting exists.

- [ ] **Step 4: Add optional maintenance preset behavior**

Add an optional `model_preset` to the existing memory configuration. In consolidation:

```python
provider = self.provider
if self.config.model_preset:
    snapshot = self.provider_snapshot_loader(preset_name=self.config.model_preset)
    provider = snapshot.provider
```

Close an explicitly created maintenance provider in `finally`; never close the shared active provider.

- [ ] **Step 5: Run memory tests**

Run:

```bash
pytest tests/agent/test_memory.py tests/agent/test_memory_consolidation.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add nanobot/agent/memory.py nanobot/config/schema.py tests/agent/test_memory.py
git commit -m "fix: reuse active provider for memory maintenance"
```

### Task 7: Deployment Documentation and Environment Contract

**Files:**
- Modify: `deploy/nanobot.env.example`
- Modify: `docs/vps-lite.md`
- Modify: `tests/deploy/test_vps_lite_deploy_files.py`

- [ ] **Step 1: Write failing deployment assertions**

```python
def test_vps_env_documents_vertex_retirement_switch() -> None:
    text = read_deploy_file("nanobot.env.example")
    assert "NANOBOT_VERTEX_ENABLED=true" in text
    assert "Set to false after Google Cloud credit expires" in text
```

Add documentation assertions for `studio-35-flash`, restart, `/model`, and removal of Vertex credential variables.

- [ ] **Step 2: Verify the deployment test fails**

Run:

```bash
pytest tests/deploy/test_vps_lite_deploy_files.py -q
```

Expected: the environment switch is absent.

- [ ] **Step 3: Document current and post-credit configurations**

Add to `nanobot.env.example`:

```env
# Set to false after Google Cloud credit expires to expose only AI Studio presets.
NANOBOT_VERTEX_ENABLED=true
```

Add an exact retirement procedure to `docs/vps-lite.md`:

```bash
sudoedit /etc/nanobot/nanobot.env
# NANOBOT_VERTEX_ENABLED=false
sudo systemctl restart nanobot
sudo journalctl -u nanobot -n 100 --no-pager
```

Document checking `/model`, then removing `GOOGLE_APPLICATION_CREDENTIALS`,
`GOOGLE_CLOUD_PROJECT`, and `GOOGLE_CLOUD_LOCATION` only after Studio succeeds.

- [ ] **Step 4: Run deployment tests**

Run:

```bash
pytest tests/deploy/test_vps_lite_deploy_files.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add deploy/nanobot.env.example docs/vps-lite.md \
  tests/deploy/test_vps_lite_deploy_files.py
git commit -m "docs: add Vertex retirement procedure"
```

### Task 8: Full Validation and VPS Deployment

**Files:**
- Modify only if validation reveals a scoped defect.

- [ ] **Step 1: Run formatting and focused suites**

```bash
ruff check nanobot/providers nanobot/agent nanobot/config nanobot/cli
pytest \
  tests/providers/test_provider_base.py \
  tests/providers/test_vertex_ai_provider.py \
  tests/providers/test_google_ai_provider.py \
  tests/agent/test_model_switching.py \
  tests/agent/test_loop_lifecycle.py \
  tests/agent/test_vps_model_catalog.py \
  tests/agent/test_memory.py \
  tests/config/test_loader.py \
  tests/cli/test_vps_lite_gateway.py \
  tests/command/test_builtin.py \
  tests/deploy/test_vps_lite_deploy_files.py \
  -q
```

Expected: zero lint errors and all tests pass.

- [ ] **Step 2: Run the VPS Lite artifact baseline**

```bash
NANOBOT_BUILD_PROFILE=vps-lite python -m build --wheel
NANOBOT_PROFILE=vps-lite NANOBOT_VPS_LITE_WHEEL=dist/nanobot_ai-*.whl \
  pytest tests/build/test_vps_lite_artifact.py -q
```

Expected: the Lite wheel contains both Google providers, excludes full-profile modules,
and installs successfully in isolation.

- [ ] **Step 3: Push the validated branch**

```bash
git status --short --branch
git push origin codex/vps-lite
```

Expected: the remote branch reaches the local commit and the worktree remains clean.

- [ ] **Step 4: Deploy with the registered updater**

From Windows:

```powershell
gcloud compute ssh instance-20260413-080555 --zone=us-central1-c `
  --command="sudo -u caozuohua99 sudo -n /usr/local/sbin/update-nanobot"
```

Expected: updater exits zero, deployment tests pass, and it reports the new commit.

- [ ] **Step 5: Measure the enabled baseline**

Restart, wait for Lark connection, and record:

```bash
pid=$(systemctl show -p MainPID --value nanobot.service)
cat /proc/$pid/smaps_rollup | grep -E '^(Pss|Pss_Anon|Swap):'
systemctl show nanobot.service -p MemoryCurrent -p MemoryPeak -p MemorySwapCurrent
```

Switch Vertex to Studio and back at least three times through `/model`, then repeat the
measurement. Expected: no monotonic client-sized increase and service remains active.

- [ ] **Step 6: Validate disabled mode without deleting credentials**

Temporarily set `NANOBOT_VERTEX_ENABLED=false`, leave the persisted preset on Vertex,
restart, and verify:

```bash
systemctl is-active nanobot.service
journalctl -u nanobot.service -n 100 --no-pager
```

Expected: warning reports the switch to `studio-35-flash`, Lark reconnects, `/model`
contains only Studio presets, and no Vertex endpoint/ADC initialization appears.

- [ ] **Step 7: Restore current dual-source operation**

Set `NANOBOT_VERTEX_ENABLED=true`, restart, and verify Vertex and Studio presets both
appear. Confirm:

```bash
systemctl is-active nanobot.service
systemctl is-enabled nanobot.service
systemctl is-active luck-agent.service || true
systemctl is-enabled luck-agent.service || true
```

Expected: nanobot is active/enabled and luck-agent is inactive/disabled.

- [ ] **Step 8: Record the final results**

Add measured before/after PSS and the deployed commit to the implementation summary.
Do not claim a memory reduction unless the VPS measurements demonstrate it.
