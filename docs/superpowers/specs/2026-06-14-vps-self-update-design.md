# Nanobot VPS Self-Update Design

## Goal

Provide a repository-owned VPS update command that pulls the fixed
`main` branch from GitHub, builds and validates the Lite wheel, installs
it, and restarts nanobot. The login user `caozuohua99` can invoke the command
directly without receiving general root access.

## Fixed Paths And Identity

- Source checkout: `/opt/workspace/nanobot/nanobot_repo`
- Git remote: `git@github.com:caozuohua/nanobot.git`
- Git branch: `main`
- Service account: `nanobot`
- Runtime virtual environment: `/opt/nanobot/.venv`
- Service: `nanobot.service`
- Installed command: `/usr/local/sbin/update-nanobot`

The source checkout and all Git/build operations run as `nanobot`. Root is used
only for installing the verified wheel and restarting the fixed service.

## Update Flow

1. Acquire a non-blocking lock so two updates cannot run concurrently.
2. Verify the source path is the expected Git repository.
3. Verify the configured origin URL and current branch exactly match the
   approved remote and `main`.
4. Refuse to continue when the worktree or index is dirty.
5. Fetch the approved branch from origin.
6. Require the local commit to be an ancestor of the fetched commit; refuse
   divergent history.
7. Fast-forward with `git merge --ff-only origin/main`.
8. Build a `vps-lite` wheel in a temporary directory as `nanobot`.
9. Run focused artifact, provider, deployment and external-resource tests before
   changing the runtime.
10. Validate the built wheel contains the VPS Lite profile.
11. Install the wheel into `/opt/nanobot/.venv`.
12. Install repository-managed privileged assets and the systemd unit when they
    changed, validate sudoers with `visudo`, and run `systemctl daemon-reload`.
13. Restart only `nanobot.service`.
14. Verify the service is active/enabled, `luck-agent.service` remains
    inactive/disabled, and report the deployed Git commit.

If fetch, fast-forward, build, tests or validation fail, the installed runtime
and running service remain unchanged. If installation or restart fails, the
script reports the failure and recent journal output; it does not reset Git or
delete user data.

## Registration And Privilege Boundary

The repository script is installed root-owned at
`/usr/local/sbin/update-nanobot`. A dedicated sudoers entry grants only
`caozuohua99` permission to execute that exact command without a password:

```text
caozuohua99 ALL=(root) NOPASSWD: /usr/local/sbin/update-nanobot
```

The updater accepts no branch, repository, service or arbitrary command
arguments. This prevents the entry from becoming a generic root execution path.
The existing nanobot service-account sudo rules remain separate.

User-facing invocation:

```bash
sudo -n /usr/local/sbin/update-nanobot
```

An optional unprivileged convenience launcher named `update-nanobot` may invoke
the same fixed sudo command, but it must not accept pass-through arguments.

## Checkout Ownership

Registration verifies the checkout path before changing ownership. It resolves
the absolute path and requires an exact match with
`/opt/workspace/nanobot/nanobot_repo`, then changes only that tree to
`nanobot:nanobot`. It never recursively changes `/opt/workspace` or another
computed directory.

## Testing

- Static tests verify fixed paths, branch, remote, lock, clean-tree check,
  fast-forward-only behavior, pre-install tests, service verification and lack
  of destructive Git commands.
- Static tests verify the updater accepts no arguments and sudoers grants only
  the exact command to `caozuohua99`.
- Shell syntax is validated with `bash -n`; sudoers is validated with
  `visudo -cf`.
- VPS acceptance runs the updater with the repository already current, confirms
  a successful no-op deployment, verifies process ownership and Lark WebSocket
  startup, and confirms luck-agent remains inactive/disabled.

## Rollback

The updater does not automate destructive rollback. A failed pre-install phase
leaves the current runtime untouched. For an installed regression, an operator
checks out an earlier known commit through a normal reviewed Git change or
installs a previously retained wheel, then restarts nanobot. Configuration,
credentials, workspace data and luck-agent files are never deleted.
