# Applicant

> Codename **Applicant** (placeholder — rename cascades). A self-hosted,
> single-operator job-application system: a white-labeled workspace UI in front of
> an autonomous job-application engine.

Applicant runs 24/7 and conducts ongoing, per-campaign job-search campaigns. It
agentically discovers postings matching evolving, human-editable, self-learning
criteria; delivers a daily digest the operator approves/declines with feedback; and
for approved roles pre-fills as much of every application as is technically possible
— stopping only at irreducible human steps (CAPTCHA, email/SMS verification, final
submit). When a role warrants it, the engine adapts the operator's resume, writes a
cover letter, and drafts screening-question answers — all reviewed and approved
before any submission. Everything is logged; the system learns real conversion
(approval + submission) per campaign.

## Two apps and a bridge

Applicant ships as **two cooperating apps wired by an internal bridge**:

- **Front door — the white-labeled workspace UI** (`workspace/`). A no-build
  workspace web app, white-labeled as Applicant, is the **only** surface the
  operator opens. It runs as the public `applicant-ui` service on `${APP_PORT}`
  (→ container `7000`). It surfaces the engine through thin, auth-protected,
  owner-scoped proxy routes (`workspace/routes/applicant_*_routes.py`), browser glue
  (`workspace/static/js/applicant*.js`), and a progressive feature-activation layer
  (`workspace/src/applicant_features.py`) that greys/locks/activates each section as
  the engine is configured — so no dead UI ever 500s when clicked.

- **Engine — the job-application engine** (`src/applicant/`). A hexagonal
  (ports-and-adapters) FastAPI service that owns all the logic: discovery, scoring,
  digest, learning, pre-fill, material generation, the durable workflow backbone.
  It runs as the internal-only `api` service on `8000` (never published to the
  host) and is reached in-network at `http://api:8000`.

The bridge runs in both directions:

- **Workspace → engine** via `workspace/src/applicant_engine.py`, an httpx client
  pointed at the engine by the `ENGINE_URL` env var (default `http://api:8000`).
  All engine failures surface as a typed `EngineError`, so a proxy never leaks a
  broken page.
- **Engine → workspace** via the token-gated internal channel
  (`workspace/routes/applicant_internal_routes.py`). Callbacks must present the
  shared `APPLICANT_INTERNAL_TOKEN`; if the token is unset the channel is disabled
  (every callback rejected) and the engine degrades gracefully. This is how
  engine-side adjacencies (calendar interview detection, deep-research runs,
  cookbook-served local models) reach back into the workspace.

The engine still carries a small in-network `frontend/static/` shell for migration
purposes, but it is **not** the front door — the workspace app is. There is no
engine-served setup page; setup happens in the workspace OOBE wizard.

## Posture: single-operator, private LAN/VPN

Applicant is a **single-operator** product. Signup is admin-only — there is one
owner. It is designed to run on a **private LAN or VPN over plain HTTP** (e.g. a
home network or a Tailscale tailnet), not exposed to the public internet. The
internal channel, the live-session/takeover URLs, and the in-UI Update button all
assume a trusted private network. Put a reverse proxy (Caddy/nginx/Traefik) in
front for TLS if you want it — [reverse-proxy-https.md](reverse-proxy-https.md)
has copy-paste snippets for all three (Secure cookies follow
`X-Forwarded-Proto` automatically) — but the baseline posture is private + HTTP.
The app door itself is hardened either way: strong passwords enforced
server-side wherever one is set, per-client login rate-limiting, and optional
TOTP two-factor auth in Settings → Security. For the strongest privacy posture,
`LLM_LOCAL_ONLY=true` verifiably keeps every model call on your own box/network
— [private-mode.md](private-mode.md) is the honest contract (what it enforces
and what still leaves the box by design).

## What ships (the feature set)

Every surface below is reachable in the workspace front door (proxy → JS → nav/section),
backed by an engine router under `src/applicant/app/routers/`:

- **OOBE setup / onboarding wizard** — auto-launching, gated, resumable. Slimmed to
  the two steps that actually gate automated work: **Connect a model** (reuses the
  existing Local/Remote endpoint manager) → **Your profile** (the Workday-ready intake
  + base résumé, ending in the résumé LaTeX-conversion accept/reject gate). Notification
  channels, résumé fonts, and the automation sandbox are **not** wizard steps — they live
  in **Settings**, which reuses the exact same renderers (`mountSettingsStep`). Automated
  work is blocked until the wizard completes; everything else is post-setup configuration.
