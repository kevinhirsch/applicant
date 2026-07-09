# Install targets: one-command install, upgrade, uninstall (P3-1)

This page is the operator-facing lifecycle reference for standing up, upgrading,
and tearing down a self-hosted Applicant instance, and the honest record of
which legs of that lifecycle have been verified on a real host versus proven
only hermetically (syntax + control-flow, no real Docker daemon).

The three lifecycle scripts already exist and are exercised by the hermetic
test suite (`tests/unit/test_install_script_lifecycle.py`,
`tests/unit/test_deploy_scripts_syntax.py`, plus the pre-existing
`test_install_script_app_port.py` / `test_update_script_*.py`):

| Script | Purpose |
|---|---|
| `scripts/install.sh` | One-liner install **and** lifecycle manager: `--apply` (install), `--update`/`--upgrade`, `--doctor` (health check), `--uninstall` (stop + remove containers, **keep** data), `--purge` (uninstall + destroy volumes/images/`.env`, confirm-gated). Default (no flag) is a dry run. |
| `scripts/update.sh` | The in-place upgrade path: git-sync → backup → rebuild changed images → migrate → restart → heartbeat, with an automatic rollback (code + images + DB) if migrate, `up -d`, or the post-update heartbeat fails. Default is a dry run; `--rollback` restores the most recent backup. |
| `scripts/proxmox-deploy.sh` | Proxmox VE node script: creates an Ubuntu Server 24.04 LTS VM via cloud-init and runs `install.sh --apply` on first boot. |

## 1. Ubuntu/Debian (bare metal, VM, or LXC-with-nested-VM)

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/install.sh)" -- --apply
```

This bootstraps a checkout if run detached (curl-pipe-bash), installs Docker
Engine + Compose v2 if missing (apt hosts), generates and persists credentials
to `.env` (0600), builds the `applicant-ui` and `api` images, migrates the
schema, brings up the full stack, and waits for a green health check —
entirely without further CLI interaction (`NFR-ZEROCLI-1`); the rest of setup
happens in the browser (the OOBE wizard).

Health, upgrade, and teardown from the same checkout:

```bash
bash scripts/install.sh --doctor       # read-only health self-check
bash scripts/update.sh --apply         # sync -> backup -> rebuild -> migrate -> restart -> heartbeat
bash scripts/install.sh --uninstall    # stop + remove containers; KEEPS volumes + .env
bash scripts/install.sh --purge -y     # uninstall + destroy volumes/images/.env (irreversible)
```

`--purge` refuses to run without `-y`/`--yes` on a non-interactive shell, and
prompts for a literal "yes" on a TTY — it never destroys a running stack's
data implicitly (`tests/unit/test_install_script_lifecycle.py::test_purge_without_confirmation_refuses_and_touches_nothing`).
`--uninstall` never passes `--volumes`/`--rmi` to `docker compose down` — data
survives a plain uninstall by construction, not by convention
(`test_uninstall_stops_containers_but_never_touches_volumes`).

## 2. Proxmox VE

Run on a Proxmox VE **node** shell (not inside a guest):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/proxmox-deploy.sh)"
```

A `whiptail` wizard creates a VM (defaults: 4 cores / 8 GB RAM / 40 GB disk —
the same numbers `docs/requirements-and-model-matrix.md` publishes as the
"recommended" host spec) from the Ubuntu 24.04 cloud image, auto-imports the
node's SSH keys, sets a root password, and cloud-init self-provisions Docker +
the checkout + `install.sh --apply` on first boot. Upgrade/uninstall/purge
happen **inside the VM** exactly as in §1 (`qm guest exec <vmid> -- bash -lc
'cd /opt/applicant && bash scripts/update.sh --apply'`), or destroy the whole
VM at the Proxmox layer (`qm stop <vmid>; qm destroy <vmid> --purge`) when the
VM itself — not just the app — should go away.

## 3. NAS-class box (Synology / QNAP Container Manager / Portainer)

Applicant is a plain Docker Compose stack with no host-specific assumptions
beyond Docker Engine + Compose v2 and enough RAM/disk (§1 of
`docs/requirements-and-model-matrix.md`), so the same commands apply once
Docker is available — which on most NAS platforms means enabling the
vendor's container package first, since `install.sh`'s own auto-install path
is apt-only:

