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
| [`docs/dormant-surfaces.md`](docs/dormant-surfaces.md) | Dormant Surface Wiring Backlog |
| [`docs/onboarding-intake.md`](docs/onboarding-intake.md) | Workday-ready onboarding intake schema |
| [`docs/voice-and-truthfulness.md`](docs/voice-and-truthfulness.md) | Non-AI-looking + truthfulness guardrails |
| [`docs/open-items.md`](docs/open-items.md) | Open items and defaults |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |

## Install (one-liner) and update

Applicant ships the whole stack — FastAPI + frontend, PostgreSQL, SearXNG, on-demand
Neko, font-install — as a Docker Compose deployment (FR-INSTALL-1/3). No `make` needed.

**One-liner install** (Proxmox-helper-script style; idempotent, data-safe; runs the
Compose stack and Alembic migrations, then OOBE finishes in-browser — NFR-ZEROCLI-1):

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/<org>/applicant/main/scripts/install.sh)" -- --apply
```

Or from a checkout (dry-run by default — prints the steps; add `--apply` to run them):

```bash
bash scripts/install.sh            # dry-run preview
bash scripts/install.sh --apply    # provision: compose up + alembic upgrade head
```

Editable defaults are environment-driven (`POSTGRES_USER`, `POSTGRES_PASSWORD`,
`POSTGRES_DB`, `APP_URL`). Then open `http://localhost:8000` and complete the wizard.

**Update** — backs up the DB, pulls, runs migrations, restarts, and supports
**rollback** of the most recent backup on failure (FR-INSTALL-2). Safe-by-default
(dry-run unless `--apply`):

```bash
bash scripts/update.sh --apply              # backup → pull → migrate → restart
bash scripts/update.sh --rollback --apply   # restore the most recent DB backup
```

The same update flow is invokable from the **in-UI Update button** on the debug
surface (`/debug`) without any CLI (FR-OOBE-4); real dispatch is guarded behind
`APPLICANT_UPDATE_ENABLED=1`, otherwise it reports a safe dry-run.

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

Specification complete; implementation scaffolding in progress (see
[`docs/work-packages.md`](docs/work-packages.md)).