- **Pending-actions portal** — the operator's home base: one aggregated feed of
  everything awaiting input across all campaigns (digest approvals, material
  reviews, missing-detail soft errors, agent questions, account-creation handoffs,
  final-submit approvals), each actionable.
- **Documents / resume redline review** — the résumé + cover-letter library and the
  interactive add/subtract/free-text redline revision loop. Nothing submits until
  approved.
- **Profile** — the per-campaign criteria editor, attribute cloud (the structured
  facts pre-filled into applications), and learning (accept/reject AI-suggested
  attributes and résumé-conversion learning).
- **Chat / assistant + job actions** — a conversational assistant that fills gaps in
  the profile/criteria (confirmation-gated) plus campaign picker, pending list, and
  remote résumé actions.
- **Email / digest + feedback survey** — the daily digest per campaign (approve /
  decline-with-feedback) injected into the email surface, plus the guided feedback
  survey.
- **Activity / debug** — read-only observability (per-application history,
  screenshots, redacted logs, durable-workflow state, the variant library) plus
  operator controls: run mode / throughput, discovery-source toggles, mark-submitted,
  and the in-UI **Update** button.
- **Live remote view / takeover** — the one-click live session view with takeover,
  submit-self, and authorize-engine-finish controls. The engine never self-authorizes
  the final submit.
- **Credential vault** — per-tenant credentials banked and sealed at rest by the
  engine (libsodium); manual entry plus auto-capture during a live account-creation.

Engine-side adjacencies (**Calendar**, **Deep-Research**, **Cookbook**) reach the
engine via the internal callback channel rather than as separate Applicant surfaces.
**Compare** is engine-backed — put two or more applications (or postings) side-by-side
to see exactly where they differ, optionally scoped to one campaign. It lights up in
the nav once a model is connected.

## Documentation

The full build specification and developer docs live under [`docs/`]():

| Doc | Purpose |
|---|---|
| [`docs/spec/master-spec.md`](spec/master-spec.md) | The binding requirements (v4.4), with a reconciliation note |
| [`docs/requirements.md`](requirements.md) | Catalog of every FR-*/NFR-* requirement ID |
| [`docs/architecture.md`](architecture.md) | Two-app architecture: engine hexagon + workspace front door + bridge |
| [`docs/frontend.md`](frontend.md) | The workspace front door: proxies, JS glue, feature activation |
| [`docs/dormant-surfaces.md`](dormant-surfaces.md) | Surface-by-surface front-door reachability + the one disabled surface |
| [`docs/state-machine.md`](state-machine.md) | Application lifecycle state machine (engine) |
| [`docs/data-model.md`](data-model.md) | Engine Postgres/JSONB schema (campaign-scoped, multi-ready) |
| [`docs/work-packages.md`](work-packages.md) | Phases 0–5, requirement-tagged, with exit criteria |
| [`docs/traceability.md`](traceability.md) | Requirement → delivered (engine) AND reachable (front door) |
| [`docs/delivery-status.md`](delivery-status.md) | Per-phase delivery summary + reachability re-audit |
| [`docs/extending.md`](extending.md) | Working principles + how to add an ATS adapter or discovery source |
| [`docs/onboarding-intake.md`](onboarding-intake.md) | Workday-ready onboarding intake schema |
| [`docs/voice-and-truthfulness.md`](voice-and-truthfulness.md) | Non-AI-looking + truthfulness guardrails |
| [`docs/open-items.md`](open-items.md) | Open items and defaults |
| [`docs/backup-restore.md`](backup-restore.md) | Operator backup/restore + the owner "Download my data" export |
| [`docs/support.md`](support.md) | Getting support: the redacted diagnostic-bundle command, issue templates, community chat |
| [`docs/faq.md`](faq.md) | Top-20 pre-written support FAQ (no jobs found, empty digest, invalid key, CAPTCHA, weak model, review-before-submit, EEO/work-auth, private mode, backup/restore, cost/pace, notifications, …); mirrored in-app at Settings → Help & FAQ |
| [`docs/requirements-and-model-matrix.md`](requirements-and-model-matrix.md) | Host hardware/software requirements, per-service footprint, supported LLM providers, and which model class is good enough for which product function |
| [`docs/platform-matrix.md`](platform-matrix.md) | Supported CPU architecture (amd64-only, with the binary reasons), Docker-on-WSL2 setup + gotchas, other host-OS notes |
| [`docs/install-targets.md`](install-targets.md) | One-command install/upgrade/uninstall lifecycle for Ubuntu/Debian, Proxmox, and NAS-class boxes, and what is verified vs. dispatch-ready-only |
| [`docs/adr/`](adr/) | Architecture Decision Records |
| [`docs/known-issues.md`](known-issues.md) | Living bug log — open defects, product decisions pending, deploy-gated findings |
| [`docs/security-review.md`](security-review.md) | Launch-gate security pass: secrets at rest, dependency audit, endpoint sweep |
| [`docs/reverse-proxy-https.md`](reverse-proxy-https.md) | Putting a reverse proxy (Caddy/Traefik/nginx) in front for TLS |
| [`docs/private-mode.md`](private-mode.md) | The verified local-only privacy contract (`LLM_LOCAL_ONLY`) |

