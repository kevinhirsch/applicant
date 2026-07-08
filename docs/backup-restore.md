# Backup, restore, and data export (P1-7, issue #659)

An irreplaceable job search — the résumé, every generated document, the profile
attribute cloud, and the application history — lives in this self-hosted
instance. This page covers the two ways it survives:

1. **Operator backup/restore** — `scripts/backup.sh` / `scripts/restore.sh`, a
   full tarball of Postgres + the front-door UI's own data + the deploy config,
   for recovering the whole instance (disk failure, bad host migration,
   accidental `docker compose down -v`).
2. **Owner data export** — Settings → Account → "Download my data", a zip of
   just the owner's own applications/documents/profile/activity, for the
   owner's own copy (not an operator concern, no shell access needed).

## 1. Operator backup

```bash
scripts/backup.sh --apply
```

Produces ONE tarball at `.backups/applicant-full-<timestamp>.tar.gz` (override
the directory with `APPLICANT_BACKUP_DIR`) containing:

| Member                     | What it is                                                          |
|----------------------------|----------------------------------------------------------------------|
| `db.sql`                   | Postgres dump (`pg_dump --clean --if-exists`) — the engine's data.   |
| `workspace-data.tar.gz`    | The front-door UI's own `data/` (its sqlite DB, uploaded documents, prefs, caches — the `ui-data` named volume). |
| `config/.env`              | The deploy secrets/config (`POSTGRES_PASSWORD`, `APPLICANT_INTERNAL_TOKEN`, LLM keys, ...). Omitted (not an error) when no `.env` is present. |
| `MANIFEST.txt`             | Which of the above actually landed in this tarball, and when.       |

Without `--apply` it is a dry run — it prints every command it would run and
touches nothing. The retention is the newest `BACKUP_KEEP_COUNT` tarballs
(default 7; `0` disables pruning) — its own namespace, independent of
`update.sh`'s `applicant-*.sql` DB-only dumps (below).

### Wired into `scripts/update.sh`

`update.sh`'s existing pre-migration step (`pg_dump` before every schema
migration, the safety net its `--rollback` restores from) is untouched — every
test pinning its exact behavior still holds. Right after that dump succeeds,
`update.sh` now ALSO calls `scripts/backup.sh --reuse-db-dump <the dump it just
took>` to produce the fuller tarball above, sharing the dump/export/bundle
logic via `scripts/lib/backup-common.sh` rather than a second implementation.
This is additive: a failure producing the fuller tarball is logged as a warning
and never aborts the update — the original DB-only dump is still the update
flow's real rollback safety net.

## 2. Operator restore

```bash
# Fresh host, or after `docker compose down -v`:
docker compose -f docker/docker-compose.prod.yml up -d postgres applicant-ui
docker compose -f docker/docker-compose.prod.yml ps   # wait for both healthy

scripts/restore.sh --apply --from .backups/applicant-full-<timestamp>.tar.gz
# (omit --from to restore the newest tarball under APPLICANT_BACKUP_DIR)

docker compose -f docker/docker-compose.prod.yml run --rm api uv run alembic upgrade head
docker compose -f docker/docker-compose.prod.yml up -d
```

Notes:

- The Postgres dump carries `--clean --if-exists`, so restoring onto an empty
  OR partially-migrated database is idempotent.
- Restoring the config never silently overwrites a `.env` that already exists
  at the destination — the restored copy is written to `.env.restored`
  alongside it instead, so you diff/merge by hand rather than losing whichever
  secrets were live before the restore.
- Without `--apply` it is a dry run.

## 3. The backup → destroy volumes → restore drill

`scripts/backup-restore-drill.sh` automates the DoD's "backup → destroy volumes
→ restore" verification end to end against a **live** compose stack:

```bash
scripts/backup-restore-drill.sh                  # dry run: prints the plan only
scripts/backup-restore-drill.sh --confirm-destroy # actually runs it
```

It: takes a fresh backup, `docker compose down -v` (genuinely **destroys every
named volume**), brings `postgres` + `applicant-ui` back up empty, restores
from the backup just taken, migrates, brings up the full stack, then polls
`/api/health` + `/healthz` until both are green ("the app returns whole").

**This needs a real compose stack and is destructive** — run it against a
disposable/staging deployment you can afford to lose, never blind against
production. It is intentionally NOT part of CI or the hermetic test suite for
that reason; `tests/unit/test_backup_restore_drill_script.py` covers its
control flow hermetically (fake `docker` on `PATH`), but the actual
"comes back whole against a live stack" claim needs a manual run — see the PR
that introduced this doc for the current verification status.

## 4. Owner data export ("Download my data")

Settings → Account → **Download my data** (front-door: `workspace/static/js/
settings.js`, backed by the owner-scoped proxy `GET
/api/applicant/export/data.zip`, `workspace/routes/applicant_export_routes.py`)
downloads a zip with:

| File                          | Contents                                                             |
|--------------------------------|------------------------------------------------------------------------|
| `applications.csv` / `.json`  | Every application (role, company, status, signals, dates) — CSV opens directly in Excel (UTF-8 BOM-prefixed); JSON for anything else. |
| `profile.json`                | The attribute cloud (the facts the engine pre-fills) per campaign.   |
| `activity.json`               | The recent agent-run history per campaign.                           |
| `documents/documents.json`    | Per-application generated-document metadata + the résumé-variant library. |
| `documents/resume-<id>.pdf`   | The compiled résumé PDF for each variant the engine has rendered.    |

Gated by `require_engine_owner` (the engine is single-tenant — CLAUDE.md — so
this is owner-scoped, not just "any logged-in account"). Every section
degrades soft: an unreachable engine, or one failed per-campaign/per-application
read, still produces a well-formed zip whose `manifest.json` honestly records
what happened (H-series honesty invariant — an incomplete export must never
look indistinguishable from a complete one).