- **Synology DSM** (Container Manager / “Docker” package): install Container
  Manager from Package Center (bundles Docker Engine + `docker compose`),
  enable SSH (Control Panel → Terminal & SNMP), then run the exact §1 command
  from an SSH session. Set `APPLICANT_SKIP_DOCKER_INSTALL=1` so `install.sh`
  never attempts an apt-based Docker install on DSM's non-apt base — Container
  Manager already provides it. Skip the reverse-proxy prompts in Synology's
  own web UI; Applicant runs its own front door on `APP_PORT`.
- **QNAP QTS** (Container Station): install Container Station from the App
  Center (Docker + Compose v2), enable SSH (Control Panel → Telnet/SSH), then
  the same §1 command with `APPLICANT_SKIP_DOCKER_INSTALL=1`.
- Both platforms' storage volumes are typically slower spinning-disk arrays
  behind a RAID layer; the "recommended" 40 GB disk figure assumes it, but the
  first image build (the ~700 MB TeX layer) will take noticeably longer than
  on SSD-backed compute — this is a performance note, not a support gap.

Upgrade/uninstall/purge are the exact §1 commands, run over SSH from the NAS's
shell (or its Container Manager/Station "execute command" console if SSH is
disabled by policy).

## 4. What is verified, and how

| Leg | Status |
|---|---|
| `install.sh` / `update.sh` / `proxmox-deploy.sh` are syntactically valid bash | **Verified in CI** — `tests/unit/test_deploy_scripts_syntax.py` runs `bash -n` over every script under `scripts/` on every PR. |
| Dry-run paths (`install.sh` default, `--uninstall`, `--purge` without confirm, `update.sh` default) touch no real state and issue no destructive Docker calls | **Verified in CI** — `tests/unit/test_install_script_lifecycle.py`, `tests/unit/test_update_script_*.py`, `tests/unit/test_backup_restore_drill_script.py`, all against a fake `docker` shim, no real daemon. |
| `--uninstall` never touches volumes; `--purge` requires explicit confirmation | **Verified in CI** — same file, asserting on the exact `docker compose` invocation (or its absence). |
| `docker compose -f docker/docker-compose.prod.yml config` resolves with dummy secrets | **Verified in CI** (`.github/workflows/ci.yml`). |
| A real `install.sh --apply` builds the images, migrates, and brings the stack green; `--doctor` reports it; `--uninstall` removes containers and keeps the named volumes; `--purge` then removes them | **Dispatch-ready, not yet observed.** The `install-uninstall-drill` job in `.github/workflows/ci-integration.yml` runs exactly this sequence against an isolated, throwaway `docker compose` project (own `COMPOSE_PROJECT_NAME`, own port, torn down unconditionally) — mirroring the existing P1-7 `destroy-drill` job. It is gated behind `workflow_dispatch` and an explicit `confirm_install_drill: yes-i-mean-it` input, and needs the same self-hosted runner Docker socket as `destroy-drill`. |
| Real `docker compose up` on Ubuntu/Debian bare metal, the Proxmox script end-to-end (VM creation through green health check), and one real NAS-class box (Synology/QNAP) | **Blocked — no live host in this environment.** This sandbox has no Docker daemon, no Proxmox node, and no NAS to test against, and the project's self-hosted CI runner (`ubnthost01-applicant`) cannot currently reach its own Docker socket (`docs/known-issues.md` K9: the runner's OS user isn't in the `docker` group) — every job that needs Docker, including the new `install-uninstall-drill` job below, fails identically to `destroy-drill` and the Integration Lane's main job until that host is fixed. This is the same class of gap as P1-2 and P1-7: the mechanism is built and dispatch-ready, but nobody has watched it pass against a real host yet. Closing it needs either the runner-host fix (K9) or a manually-verified run report from an operator with a real Ubuntu/Debian box, a Proxmox node, and a NAS unit. |

### Why `update.sh`'s live upgrade leg isn't in the same CI drill

`update.sh --apply` starts by `git fetch origin main && git reset --hard
origin/main` in the checkout it runs from — the right behavior for a real
deployment (always deploy the tracked branch), but not safe to run inside a
PR's own CI checkout: it would discard the PR's changes and silently test
`main` instead of the code under review. Its backup → migrate → restart →
heartbeat → auto-rollback control flow (the part that is actually
version-sensitive) is already covered hermetically by
`tests/unit/test_update_script_backup_guard.py`,
`test_update_script_migration_rollback.py`, and `test_update_script_rollback.py`
against a fake Docker/Postgres. A genuine live "old code → new code" upgrade
drill needs a second, older tagged ref to reset *to* before running the
update against `HEAD` — worth adding once the runner-host Docker gap (K9) is
closed and there is a stable prior release tag to upgrade from; tracked as a
follow-up, not faked here.