A user-facing **docs site** (Quickstart, FAQ, Troubleshooting, Security & Privacy) is
generated straight from the docs above plus the shipped landing page and compose
files — see [`scripts/build_docs_site.py`](../scripts/build_docs_site.py). Regenerate
it any time with:

```bash
python scripts/build_docs_site.py         # writes docs/site/*.html (gitignored — regenerate, don't hand-edit)
python -m http.server --directory docs/site 8080   # serve it locally to preview
```

Because every page is pulled live from the repo's own docs/scripts/compose files
(never hand-duplicated prose), the site can't silently drift from what's actually
shipped — see `workspace/tests/test_applicant_docs_site.py` for the pinning tests.

---

# Deployment

Applicant ships the whole two-app stack as a Docker Compose deployment
(FR-INSTALL-1/3). The production stack (`docker/docker-compose.prod.yml`) brings up:

| Service | Role | Network |
|---|---|---|
| `applicant-ui` | Front-door workspace UI (built from `workspace/`) | **Public** on `${APP_PORT}` → container `7000` |
| `api` | Job-application engine | **Internal only** (`http://api:8000`) |
| `postgres` | Engine persistence + durable workflow state (16) | Internal |
| `searxng` | Metasearch for discovery (shared) | Internal |
| `chromadb` | Vector store for the workspace UI | Internal |
| `ntfy` | Push notifications for the workspace UI | Internal |
| `takeover-desktop` | On-demand web-streamed Ubuntu desktop for live takeover (`--profile takeover`) | Internal |

An optional `ollama` service is provided (commented) for a fully-local LLM. Secrets
come from the environment, restart policies are pinned, the engine carries a
healthcheck, and DB backups land in a named volume for `update.sh` rollback. Both
containers read the same `ENGINE_URL` / `APPLICANT_INTERNAL_TOKEN` from the repo-root
`.env` that `install.sh` generates, so the bridge is wired automatically.

The base `docker/docker-compose.yml` is a leaner **dev/engine-only** stack
(`api` + `postgres` + `searxng`, engine published on `8000`) for working on the
engine in isolation. Everything after install is configured **in-browser** (zero-CLI,
NFR-ZEROCLI-1).

## Prerequisites

- A Linux host (VM, Proxmox LXC, or bare metal) or any Docker host; 4 vCPU / 8 GB
  RAM / 40 GB disk (the Proxmox deployer's own default, sized for the full
  stack build) is the grounded recommendation — see
  [`docs/requirements-and-model-matrix.md`](requirements-and-model-matrix.md)
  for the minimum floor and per-service footprint.
