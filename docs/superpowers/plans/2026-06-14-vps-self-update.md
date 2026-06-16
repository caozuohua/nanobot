# Nanobot VPS Self-Update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add and register a safe VPS command that updates nanobot from the fixed `codex/vps-lite` GitHub branch.

**Architecture:** A root-owned updater validates a fixed source checkout, runs Git/build/test work as `nanobot`, and performs only the final wheel installation and service restart as root. A dedicated sudoers file grants `caozuohua99` access only to this argument-free updater.

**Tech Stack:** Bash, Git, Python build/pytest, pip, systemd, sudoers, pytest.

---

### Task 1: Lock The Updater Contract With Tests

**Files:**
- Modify: `tests/deploy/test_vps_lite_deploy_files.py`

- [ ] Add assertions for the fixed checkout, remote, branch, lock, clean-tree refusal, fast-forward-only update, pre-install tests, service verification and forbidden destructive commands.
- [ ] Add assertions that `caozuohua99` receives only `/usr/local/sbin/update-nanobot` and that the updater rejects arguments.
- [ ] Run `pytest tests/deploy/test_vps_lite_deploy_files.py -q` and confirm failure because the assets do not exist.

### Task 2: Implement And Register The Updater

**Files:**
- Create: `deploy/update-vps-lite.sh`
- Create: `deploy/nanobot-update-sudoers`
- Modify: `deploy/install-vps-lite.sh`

- [ ] Implement root/argument checks, a fixed lock, exact checkout validation, origin/branch checks, clean-tree refusal, fetch and fast-forward.
- [ ] Build and test in a temporary directory as `nanobot`.
- [ ] Install the verified wheel, privileged assets and unit; validate sudoers; restart and verify services.
- [ ] Install the updater and dedicated sudoers file from `install-vps-lite.sh`.
- [ ] Run deploy tests, `bash -n`, Ruff and `git diff --check`.

### Task 3: Document The Operator Workflow

**Files:**
- Modify: `docs/vps-lite.md`

- [ ] Document first-time registration, normal `sudo -n update-nanobot` use, safety checks, failure behavior and useful diagnostics.
- [ ] Run focused documentation/deploy tests.

### Task 4: Deploy And Verify On The VPS

**Files:**
- Runtime: `/usr/local/sbin/update-nanobot`
- Runtime: `/etc/sudoers.d/nanobot-update`
- Runtime checkout: `/opt/workspace/nanobot/nanobot_repo`

- [ ] Commit and push the implementation.
- [ ] Verify the checkout resolves to the exact approved path before changing ownership to `nanobot:nanobot`.
- [ ] Install the updater and sudoers file; validate with `visudo -cf`.
- [ ] Run the updater as `caozuohua99`.
- [ ] Confirm the deployed commit, nanobot `active/enabled`, luck-agent `inactive/disabled`, process user `nanobot`, and Lark WebSocket connection.
