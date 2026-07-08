# Live verification: P1-1 TTFV stopwatch and P1-7 restore drill

Two Phase-1 stories carried an open box that only a **live run against a
standing stack with a real model** could close. This page records those runs:
what was stood up, what was measured, and — honestly — what could and could not
be exercised in the run environment. It pairs with the backlog rows P1-1 and
P1-7 in `docs/backlog/road-to-market.md`.

The model round-trips used an **owner-provided OpenRouter key** (base
`https://openrouter.ai/api/v1`) against a cheap, capable hosted model in the
tier ladder's floor class. No key material is recorded here or anywhere in the
repo.

## Stack stood up (single-host, no docker)

The run environment has no docker daemon, so the stack was brought up as native
processes rather than via `docker/docker-compose.prod.yml`:

- **Postgres 16** (`initdb` cluster on `127.0.0.1:5432`, db/user `applicant`).
- **Engine** — `uv run alembic upgrade head` (single head
  `0012_job_postings_easy_apply`) then `uv run uvicorn applicant.app.main:app
  --port 8000`. `/healthz` green: `database ok`, `credential_keydir ok`.
- **Front-door** — `workspace/` on `127.0.0.1:7000` (SQLite app DB, admin
  bootstrapped via `setup.py`), `ENGINE_URL=http://127.0.0.1:8000`.

Every step below was driven through the **white-labeled front-door proxies**
(`/api/applicant/*` on :7000), not the engine directly — the reachable surface
per CLAUDE.md principle #2.

## P1-1 — TTFV stopwatch (live model)

**What was measured.** Wall-clock latency of the three-action critical path that
`tests/unit/test_p1_1_ttfv_walkthrough.py` pins, driven live end-to-end: from a
fresh login to the moment the automated-work gate opens (the "first value"
moment — the 24/7 loop may now discover + digest). The clock starts after login
on a **freshly migrated, empty database**.

| Action | What ran (live) | Latency |
| --- | --- | --- |
| 1. Connect a model | Verify round-trip (live catalog probe, 345 models listed) → save endpoint → configure engine LLM | ~1.0–1.6 s |
| 2. Upload résumé | deterministic parse **+ live LLM parse-verify re-slot** | ~13 s |
| 3. Confirm criteria | integral-change 409 → explicit confirm → commit | ~0.2 s |
| gate status read | `automated_work_allowed` | ~0.1 s |
| **Total machine critical-path latency** | | **~14–15 s** |

Two clean fresh-DB runs: **15.3 s** and **14.4 s**. `automated_work_allowed`
flipped to **true** in both (`gate_open: true`, `onboarding_complete: true`).

The parse-verify step ran on the live model and returned `verified: true`, tier
1 (no escalation), per-area confidence all `1.0`, and **zero** corrections,
unsourced drops, or restorations — consistent with the tier study
(`docs/studies/2026-07-07-parse-verify-tier-study.md`). `parsed_field_count: 8`.

**Verdict vs the 10-minute bar: PASS with wide margin.** The system-imposed
latency on the critical path — the part a live model makes unpredictable, and
the part the earlier hermetic walkthrough could not measure — is ~15 s, leaving
> 9m 40s of the 10-minute budget for the user's own review/typing. The
three-action design plus résumé prefill (identity, work history incl.
achievements, education, skills) is what keeps the human remainder small.

**Honest boundaries.**
- The measured quantity is **machine critical-path latency**, not a full human
  wall-clock; a human's read/edit time sits on top of the ~15 s but within the
  remaining budget, and is bounded by the 3-action prefill design.
- The stack was native processes on one host, not the `docker-compose.prod.yml`
  deploy. The application code path (front-door proxy → engine → live model) is
  identical; only the process/orchestration substrate differs.
- The DoD's historical phrase "channel set" predates the wizard slimming
  (channels now live in Settings and are **not** part of the gating critical
  path — `automated_work_allowed` opened here with no channel configured). The
  operative first-value gate is model + parsed profile + confirmed criteria.

Reproduce: stand up the stack as above, then drive the three front-door actions
(`POST /api/applicant/setup/model-endpoints/test|…`, `…/from-endpoint`,
`…/onboarding/{cid}/base-resume`, `PUT /api/applicant/memory/criteria` with
`confirm:true`) and read `GET /api/applicant/setup/status`.

## P1-7 — backup → destroy → restore drill

The shipped drill (`scripts/backup-restore-drill.sh --confirm-destroy`) is
docker-compose-native: it runs `docker compose down -v` (wiping the
`pgdata`/`ui-data`/`secrets`/… named volumes), brings the stack back up, restores
via `scripts/restore.sh`, migrates, and heartbeats both services. With no docker
daemon available it could not run as-is.

**What WAS exercised (live):**

1. **Control flow of the shipped script** — `tests/unit/
   test_backup_restore_drill_script.py` (fake `docker` on `PATH`): **4 passed**.
2. **The data-safety roundtrip at the Postgres layer**, using the *exact* dump
   and restore commands `scripts/lib/backup-common.sh` uses (`pg_dump --clean
   --if-exists`, `psql -v ON_ERROR_STOP=1`), just without the docker wrapper:
   - **Backup** a live DB carrying the full configured TTFV state (model
     endpoint, campaigns, parsed attributes, agent runs) → 67 KB dump.
   - **Destroy**: `DROP DATABASE applicant` (the data-layer equivalent of
     `down -v` wiping `pgdata`).
   - **Fresh empty DB** (0 tables) → **Restore** the dump → restore OK.
   - **Integrity compare: PASS** — row counts (`campaigns`, `app_config`,
     `attributes`, `agent_runs`, `pending_actions`) and a campaign-content md5
     were **identical** before and after.
3. **"The app returns whole"** — restarting the engine against the restored DB:
   `/healthz` green (`db ok`), single Alembic head, and `GET /api/setup/status`
   still reported `llm_configured: true`, `gate_open: true`,
   `automated_work_allowed: true`, `onboarding_complete: true`. The fully
   configured application came back from the backup alone.

**What was NOT exercised (needs a real docker-compose deploy):**

- `docker compose down -v` of the actual **named volumes** and `up -d` of fresh
  ones.
- The **engine-state.tar.gz** member (credential vault master key + checkpoints
  + fonts + browser profiles volumes) and the **workspace-data.tar.gz** member
  (the front-door `ui-data` volume) — both are `docker compose exec/run` volume
  captures with no host path to reach natively.
- The two-service **heartbeat** (`/api/health` on the UI + engine `/healthz` via
  `docker compose exec`).

**Verdict: the data-safety core is proven live; the compose-orchestration wrapper
remains to be run on a real deployment.** The Postgres backup→destroy→restore
roundtrip that carries the irreplaceable job-search data survives a full wipe
using the shipped commands, and the configured app returns whole. Running
`--confirm-destroy` against a live/disposable `docker-compose.prod.yml` stack
(to also cover the volume tarballs and the heartbeat) is the remaining step and
keeps P1-7's third DoD box open.
