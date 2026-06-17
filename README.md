# Applicant

> Codename **Applicant** (placeholder — rename cascades). An autonomous, self-hosted
> job-application engine.

A self-hosted engine that runs 24/7 and conducts ongoing, per-campaign job-search
campaigns. It agentically discovers postings matching evolving, human-editable,
self-learning criteria; delivers a daily digest the user approves/declines with
feedback; and for approved roles pre-fills as much of every application as is
technically possible — stopping only at irreducible human steps (CAPTCHA, email/SMS
verification, final submit). When a role warrants it, the engine adapts the user's
resume, writes a cover letter, and drafts screening-question answers — all reviewed
and approved by the user before any submission. Everything is logged; the system
learns real conversion (approval + submission) per campaign.

## Engineering mandate

Built with **hexagonal (ports-and-adapters) architecture, BDD, and TDD**. The pure
core domain has no I/O; all external concerns are ports with swappable adapters.
Every component cites the requirement IDs it satisfies.

## Documentation

The full build specification lives under [`docs/`](docs/):

| Doc | Purpose |
|---|---|
| [`docs/spec/master-spec.md`](docs/spec/master-spec.md) | The single source of truth (v4.4, verbatim) |
| [`docs/requirements.md`](docs/requirements.md) | Catalog of every FR-*/NFR-* requirement ID |
| [`docs/architecture.md`](docs/architecture.md) | Hexagonal map: core, driving ports, driven ports, domain rules |
| [`docs/state-machine.md`](docs/state-machine.md) | Application lifecycle state machine |
| [`docs/data-model.md`](docs/data-model.md) | Postgres/JSONB schema (campaign-scoped, multi-ready) |
| [`docs/work-packages.md`](docs/work-packages.md) | Phases 0–4, requirement-tagged, with exit criteria |
| [`docs/traceability.md`](docs/traceability.md) | Requirement → Work Package → BDD Feature → contract test |
| [`docs/delivery-status.md`](docs/delivery-status.md) | Per-phase delivery summary + exit-criteria status |
| [`docs/extending.md`](docs/extending.md) | How to add a new ATS adapter or discovery source |
| [`docs/dormant-surfaces.md`](docs/dormant-surfaces.md) | Dormant Surface Wiring Backlog |
| [`docs/onboarding-intake.md`](docs/onboarding-intake.md) | Workday-ready onboarding intake schema |
| [`docs/voice-and-truthfulness.md`](docs/voice-and-truthfulness.md) | Non-AI-looking + truthfulness guardrails |
| [`docs/open-items.md`](docs/open-items.md) | Open items and defaults |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |

---

# Deployment

Applicant ships the whole stack — FastAPI + the vendored frontend, PostgreSQL,
SearXNG, the on-demand **takeover desktop** (a full Ubuntu desktop, see below),
font-install — as a Docker Compose deployment (FR-INSTALL-1/3). No `make` needed.
Everything after install is configured **in-browser** (zero-CLI, NFR-ZEROCLI-1).

The host is a **lean, headless Ubuntu Server 24.04 LTS** VM (the Proxmox deployer
builds it from the Ubuntu noble cloud image). The desktop the user takes over lives
in a separate container, not on the host.

## Prerequisites

- A Linux host (VM, Proxmox LXC, or bare metal) or any Docker host; ~2 vCPU / 4 GB
  RAM is plenty to start.
