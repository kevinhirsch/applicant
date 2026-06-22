# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Applicant** is an autonomous job-application engine behind a white-labeled front-door UI. It is a
**two-app system** in one repo:

- **Engine** — `src/applicant/`: a hexagonal FastAPI app (`create_app()` → `applicant.app.main:app`),
  Postgres + Alembic, the autonomous agent/pre-fill/discovery/digest/learning logic. Runs as the
  internal `api` service (never published to the host).
- **Front-door** — `workspace/`: a vendored, white-labeled multi-user AI-workspace app (FastAPI +
  vanilla-JS ES modules, no build step) that is the **only** public surface (`applicant-ui` service
  on `${APP_PORT}` → container 7000). It proxies to the engine; it does not duplicate engine logic.

The authority for behavior is `docs/spec/master-spec.md` (FR-/NFR- requirements). `workspace/CLAUDE.md`
documents the vendored app's internals.

## Commands

Engine (repo root; uses `uv`, Python 3.11):
```bash
uv sync                                            # install deps (incl. dev: ruff, pytest)
uv run pytest -q                                   # full engine suite (testpaths=tests; integration tests are @pytest.mark.integration)
uv run pytest tests/unit/test_x.py::test_name      # single test (or: -k "keyword")
uv run pytest -m "not integration"                 # default-style run (hermetic only)
# Gotcha: DATABASE_URL defaults to localhost:5432, so when a Postgres is reachable
# (deploy stack / dev container up) the suite uses the REAL DB. Force the hermetic
# in-memory lane with an unreachable URL — this is the green-increment test command:
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' uv run pytest -q -m "not integration"
uv run ruff check .                                # lint (workspace/ is extend-excluded)
uv run python -c "from applicant.app.main import app"   # import/boot smoke
uv run alembic heads                               # MUST be a single head
uv run alembic upgrade head                        # apply migrations
```

Front-door (workspace): runs under the **root** `uv` env for the Applicant proxy tests; the vendored
app has its own heavier deps not installed here, so only run the `applicant_*` tests:
```bash
uv run pytest -q workspace/tests/test_applicant_*.py    # front-door proxy/lane tests
python -m compileall -q workspace/app.py workspace/routes workspace/src   # workspace syntax
node --check workspace/static/js/<file>.js              # front-end has no bundler — node --check only
```
To **boot the front-door locally** for UI / playtest work, install the vendored deps into the root
env once (`uv pip install -r workspace/requirements.txt`), then run it pointed at the engine:
```bash
cd workspace && DATABASE_URL="sqlite:///$(pwd)/data/app.db" ENGINE_URL=http://127.0.0.1:8000 \
  APPLICANT_ADMIN_USER=admin APPLICANT_ADMIN_PASSWORD=<pw> python setup.py   # SQLite + admin (re-runnable)
cd workspace && DATABASE_URL=... ENGINE_URL=http://127.0.0.1:8000 uv run uvicorn app:app --port 7000
```
The engine needs Postgres (default DSN `postgresql+psycopg://applicant:applicant@localhost:5432/applicant`
+ `alembic upgrade head`), not SQLite. `workspace/app.py` re-reads `.js/.css/.html` per request, so
**front-end edits need no restart** — only engine/Python changes do. `docs/playtest-protocol.md` is the
full stand-up + UI-regression playbook, incl. §6a's **automated Playwright UI monkey/crawl** (open every
surface, click every control, classify findings, run-until-green) for full-product front-door testing.

Deploy / stack:
```bash
docker compose -f docker/docker-compose.prod.yml config         # validate compose
bash scripts/proxmox-deploy.sh                                  # one-liner: create Proxmox VM + provision
bash scripts/install.sh --apply                                 # bring up the Compose stack (dry-run without --apply)
bash scripts/update.sh --apply                                  # git-sync → backup → build → migrate → restart → heartbeat
```
Stack services: `applicant-ui` (public) + `api` (internal) + `postgres` + `searxng` + `chromadb` +
`ntfy` (+ optional `takeover-desktop`). CI (`.github/workflows/ci.yml`) gates every PR on: ruff,
engine pytest, the front-door proxy tests, single Alembic head, workspace compileall, `node --check`
on all workspace JS, `docker compose config`, and the white-label codename denylist.

## Architecture (the big picture)