- **Docker + Docker Compose v2** — the only hard requirement.
- An LLM endpoint — either a cloud OpenAI-compatible API key (e.g. OpenRouter) **or**
  a local/network [Ollama](https://ollama.com) (fully local, no cloud key). You set
  this in the browser at first run; no key needs to live in a file.
- For local engine development without containers: **Python 3.11+** and
  **[uv](https://docs.astral.sh/uv/)** (`uv sync`).

## Install and first run

### Proxmox VE node (recommended) — paste-and-go

On your **Proxmox VE node shell**, paste this one line. Per the spec (FR-INSTALL-1)
it provisions a **Proxmox VM** (not an LXC): a whiptail wizard creates a lean,
headless **Ubuntu Server 24.04 LTS** cloud VM, presets the root password, auto-imports
the node's SSH keys, and uses cloud-init to self-provision on first boot — install
Docker, deploy the stack, run migrations:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/proxmox-deploy.sh)"
```

Pick **default** (4 cores / 8 GB / 40 GB disk, DHCP, auto-picked storage) or
**advanced** (choose VMID, resources, disk storage, bridge). It prints the VM's root
password and, once the first-boot build finishes (a few minutes),
`http://<vm-ip>:${APP_PORT}` — open that **front-door UI** and complete the in-browser
OOBE wizard (see the [Operator guide](#operator-guide)). The deployer waits on the
front door's `/api/health` before declaring the stack green. Watch first-boot progress
with `qm guest exec <vmid> -- tail -n40 /var/log/cloud-init-output.log`.

A VM (not a container) is deliberate — it matches the spec, gives Docker and the
browser sandbox clean isolation, and supports the residential-egress posture
(FR-STEALTH-4).

### Any Docker host

If you already have a Docker host (or a fresh VM), install directly. The installer
builds both images from local source, so it needs the repo on disk — the one-liner
**self-bootstraps**: it clones the repo into `./applicant` (override with
`APPLICANT_DIR=...`) and re-execs itself from inside that checkout. Requires `git`,
`docker`, and `docker compose` v2:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/install.sh)" -- --apply
```

Or clone first and run from the checkout (dry-run by default — prints the steps;
add `--apply` to run them):

```bash
git clone https://github.com/kevinhirsch/applicant.git
cd applicant
bash scripts/install.sh            # dry-run preview
bash scripts/install.sh --apply    # provision: compose up (prod stack) + alembic upgrade head
```

`install.sh` opens the **front door** on `${APP_PORT}` (default `8000`, mapped to the
UI container's `7000`) — the engine `api` stays internal. It generates and persists
the DB credentials, `APP_URL`, `ENGINE_URL`, and the shared `APPLICANT_INTERNAL_TOKEN`
into the repo-root `.env` so both containers agree. Then open
**`http://<host>:${APP_PORT}`** and complete the setup wizard.

**Local engine run** for development (the engine alone, no workspace UI):

```bash
uv sync                                   # install deps (add --extra browser for patchright)
uv run alembic upgrade head               # create the schema (needs DATABASE_URL → Postgres)
uv run uvicorn applicant.app.main:app --host 0.0.0.0 --port 8000
```

With the default `ORCHESTRATOR_BACKEND=shim` the engine boots with **no Postgres**
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

The same flow is invokable from the **in-UI Update button** on the Activity/debug
surface with no CLI (FR-OOBE-4); real dispatch is guarded behind
`APPLICANT_UPDATE_ENABLED=1`, otherwise it reports a safe dry-run.

## Backup, restore, and data export

`scripts/backup.sh` / `scripts/restore.sh` produce/restore ONE full tarball
(Postgres + the front-door UI's own data + the deploy config), sharing code
with `update.sh`'s own pre-migration backup step; `scripts/backup-restore-drill.sh`
automates a live backup → destroy volumes → restore verification. Owners get
their own copy via Settings → Account → "Download my data" (applications,
documents, profile, activity). See [`docs/backup-restore.md`](backup-restore.md).

## Configuration (environment variables)

Sensible defaults mean a fresh install needs almost none of these — the LLM and
notification channels are configured in-browser. The most load-bearing ones:

| Variable | Default | Purpose |
|---|---|---|
| `APP_PORT` | `8000` | Public host port for the front-door UI (→ container `7000`). |
| `ENGINE_URL` | `http://api:8000` | Where the workspace UI reaches the engine (the bridge). |
| `APPLICANT_INTERNAL_TOKEN` | _unset_ | Shared secret for engine→workspace callbacks; unset disables the channel. |
| `WORKSPACE_URL` | `http://applicant-ui:7000` | Where the engine reaches the workspace for callbacks. |
| `UI_DATABASE_URL` | `sqlite:///./data/app.db` | The workspace UI's own store (separate from the engine's Postgres). |
| `DATABASE_URL` | `postgresql+psycopg://applicant:applicant@postgres:5432/applicant` | Engine Postgres DSN. |
| `ORCHESTRATOR_BACKEND` | `shim` | Engine durable backbone: `shim` (file-backed, no PG) or `dbos` (needs Postgres). |
| `CHECKPOINT_DIR` | `/data/checkpoints` | Where the shim stores durable checkpoints (named volume in prod). |
| `SCHEDULER_ENABLED` | `true` (prod) | 24/7 scheduler: run loop, daily digest, notification ladder. |
| `LLM_PROVIDER` / `LLM_MODEL` | _empty_ | Seed the OOBE LLM gate from env (otherwise set in-browser). |
| `LLM_BASE_URL` / `LLM_API_KEY` | _empty_ | OpenAI-compatible endpoint + key (or Ollama base URL; key blank). |
| `DISCOVERY_LIVE` | `true` (prod) | Real job-board scraping (off = offline fakes). |
| `SEARXNG_URL` | `http://searxng:8080` | SearXNG metasearch endpoint for discovery. |
| `NOTIFICATIONS_LIVE` | `true` (prod) | Real Discord/email send (off = captured, no network). |
| `DISCORD_WEBHOOK_URL` / `APPRISE_URLS` | _empty_ | Notification targets (Apprise URL syntax). |
| `CREDENTIAL_KEYFILE` | `secrets/master.key` | libsodium master key file for the credential vault (mode `0600`). |
| `BROWSER_CHANNEL` | `chrome` | Driving browser channel: `chrome` (real Google Chrome, default) \| `chromium` (fallback). Invalid → boot error. |
| `EGRESS_MODE` | `direct` | Browser egress: `direct` (host residential connection) \| `residential-proxy` (requires `EGRESS_PROXY_URL` + `EGRESS_RESIDENTIAL=true`). Datacenter exit refused. |
| `EGRESS_PROXY_URL` / `EGRESS_RESIDENTIAL` | _empty_ / `false` | Residential proxy URL + operator attestation it is residential (FR-STEALTH-4). |
| `EGRESS_TIMEZONE` / `EGRESS_LOCALE` | `America/Phoenix` / `en-US` | tz/locale pinned to the egress geolocation so the fingerprint ↔ exit IP stay consistent (FR-STEALTH-1). |
| `TAKEOVER_DESKTOP` | `cinnamon` | Takeover desktop DE: `cinnamon` (default) \| `xfce` \| `gnome` \| `pantheon`. Invalid → boot error. Every DE ships Google Chrome. |
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

See `src/applicant/app/config.py` for the full engine config surface; the front-door
UI reads `ENGINE_URL`, `APPLICANT_INTERNAL_TOKEN`, `SEARXNG_INSTANCE`,
`CHROMADB_*`, and its own `DATABASE_URL`.

## Enabling the real integrations

The default lane runs everything behind hermetic fakes. To go fully live, enable each
integration (all opt-in, none required to boot):

- **Persistence + durable execution (DBOS):** set `ORCHESTRATOR_BACKEND=dbos` and a
  reachable `DATABASE_URL`. DBOS owns its own system tables; Alembic manages the app
  schema. See [Durable orchestration backend](#durable-orchestration-backend).
- **Real browser pre-fill (Google Chrome via patchright):** `uv sync --extra browser`,
  install real `google-chrome-stable`, keep `BROWSER_CHANNEL=chrome`. The driver runs
  **headful** (never headless — a detection tell) on a per-tenant Chrome profile.

  **Coherent real-Linux/Chrome identity (FR-STEALTH-1).** The engine presents a single,
  internally-consistent **real Linux + Google Chrome** identity rather than a spoofed
  Windows persona: UA `Mozilla/5.0 (X11; Linux x86_64) ... Chrome/<major>` (the
  `<major>` derived from the *installed* Chrome), `navigator.platform = "Linux x86_64"`,
  `Sec-CH-UA-Platform: "Linux"`, a real Linux GPU (Mesa/llvmpipe) WebGL renderer —
  stable, not randomized, no canvas-noise. An incoherent spoof scores *worse* with bot
  detectors than an honest, coherent fingerprint on a residential IP, so coherence is
  the point. `EGRESS_TIMEZONE`/`EGRESS_LOCALE` are pinned to the egress geolocation so
  tz/locale ↔ exit IP stay consistent.
- **Live discovery:** `DISCOVERY_LIVE=true` (+ `SEARXNG_URL`, optional
  `DISCOVERY_PROXIES`) to scrape real boards via JobSpy + SearXNG.
- **Notifications:** `NOTIFICATIONS_LIVE=true` + `DISCORD_WEBHOOK_URL` / `APPRISE_URLS`.
  Also configurable in the wizard.
- **Live remote takeover (full Ubuntu desktop, default):** the takeover environment is a
  containerized, web-streamed **full Ubuntu desktop** the operator drives during an
  irreducible human step (CAPTCHA / account-creation / verification / final submit;
  FR-SANDBOX-2/3, FR-PREFILL-5). The DE is configurable via `TAKEOVER_DESKTOP`
  (default **Cinnamon**, plus **Xfce**, **GNOME**, **Pantheon**) and is an image swap;
  **every desktop ships real Google Chrome** (FR-STEALTH-1) so the human takes over the
  same Chrome the engine drives. All run on **X11** (not Wayland) for the streaming +
  automation path. Run with the `takeover` compose profile.
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

- **Engine data** lives in Postgres (the `pgdata`/`pgbackups` volumes): campaigns,
  attribute clouds, applications, screenshots, resume variants, learning state, durable
  workflow state. The **workspace UI** keeps its own state on the `ui-data` volume.
  Back up Postgres with `scripts/update.sh` (which dumps before every migration) or
  your own `pg_dump` schedule.
- **Secrets:** application credentials are sealed at rest with libsodium
  (XSalsa20-Poly1305); the master key is a `0600` key-file (`CREDENTIAL_KEYFILE`).
  Secrets are never logged (structlog redacts recursively, value-based).
- **Network posture:** single-operator on a private LAN/VPN over HTTP (see
  [Posture](#posture-single-operator-private-lanvpn)). Add a reverse proxy for TLS if
  you expose it beyond the private network.

---

# Operator guide

Applicant is operated entirely through the workspace front door (zero-CLI). Each
surface is a workspace section backed by an engine router; surfaces light up
progressively as setup completes.

### 1. First-run setup wizard

A resumable, slimmed wizard (FR-OOBE, FR-UI-5) auto-launches on first run as a
blocking overlay. It is deliberately reduced to the **only** setup that gates automated
work — fonts, the automation sandbox, and notification channels all moved into
**Settings** (which re-uses the exact wizard renderers). The three steps gate in order and
the engine will not start automated work until they're complete:

1. **Welcome.** A short orientation that frames what the assistant will and won't do
   (review-before-submit safety, the daily digest) before any configuration.
2. **Connect a model (gate).** Connect a provider/model — a cloud OpenAI-compatible API
   (paste an OpenRouter key) or a local Ollama URL (fully local). This step **reuses
   the workspace's existing Local/Remote model-endpoint manager** over
   `/api/model-endpoints`, not a new form. Optionally arrange a capability-ranked
   **tier ladder**. Nothing downstream unlocks until this is set.
3. **Your profile.** A Workday-ready interview (identity, work authorization,
   location/remote prefs, target roles, salary floor, full work history, education,
   references, key attributes, EEO — defaulting to "decline to self-identify", never
   AI-guessed). Your base résumé is parsed to bootstrap the **attribute cloud**;
   conflicts ask for confirmation. Finally you **accept or reject** the LaTeX
   conversion preview (accept → LaTeX-primary engine; reject → docx fallback).

Notification channels, fonts, and the automation sandbox are configured in **Settings**
afterwards (the wizard is re-launchable from there); they are not first-run gates.

### 2. The daily digest (approve / decline)

When matches accumulate, you get a per-campaign **digest** (email + the in-app digest
panel + a Discord "ready" ping). Each row shows the role, a brief summary, the posting
link, work mode, a viability score, and **why it was suggested**. You **approve**
(queue it for pre-fill) or **decline with feedback** (mandatory free-text) — and that
feedback feeds learning and tunes the next run's criteria. Empty days get a short
"here's what I searched and why" note. Notifications escalate: in-app if you're present
→ Discord (held ~30s) → email after a timeout; acting on one channel cancels the others.

### 3. Pending-actions home base

The 24/7 home base aggregates **everything awaiting you across all campaigns** — digest
approvals, material reviews, missing-attribute soft errors, agent questions,
account-creation handoffs, and final-submit approvals — each one actionable.

### 4. Application pre-fill and live takeover

For an approved role the engine spins up an isolated, stealthy browser **sandbox** and
pre-fills every field on every page from your attribute cloud (escalating ambiguous
mappings to the LLM, never guessing sensitive/EEO fields). It **stops at irreducible
human steps** — CAPTCHA, email/SMS verification, account-creating submit, final submit
— and notifies you with a **one-click live session** where you can finish the step
yourself or authorize the engine to continue. If a board gets hostile, **cautious mode**
pauses and hands off rather than risking your account. Credentials you enter (or that
the engine captures during account creation) are banked in the encrypted **vault**.

### 5. Material review and approval

When a role warrants tailored material, the engine generates a résumé variant and/or
cover letter and/or screening answers — truthfully (it reframes real experience, never
fabricates) and without AI tells (em-dashes stripped, your voice matched). Each artifact
is shown as a **redline** with additions and subtractions highlighted. Run the
interactive loop: accept, reject, free-text instruction, targeted add, or targeted
subtract. **Nothing is submitted until you approve it.**

### 6. Profile, chat, and activity

- **Profile:** edit criteria (integral edits confirmation-gated), the attribute cloud
  (including overridable learned/AI-added values; EEO never AI-guessed), and review
  résumé-conversion learning.
- **Chat / assistant:** converse to fill gaps in your profile or criteria; proposed
  changes go through the confirmation gate. Drive job actions (pending list, remote
  résumé actions) from here.
- **Activity / debug:** recent redacted logs, per-application history, captured
  screenshots, durable-workflow state, the variant library, run-mode/throughput
  controls, discovery-source toggles, mark-submitted, and the **Update button**.

### 7. How it learns

Every input — digest approvals/declines and their feedback, redline edits, pre-fill
soft-error resolutions, source yield, and actual **conversions** (approval **plus**
submission) — feeds per-campaign learning. The engine learns the signature of roles
that convert and biases discovery, scoring, and variant selection toward them —
transparently, and always overridable.

---

## Stack

Python 3.11+ · FastAPI (engine) + white-labeled no-build workspace UI (front door) ·
PostgreSQL + JSONB · DBOS Transact (durable execution) · LangGraph (in-step reasoning)
· patchright (browser automation) · JobSpy + SearXNG (discovery) · LaTeX/moderncv
primary resume engine with docx-XML fallback · Apprise/Discord notifications ·
ChromaDB + ntfy (workspace UI) · structlog. Toolchain: **uv**.

## Durable orchestration backend

The engine's durable backbone is pluggable via the `ORCHESTRATOR_BACKEND` env var:

- `shim` (**default**) — a file-backed checkpoint store (`CHECKPOINT_DIR`). Requires no
  Postgres, so the engine boots and the full test suite runs hermetically while still
  proving true mid-step resumption.
- `dbos` — the real DBOS Transact adapter (durable workflows, idempotent checkpointed
  steps, `send`/`recv` approval gates, cron scheduling, durable queues for concurrency
  caps / rate limits). Requires a live Postgres at `DATABASE_URL`.

## Status

**All phases (0–5) are implemented and merged to `main`,** plus a production-hardening
remediation pass and a front-door reachability re-audit. The engine is end-to-end
functional in its hermetic default lane, and every requirement is reachable in the
workspace front door (see [`docs/traceability.md`](traceability.md) and
[`docs/delivery-status.md`](delivery-status.md)).

- **Phase 0** — zero-CLI OOBE + onboarding, provider-agnostic LLM with a tier ladder,
  resumable onboarding interview, attribute-cloud bootstrap, durable orchestration
  backbone, structlog observability.
- **Phase 1** — discovery → digest → approve/decline → learning, per-campaign
  self-learning criteria + attribute cloud, pending-actions portal,
  Discord/web/email notifications with the escalation ladder.
- **Phase 2** — maximal Workday pre-fill in a stealth browser sandbox, stop-at-irreducible-
  human-steps handoff, one-click live remote session, cautious mode, encrypted
  credential vault, screenshot logging, submission detection.
- **Phase 3** — truthful material generation (LaTeX-primary / docx-XML fallback),
  cover letters, screening answers, guardrails, variant library, interactive redline
  review with a durable revision loop.
- **Phase 4** — conversion learning, per-tool toggle registry, Activity/debug surface,
  confirmation-gated chatbot, one-liner install/update with the in-UI Update button.
- **Phase 5 (front door)** — the white-labeled workspace front door: lift-and-shift of
  the wizard, chat, profile, documents, digest, remote, vault, and activity surfaces
  onto the workspace, wired to the engine through the bridge, with progressive
  feature activation. Reachability — not just engine delivery — is the definition of
  done.

**Tests:** the hermetic default lane is green. Real external integrations — live job
boards, a real browser, TeX, remote sessions, Postgres/DBOS durable execution, and
Discord/SMTP delivery — sit behind integration-gated boundaries that require a live
deployment.