- **Docker + Docker Compose v2** — the only hard requirement for the container path.
- For local development instead of containers: **Python 3.11+** and
  **[uv](https://docs.astral.sh/uv/)** (`uv sync`).
- An LLM endpoint — either a cloud OpenAI-compatible API key (e.g. OpenRouter) **or**
  a local/network [Ollama](https://ollama.com) (fully local, no cloud key). You set
  this in the browser at first run; no key needs to live in a file.

The dev Compose stack (`docker/docker-compose.yml`) brings up three services — `api`
(FastAPI + UI), `postgres` (16), and `searxng` (metasearch) — with a persistent
`pgdata` volume. `docker/docker-compose.prod.yml` is the hardened production variant
(env-based secrets, `restart: always`, an `api` healthcheck, a `pgbackups` volume,
internal-only SearXNG).

## Install and first run

### Proxmox VE node (recommended) — paste-and-go

On your **Proxmox VE node shell**, paste this one line. Per the spec (FR-INSTALL-1) it
provisions a **Proxmox VM** (not an LXC): a whiptail wizard creates a **lean, headless
Ubuntu Server 24.04 LTS** cloud VM, presets the root password, auto-imports the node's
SSH keys, and uses cloud-init to self-provision on first boot — install Docker, deploy
Applicant, run the migrations (the full takeover desktop is a container, not on the host):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/proxmox-deploy.sh)"
```

Pick **default** (2 cores / 4 GB / 16 GB disk, DHCP, auto-picked storage) or **advanced**
(choose VMID, resources, disk storage, bridge). It prints the VM's root password and,
once the first-boot build finishes (a few minutes), `http://<vm-ip>:8000` — open that and
complete the in-browser OOBE wizard (see the [User guide](#user-guide)). Watch first-boot
progress with `qm guest exec <vmid> -- tail -n40 /var/log/cloud-init-output.log`; update
later with `qm guest exec <vmid> -- bash -lc 'cd /opt/applicant && bash scripts/update.sh --apply'`.

A VM (not a container) is used deliberately — it matches the spec, gives Docker and the
browser sandbox clean isolation, and supports the residential-egress posture (FR-STEALTH-4).

### Any Docker host

If you already have a Docker host (or a fresh VM), install directly:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/install.sh)" -- --apply
```

From a checkout (dry-run by default — prints the steps; add `--apply` to run them):

```bash
bash scripts/install.sh            # dry-run preview
bash scripts/install.sh --apply    # provision: compose up + alembic upgrade head
```

Then open **`http://localhost:8000`** and complete the setup wizard. Editable defaults
are environment-driven (set them in a `.env` file next to the compose file before
`--apply`, or export them — e.g. `POSTGRES_PASSWORD`, `APP_URL`).

**Local (non-container) run** for development:

```bash
uv sync                                   # install deps (add --extra browser for patchright)
uv run alembic upgrade head               # create the schema (needs DATABASE_URL → Postgres)
uv run uvicorn applicant.app.main:app --host 0.0.0.0 --port 8000
```

With the default `ORCHESTRATOR_BACKEND=shim` the app boots with **no Postgres**
(file-backed checkpoints + in-memory storage fallback), which is how the test suite
stays hermetic; point `DATABASE_URL` at a real Postgres for persistence.

## Updating

`scripts/update.sh` backs up the DB, pulls, runs migrations, restarts, and supports
**rollback** of the most recent backup on failure (FR-INSTALL-2). Safe-by-default
(dry-run unless `--apply`):

```bash
bash scripts/update.sh --apply              # backup → pull → migrate → restart
bash scripts/update.sh --rollback --apply   # restore the most recent DB backup
```

The same flow is invokable from the **in-UI Update button** on the debug surface
(`/debug`) with no CLI (FR-OOBE-4); real dispatch is guarded behind
`APPLICANT_UPDATE_ENABLED=1`, otherwise it reports a safe dry-run.

## Configuration (environment variables)

All settings are env-driven (`src/applicant/app/config.py`, loaded from the
environment or a `.env` file). Sensible defaults mean a fresh install needs almost
none of these — the LLM and notification channels are configured in-browser.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://applicant:applicant@localhost:5432/applicant` | Postgres DSN (app schema). |
| `ORCHESTRATOR_BACKEND` | `shim` | Durable backbone: `shim` (file-backed, no PG) or `dbos` (needs Postgres). |
| `CHECKPOINT_DIR` | `.applicant_checkpoints` | Where the shim stores durable checkpoints. |
| `APP_STATIC_DIR` | `frontend/static` | Vendored UI assets served by FastAPI. |
| `LLM_PROVIDER` / `LLM_MODEL` | _empty_ | Seed the OOBE LLM gate from env (otherwise set in-browser). |
| `LLM_BASE_URL` / `LLM_API_KEY` | _empty_ | OpenAI-compatible endpoint + key (or Ollama base URL; key blank). |
| `LLM_RATE_LIMIT` / `LLM_RATE_PERIOD` | `0` / `60.0` | Per-provider LLM rate cap (0 disables) over N seconds. |
| `SANDBOX_CONCURRENCY` | `3` | Max concurrent application sandboxes (durable-queue cap). |
| `CREDENTIAL_KEYFILE` | `secrets/master.key` | libsodium master key file for the credential vault (mode `0600`). |
| `FONTS_DIR` | `.applicant_fonts` | Confined dir for runtime font installs (never system-wide). |
| `DISCOVERY_LIVE` | `false` | Turn on real job-board scraping (off = offline fakes). |
| `SEARXNG_URL` | _empty_ | SearXNG metasearch endpoint for discovery. |
| `DISCOVERY_PROXIES` | _empty_ | Comma-separated proxy hooks for hostile boards (empty = direct). |
| `NOTIFICATIONS_LIVE` | `false` | Turn on real Discord/email send (off = captured, no network). |
| `DISCORD_WEBHOOK_URL` / `APPRISE_URLS` | _empty_ | Notification targets (Apprise URL syntax). |
| `BROWSER_CHANNEL` | `chrome` | Driving browser channel: `chrome` (real Google Chrome, default) \| `chromium` (fallback). Invalid → boot error. |
| `EGRESS_MODE` | `direct` | Browser egress: `direct` (host residential connection) \| `residential-proxy` (requires `EGRESS_PROXY_URL` + `EGRESS_RESIDENTIAL=true`). Datacenter exit refused. |
| `EGRESS_PROXY_URL` / `EGRESS_RESIDENTIAL` | _empty_ / `false` | Residential proxy URL + operator attestation it is residential (FR-STEALTH-4). |
| `EGRESS_TIMEZONE` / `EGRESS_LOCALE` | `America/Phoenix` / `en-US` | tz/locale pinned to the egress geolocation so the fingerprint ↔ exit IP stay consistent (FR-STEALTH-1). |
| `TAKEOVER_DESKTOP` | `cinnamon` | Takeover desktop DE: `cinnamon` (default) \| `xfce` \| `gnome`. Invalid → boot error. Every DE ships Google Chrome. |
| `TAKEOVER_DESKTOP_IMAGE` | _empty_ | Advanced: pin an exact desktop image (overrides the DE→image table). |
| `REMOTE_VIEW_BACKEND` | `webtop` | Live remote-view backend: `webtop` (full desktop, default) \| `neko` (browser-only). |
| `NEKO_ROOMS_URL` / `NEKO_ROOMS_TOKEN` | _empty_ | Real Neko remote-session server (used when `REMOTE_VIEW_BACKEND=neko`). |
| `SANDBOX_BACKEND` | `local` | Sandbox backend: `local` (default, the webtop/Neko path) \| `proxmox-windows` (native real Windows VM, see below). Invalid → boot error. |
| `STEALTH_PERSONA` | _empty_ | `linux` (coherent honest spoof) \| `native` (real browser identity, no override). Blank derives it: `native` for `proxmox-windows`, `linux` for `local`. |
| `PROXMOX_API_URL` / `PROXMOX_NODE` / `PROXMOX_TOKEN_ID` | _empty_ | Proxmox node API URL, node name, API token id (non-secret). The token **secret** + RDP password are collected in the setup wizard and **vaulted** — never env/logs. |
| `PROXMOX_TEMPLATE_VMID` | `0` | The licensed Windows VM template (or persistent) VMID. |
| `PROXMOX_CLONE_MODE` | `snapshot-revert` | `snapshot-revert` (reuse one VM, roll back per session) \| `linked-clone` (clone per session, destroyed on teardown). |
| `PROXMOX_CDP_HOST` / `PROXMOX_CDP_PORT` | _empty_ / `9222` | Chrome remote-debugging (CDP) host (blank → guest IP) + port the engine connects to. |
| `PROXMOX_TAKEOVER_METHOD` / `PROXMOX_TAKEOVER_URL_TEMPLATE` | `rdp` / _empty_ | One-click takeover: `rdp` (rdp:// URI) \| `web-console` (Guacamole/web RDP URL template with `{host}`/`{token}`/`{vmid}` slots). |
| `APPLICANT_UPDATE_ENABLED` | _unset_ | Set `1` to let the in-UI Update button actually dispatch. |
| `LOG_FORMAT` / `LOG_LEVEL` | `pretty` / `INFO` | structlog output (`json` in prod) and verbosity. |

## Enabling the real integrations

The default lane runs everything behind hermetic fakes. To go fully live in a real
deployment, enable each integration (all are opt-in, none required to boot):

- **Persistence + durable execution (DBOS):** set `ORCHESTRATOR_BACKEND=dbos` and a
  reachable `DATABASE_URL`. DBOS owns its own system tables; Alembic manages the app
  schema. See [Durable orchestration backend](#durable-orchestration-backend).
- **Real browser pre-fill (Google Chrome via patchright):** `uv sync --extra browser`
  then install **real Google Chrome** (`google-chrome-stable`) — patchright drives
  the Chrome *channel* (`BROWSER_CHANNEL=chrome`, the default; `chromium` is a
  less-coherent fallback). The driver runs **headful** (never headless — that is a
  detection tell) on a per-tenant Chrome profile. Real Google Chrome (not Chromium)
  is the foundation of the stance below: it yields the genuine Chrome TLS/JA3 +
  HTTP/2 fingerprint and the correct Sec-CH-UA client hints automatically. The
  adapter swaps from the in-memory fake page model to that real Chrome.

  **Coherent real-Linux/Chrome identity (FR-STEALTH-1) — and WHY.** The engine
  presents a single, internally-consistent **real Linux + Google Chrome** identity
  rather than spoofing a Windows persona: UA `Mozilla/5.0 (X11; Linux x86_64) ...
  Chrome/<major>` (the `<major>` is derived from the *installed* Chrome so UA ↔
  Sec-CH-UA ↔ engine never disagree), `navigator.platform = "Linux x86_64"`,
  `navigator.vendor = "Google Inc."`, `Sec-CH-UA-Platform: "Linux"`, languages
  `en-US,en`, and a **real Linux GPU** WebGL renderer (Mesa/llvmpipe) — never a
  Windows Direct3D renderer, and **stable, not randomized** (randomization is itself
  a tell, and no canvas-noise is injected). An incoherent spoof (e.g. a Windows UA
  with a Linux GPU) scores *worse* with bot detectors than an honest, coherent
  fingerprint on the residential IP, so coherence is the whole point.

  **Timezone/locale pinned to egress (FR-STEALTH-1 ↔ FR-STEALTH-4).** `EGRESS_TIMEZONE`
  / `EGRESS_LOCALE` are threaded into the browser context (`timezone_id` / `locale`)
  so tz/locale ↔ exit IP stay consistent; derive them from the residential egress IP's
  region in a real deployment (defaults are a sensible coherent pair).
- **Live discovery:** `DISCOVERY_LIVE=true` (+ `SEARXNG_URL`, optional
  `DISCOVERY_PROXIES`) to scrape real boards via JobSpy + SearXNG.
- **Notifications:** `NOTIFICATIONS_LIVE=true` + `DISCORD_WEBHOOK_URL` / `APPRISE_URLS`
  (email/SMTP/etc. via Apprise URL syntax). Also configurable in the wizard.
- **Live remote takeover (full Ubuntu desktop, default):** the takeover environment
  is a containerized, web-streamed **full Ubuntu desktop** the user drives during an
  irreducible human step (CAPTCHA / account-creation / verification / final submit;
  FR-SANDBOX-2/3, FR-PREFILL-5). The desktop's DE is configurable via
  `TAKEOVER_DESKTOP` (default **Cinnamon**, plus **Xfce** and full **GNOME**) and is a
  pure image swap:

  | `TAKEOVER_DESKTOP` | Image | Notes |
  | --- | --- | --- |
  | `cinnamon` (default) | `applicant/webtop-chrome:cinnamon` | LinuxServer Cinnamon webtop **+ Google Chrome + realistic fonts** (`docker/webtop-chrome/Dockerfile`, `BASE=...ubuntu-cinnamon`). |
  | `xfce` | `applicant/webtop-chrome:xfce` | LinuxServer Xfce webtop **+ Google Chrome + realistic fonts** (`docker/webtop-chrome/Dockerfile`, `BASE=...ubuntu-xfce`). |
  | `gnome` | `applicant/webtop-gnome:latest` | **Custom** image (`docker/webtop-gnome/Dockerfile`): Ubuntu + GNOME on Xorg + KasmVNC **+ Google Chrome + realistic fonts**. **Heavier** — full GNOME has no prebuilt webtop. |

  **Google Chrome is the browser in every desktop** (FR-STEALTH-1): the stock
  LinuxServer webtops do not ship Chrome, so `cinnamon`/`xfce` resolve to local
  *derived* images (`docker/webtop-chrome/Dockerfile`, `FROM` the LinuxServer webtop)
  that add `google-chrome-stable` + a realistic desktop font set (Liberation/DejaVu/
  Noto/MS-corefonts) so font enumeration looks like a real machine, not a bare
  container. This way the human takes over the **same real Chrome** the engine drives.

  **X11, not Wayland**, for all three: the web-streaming layer and the
  automation/handoff path are X11-native (Chrome runs headful on that X server);
  Wayland would complicate both. **GNOME trade-off:** standard webtop images don't
  ship full GNOME (it assumes Wayland/systemd), so `gnome` builds a heavier custom
  image — prefer Cinnamon or Xfce unless GNOME is specifically required. **Switch the
  driving channel** with `BROWSER_CHANNEL` (`chrome` default ↔ `chromium`).

  **Session continuity / handoff:** the one-click live-session URL carries the
  short-lived access token AND the application URL the agent was on (`app=`), so the
  desktop's browser opens the SAME application the engine was filling. The real
  shared-profile/cookie continuity + container start/stop are integration-gated; the
  image selection, URL/token minting, and lifecycle bookkeeping are unit-tested.

  Switch backend with `REMOTE_VIEW_BACKEND` (`webtop` default ↔ `neko`). Run the
  desktop container with the `takeover` compose profile:
  `TAKEOVER_DESKTOP_IMAGE=lscr.io/linuxserver/webtop:ubuntu-xfce docker compose -f docker/docker-compose.prod.yml --profile takeover up -d takeover-desktop`.
- **Live remote takeover (Neko, browser-only alt):** set `REMOTE_VIEW_BACKEND=neko`
  with `NEKO_ROOMS_URL` (+ `NEKO_ROOMS_TOKEN`) for the one-click browser-only session;
  the remote-view sub-port also supports noVNC.
- **Native Proxmox Windows VM backend (`SANDBOX_BACKEND=proxmox-windows`):** a
  selectable sandbox backend where the browser the engine drives — and that you take
  over — is **real Google Chrome inside a real, licensed Windows VM** on your Proxmox
  node. Because it is real Windows, the fingerprint (JA3/TLS, Direct3D WebGL,
  Segoe UI/Calibri, OS signals) is **genuinely Windows with ZERO spoofing** — the
  strongest FR-STEALTH-1 (so the persona is `native`: no fingerprint override). It is
  a clean swap behind the existing `SandboxPort`/`RemoteViewPort` — the engine,
  services and router are unchanged; the `local` backend stays the default.

  **Definition of ready (you provide; everything else is automated):** a licensed
  Windows VM (Server or Desktop) on the Proxmox node with **Google Chrome installed**,
  **qemu-guest-agent** running, and **RDP enabled**. Make it the template/VMID you
  point the wizard at, and (for `snapshot-revert` mode) take a clean snapshot named
  `applicant-clean`.

  **Setup is zero-CLI (FR-OOBE):** the setup wizard has a *“Windows sandbox
  connection”* step (`POST /api/setup/sandbox-connection`) that collects the Proxmox
  API URL/node/token id + **token secret**, the template/persistent VMID, clone mode,
  Chrome CDP host/port, RDP username + **password**, and the takeover method/URL. The
  **secrets (token secret + RDP password) are sealed in the credential vault** and
  never logged or returned; the non-secrets persist to app-config. The
  `proxmox-windows` backend is **gated** on this step (until it is complete the app
  boots on the local sandbox and automated work stays blocked).

  **How it works:** on provision the backend clones the template (`linked-clone`) or
  rolls a persistent VM back to the clean snapshot (`snapshot-revert`), starts it,
  reads the guest IP via the agent, launches Chrome with
  `--remote-debugging-port`/`--remote-debugging-address` (so its CDP endpoint is
  reachable from the host), and returns a session carrying the **CDP ws endpoint**
  (the prefill browser **connects over CDP** to that remote Chrome instead of
  launching a local one) plus a **tokenized one-click takeover URL** (an `rdp://` URI
  or a web-console/Guacamole URL) so you take over the SAME real Chrome. Teardown
  reverts/stops/destroys the VM and invalidates the takeover token. The real Proxmox
  control plane + CDP + RDP paths are **integration-gated**
  (`tests/integration/test_proxmox_windows_real.py`, skipped without `PROXMOX_API_URL`);
  the orchestration, backend/persona selection, CDP wiring, takeover URL/token,
  secret vaulting, and the lifecycle are unit-tested with a `FakeProxmoxClient`.
- **Resume fidelity rendering:** install a TeX engine (`lualatex`/`xelatex` +
  fontspec/moderncv) for LaTeX-primary PDFs, or LibreOffice (`soffice`) for the
  docx-XML fallback. Without either, rendering uses the deterministic stub seam.

## Data, backups, and security

- **Persistent data** lives in Postgres (the `pgdata`/`pgbackups` Compose volumes):
  campaigns, attribute clouds, applications, screenshots, resume variants, learning
  state, durable workflow state. Back it up with `scripts/update.sh` (which dumps
  before every migration) or your own `pg_dump` schedule.
- **Secrets:** application credentials are sealed at rest with libsodium
  (XSalsa20-Poly1305); the master key is a `0600` key-file (`CREDENTIAL_KEYFILE`) —
  keep it off the repo and back it up separately. Secrets are never logged (structlog
  redacts recursively). API keys are stored via the encrypted credential path, not in
  plaintext config.
- **Remote access / HTTPS:** put the `api` service behind a reverse proxy (Caddy,
  nginx, Traefik) for TLS, or expose it over a private network (e.g. Tailscale). The
  Update button and live-session URLs assume an authenticated, trusted network.

---

# User guide

Applicant is operated entirely through its web UI (zero-CLI). The surfaces:

| URL | Surface | What you do there |
|---|---|---|
| `/wizard` | Setup wizard (OOBE) | First-run configuration: LLM → channels → fonts → onboarding |
| `/` `/digest` | Pending-actions home + daily digest | Approve/decline roles, work the 24/7 action queue |
| `/review` | Redline review | Approve/revise resumes, cover letters, screening answers |
| `/chat` | Chatbot | Fill gaps in your profile/criteria conversationally |
| `/debug` | Debug & admin | Tool toggles, logs, screenshots, history, workflow state, Update button |

### 1. First-run setup wizard (`/wizard`)

A resumable, multi-step wizard (FR-OOBE, FR-UI-5). Steps gate in order and the engine
will not start automated work until they're complete:

1. **LLM settings (gate).** Choose a provider/model — a cloud OpenAI-compatible API
   (paste an OpenRouter key) or a local Ollama URL (fully local). Optionally arrange a
   capability-ranked **tier ladder** (cheap model first, escalate on hard tasks).
   Nothing downstream unlocks until this is set.
2. **Notification channels.** Connect Discord and/or email (Apprise). This is a gating
   step — the engine won't run unattended until you can be reached.
3. **Fonts.** Upload your résumé; the engine detects required fonts and prompts for any
   missing ones, installing them into the render environment.
4. **Onboarding intake.** A Workday-ready interview (identity, work authorization,
   location/remote prefs, target roles, salary floor, full work history, education,
   references, key attributes, EEO — defaulting to "decline to self-identify", never
   AI-guessed). Your base résumé is parsed to bootstrap the **attribute cloud**;
   conflicts with your answers ask for confirmation. Finally you **accept or reject**
   the LaTeX conversion preview of your résumé (accept → LaTeX-primary engine; reject →
   docx fallback).

### 2. Create a campaign and criteria

Each job search is a **campaign** (`/api/campaigns`) with its own criteria, attribute
cloud, learning, and digest. Criteria (`/api/criteria`) are human-readable and editable
at any time; the engine also proposes learned adjustments, always shown transparently
and overridable. Tune run behavior (`/api/agent-runs`): throughput (default ~15/day,
hard cap 30), and run mode (24/7 continuous, fixed duration, or until N viable roles).

### 3. The daily digest (approve / decline)

When matches accumulate, you get a per-campaign **digest** (email + webpage + a Discord
"ready" ping). Each row shows the role, a brief summary, the posting link, work mode, a
viability score, and **why it was suggested**. You **approve** (queue it for pre-fill)
or **decline with feedback** (mandatory free-text) — and that feedback feeds learning
and tunes the next run's criteria. Empty days get a short "here's what I searched and
why" note. Notifications follow an escalation ladder: in-app if you're present →
Discord (held ~30s) → email after a timeout; acting on one channel cancels the others.

### 4. Pending-actions home base (`/` and `/digest`)

The 24/7 home base lists **everything awaiting you** — digest approvals, material
reviews, missing-attribute soft errors, agent questions, and final-submit approvals —
each one actionable.

### 5. Application pre-fill and live takeover

For an approved role the engine spins up an isolated, stealthy browser **sandbox** and
pre-fills every field on every page from your attribute cloud (escalating ambiguous
mappings to the LLM, never guessing sensitive/EEO fields). It **stops at irreducible
human steps** — CAPTCHA, email/SMS verification, account-creating submit, final
submit — and notifies you with a **one-click live session (VNC)** link (`/api/remote`)
where you can finish the step yourself or authorize the engine to continue. If a board
gets hostile, **cautious mode** pauses and hands off rather than risking your account.
Credentials you enter (or that the engine captures during account creation) are banked
in the encrypted **vault** (`/api/credentials`) for reuse.

### 6. Material review and approval (`/review`)

When a role warrants tailored material, the engine generates a résumé variant and/or
cover letter and/or screening answers — truthfully (it reframes real experience, never
fabricates) and without AI tells (em-dashes stripped, your voice matched). Each artifact
is shown as a **redline** with additions and subtractions highlighted. Run the
interactive loop: accept, reject, free-text instruction ("make it more concise"),
targeted add, or targeted subtract — each turn re-generates within budget and
re-renders. **Nothing is submitted until you approve it.** Approved material bundles
into the final-submit step.

### 7. Tools, debug, and the chatbot

- **Tool toggles** (`/debug`): switch any capability on/off (discovery, scoring,
  pre-fill, account-creation, web-research, résumé/cover/answer generation, chat,
  notifications) — and it actually disables at runtime.
- **Debug surface** (`/debug`): recent (redacted) logs, per-application history, captured
  per-page screenshots, durable-workflow state, and the **variant library** (lineage +
  fit scores). The **Update button** lives here too.
- **Chatbot** (`/chat`): converse to fill gaps in your profile or criteria; proposed
  changes go through the confirmation gate (integral/sensitive changes need your
  explicit OK; minor ones auto-apply).

### 8. How it learns

Every input — digest approvals/declines and their feedback, redline edits, pre-fill
soft-error resolutions, source yield, and actual **conversions** (approval **plus**
submission) — feeds per-campaign learning. The engine learns the signature of roles
that convert and biases discovery, scoring, and variant selection toward them —
transparently, and always overridable by you.

---

## Stack

Python 3.11+ · FastAPI + vendored Odysseus UI · PostgreSQL + JSONB · DBOS Transact
(durable execution) · LangGraph (in-step reasoning) · patchright (browser automation)
· JobSpy + SearXNG (discovery) · LaTeX/moderncv primary resume engine with docx-XML
fallback · Apprise/Discord notifications · structlog. Toolchain: **uv**.

## Durable orchestration backend

The durable backbone is pluggable via the `ORCHESTRATOR_BACKEND` env var:

- `shim` (**default**) — a file-backed checkpoint store (`CHECKPOINT_DIR`,
  default `.applicant_checkpoints`). Requires no Postgres, so the app boots and the
  full test suite runs hermetically while still proving true mid-step resumption.
- `dbos` — the real DBOS Transact adapter (durable workflows, idempotent
  checkpointed steps, `send`/`recv` approval gates, cron scheduling, durable
  queues for concurrency caps / rate limits). Requires a live Postgres at
  `DATABASE_URL`. The DBOS-backed resumption tests
  (`tests/integration/test_dbos_orchestrator.py`) are skipped unless both
  `ORCHESTRATOR_BACKEND=dbos` and a reachable `DATABASE_URL` are set.

## Status

**All five phases (0–4) are implemented and merged to `main`.** The engine is end-to-end
functional in its hermetic default lane. What works today:

- **Phase 0** — zero-CLI OOBE + onboarding: setup wizard (LLM-gate first, then channels,
  fonts, Workday-ready intake), provider-agnostic LLM with a tier ladder, resumable
  onboarding interview, resume parsing to bootstrap the attribute cloud, durable
  orchestration backbone, structlog observability, vendored Odysseus UI shell.
- **Phase 1** — discovery → digest → approve/decline → learning: JobSpy/SearXNG discovery,
  per-campaign self-learning criteria + attribute cloud, daily digest with rationale and
  approve/decline-with-feedback, pending-actions portal, Discord/web/email notifications
  with the 30s-hold escalation ladder, source-yield learning.
- **Phase 2** — maximal Workday pre-fill in a stealth browser sandbox: per-application
  ephemeral sandbox, deterministic field mapping with LLM escalation, stop-at-irreducible-
  human-steps handoff, one-click live remote session (Neko), cautious mode, encrypted
  credential vault (libsodium), per-page screenshot logging, submission detection.
- **Phase 3** — truthful material generation: LaTeX-primary / docx-XML fallback resume
  tailoring, cover letters and screening answers, truthfulness + non-AI-voice guardrails,
  variant library with lineage and fit-scoring, interactive redline review with a durable
  revision-session loop.
- **Phase 4** — conversion learning + tool registry + debug surface + chatbot + one-liner
  install/update: deepened real-conversion learning, per-tool toggle registry, debug surface
  (logs/screenshots/history/workflow state), confirmation-gated chatbot, and the
  install/update scripts (with in-UI Update button).

**Tests:** the hermetic default test lane is green — `uv run pytest -q` reports **539
passed** (10 integration-gated skips). Real external integrations — live job boards, a real
browser (patchright/playwright), TeX (lualatex/xelatex), Neko remote sessions,
Postgres/DBOS durable execution, and Discord/SMTP delivery — sit behind integration-gated
boundaries that require a live deployment; the default lane proves the same logic with
fakes. See [`docs/delivery-status.md`](docs/delivery-status.md) for the per-phase delivery
summary and [`docs/traceability.md`](docs/traceability.md) for requirement-level coverage.