**Engine — hexagonal** (`src/applicant/`): `core/` (domain entities + rules — pure, no IO),
`ports/` (driving/driven Protocols), `adapters/` (browser/stealth, sandbox, storage, notification,
resume_tailoring, discovery, workspace-callback — swappable per NFR-EXT-1), `application/services/`
(use-cases), `app/` (FastAPI: `routers/`, `container.py` DI, per-request DB session, `config.py`,
lifespan), `observability/`. Durable orchestration (DBOS or the default in-process "shim") survives
restarts; an in-process scheduler drives the 24/7 loop. **The scheduler rebuilds a fresh `AgentLoop`
per tick** (per-tick Session isolation, `container._build_tick_services`), so any state that must
persist across ticks (e.g. the resume backoff/failure ledger) lives in a process-lived object
injected into every loop — NOT on the instance, or it silently resets each tick. Safety is enforced
in the core: review-before-submit and the pre-fill stop-boundary mean the engine **cannot**
self-authorize a final submit. Enforce such guards server-side (e.g. the fabrication guard derives
its own ground truth) — never rely on a caller-supplied input to opt a safety check in.

**The bridge (bidirectional):**
- workspace → engine: `workspace/src/applicant_engine.py` (`ApplicantEngineClient`, `ENGINE_URL`,
  default `http://api:8000`). The ~12 `workspace/routes/applicant_*_routes.py` are thin auth-protected,
  owner-scoped proxies over it (`/api/applicant/*`).
- engine → workspace (callback): `workspace/routes/applicant_internal_routes.py`, a token-gated
  (`APPLICANT_INTERNAL_TOKEN`) channel at `/api/applicant/internal/*` the engine calls via
  `WORKSPACE_URL` (calendar interviews, deep-research, Cookbook local models). Token unset ⇒ disabled.

**Front-door surfacing:** each engine capability is reachable through proxy → JS (`workspace/static/js/
applicant*.js`) → nav. `workspace/src/applicant_features.py` computes per-section state (active /
locked / disabled) from the engine's setup-status + dormant-surface registry, so sections light up as
configured and there is no dead UI. The Pending-Actions **Portal** is the post-login home base **and the
in-app notification center**: action-required items persist there and clear when handled; informational
notifications appear too and pop browser toasts (reuse `ui.js` `showToast`, do not rebuild). The engine's
in-app inbox is exposed by `app/routers/notifications.py`; Discord/email are opt-in **fan-out of the same
notifications**, configured in Settings. The OOBE **wizard** (`applicantOnboarding.js`) is slimmed to
**Connect a model → Your profile** — the only setup that gates automated work; fonts, the automation
sandbox, and notification channels live in **Settings**, which reuses the exact wizard renderers via the
exported `mountSettingsStep`. The wizard still takes precedence when setup is incomplete and is
re-launchable from Settings (`window.launchApplicantSetup`). Daily loop: digest → review (redline
add/subtract/free-text, `documentLibrary.js`) → approve/decline → final-submit (Portal / live takeover,
`applicantRemote.js`).

**Two static surfaces — don't confuse them.** The engine ships its *own* built-in UI under
`frontend/static/applicant/` (setup/review/digest/chat/criteria `.html` + matching `.js`), mounted at
`/static` with `/` and `/wizard` served by `app/routers/ui.py` (`APP_STATIC_DIR=frontend/static`,
`app/static.py`). That is the engine's direct shell, but the `api` service is internal-only — the
**public** surface is still the white-labeled `workspace/` front-door, so reachability (principle #2)
means the `workspace/` chain, not `frontend/`. Resume rendering reads Jinja sources from `templates/`:
`templates/latex/moderncv/main.tex.j2` + `cover/cover.tex.j2` (+ `OpenFonts/`) for the LaTeX path and
`templates/docx/` (OOXML in-place edit of the user's own `.docx`) for the fallback. Both `frontend/`
and `templates/` are `COPY`-ed into the engine image (`docker/Dockerfile`) and read at runtime.

## Runtime dependencies & deploy gotchas

The engine shells out to external binaries and **detects them via `shutil.which()` — silently degrading
(no real output) when absent**, so they must be baked into the engine image (`docker/Dockerfile`), not
just the host:
- **Resume rendering** (FR-RESUME-3/4): TeX (`xelatex`/`lualatex` + moderncv/fontspec/fontawesome5) for
  the LaTeX path and **LibreOffice** headless (`soffice --convert-to pdf`) for the docx fallback. Both
  paths are reachable depending on the onboarding accept/reject choice.
- **Pre-fill / Workday automation** (FR-PREFILL, FR-STEALTH): the `browser` optional extra
  (`uv sync --extra browser`). `BROWSER_ENGINE` selects the browser ALL outbound automation traffic
  routes through: the default **`camoufox`** (a Firefox-based anti-detect browser; `camoufox fetch`
  downloads its binary + the GeoIP dataset into the image, and it renders headful on Xvfb inside the
  display-less container), or the fallback **`chromium`** (patchright **plus a real Google Chrome**,
  `BROWSER_CHANNEL=chrome`). The engine wires the real `PatchrightBrowser` unconditionally
  (`container.py`); the default local sandbox launches the browser **inside the `api` container** (no
  CDP endpoint), so the binary must live in that image. Camoufox injects its OWN coherent fingerprint,
  so the Chrome WebGL/`Sec-CH-UA` init-script override is applied only on the `chromium` path. The
  takeover/Proxmox sandbox is Chrome-specific — it forces `chromium` and connects to a remote Chrome
  over CDP.
- **Durable orchestration**: `dbos` is an **optional** extra (`durable-orchestration`); the default
  `ORCHESTRATOR_BACKEND=shim` (in-process checkpoints) needs nothing extra. Select `dbos` only to
  co-reside workflow state in Postgres.

The integration tests for these paths are `@pytest.mark.integration` and **skip when the dep is absent**
— a skip is a signal that the *deployed image* needs that dependency, not just a quirk of the test box.
CI validates `docker compose config` but does **not** build images, so the apt/Chrome layers are first
exercised by the real `compose up --build` at deploy time.

## Binding working principles (read before building anything)

1. **Lift and shift first — never rebuild what exists.** If logic or UI for something already exists
   anywhere in the tree, **copy that component into the new location first**, get it working unchanged,
   and only **then adapt it by extension and removal** to meet the spec for the new context. Do NOT
   write a fresh from-scratch implementation when a working one exists. (E.g. the OOBE "Connect a
   model" step reuses the existing Local/Remote endpoint manager — `workspace/static/js/admin.js`
   `initEndpointForm`/`loadEndpoints` over the workspace's own `/api/model-endpoints` in
   `workspace/routes/model_routes.py` — not a new form.)

2. **Reachability is the definition of done.** A requirement is not done because the engine implements
   it and tests pass — it is done when it is **reachable/operable in the white-labeled front-door**.
   Verify the whole chain: spec → engine endpoint → workspace proxy → JS → nav/section. The
   traceability docs verify only the engine; do not trust them for reachability.

3. **White-label, always.** Zero references to the upstream fork's vendor/persona codenames, and zero
   `FR-`/`NFR-` jargon, in user-facing strings (and shipped artifacts generally). The product is
   **Applicant**. Plain language + tooltips. The CI **white-label check** holds the codename denylist
   and fails the build on any match.

4. **Front-door proxies; the engine owns logic.** Workspace `/api/applicant/*` routes are thin
   auth-protected, owner-scoped proxies over the engine client; reuse the engine's gates (e.g.
   `require_automated_work`) rather than re-implementing them. UI styling reuses the workspace design
   system (`.cal-btn`, `.admin-card`, `.settings-*`, `.memory-*`) — don't hand-roll button sizes or
   undefined classes.

5. **Green increments.** Before merge: `uv run pytest -q`, the front-door `test_applicant_*` tests,
   `uv run ruff check .`, the boot smoke, a single Alembic head, and `docker compose ... config`
   must pass — i.e. everything CI gates. Keep PRs focused; develop on a branch and open a PR. PRs are
   **squash-merged**, so after each merge the working branch diverges from `main` (its commits are not
   `main`'s squashed one) and `git push` is rejected non-fast-forward — the merged work is already in
   `main`, so realign with `git fetch origin main && git reset --hard origin/main` before continuing
   (force-push to rewrite shared history is blocked).

See `workspace/CLAUDE.md` for the vendored app's internals, `docs/spec/master-spec.md` for the
requirement set, and `docs/playtest-protocol.md` for the repeatable front-door audit + UI-regression
playbook (stand up the live stack, the five HCI lenses, the contract sweep, and the automated
monkey/crawl).
