#!/usr/bin/env bash
#
# Applicant — full restore (P1-7, issue #659).
#
# The inverse of scripts/backup.sh: given ONE backup tarball (db.sql +
# workspace-data.tar.gz + config/.env — see backup.sh's header for exactly what
# each member is), restores Postgres, the front-door UI's own data/, and the
# deploy config onto a running (or freshly-provisioned) compose stack.
#
# ── Usage ────────────────────────────────────────────────────────────────────
#
#   scripts/restore.sh [--apply] [--from PATH]
#
#   (default: dry-run — prints every step it would run; pass --apply to run
#   them. Without --from, the NEWEST applicant-full-*.tar.gz under
#   APPLICANT_BACKUP_DIR/.backups is used.)
#
# ── Typical recovery walkthrough (fresh host, or after `docker compose down -v`)
#
#   1. Provision the stack's containers WITHOUT letting them serve real work
#      yet, so Postgres and the UI container exist to restore into:
#        docker compose -f docker/docker-compose.prod.yml up -d postgres applicant-ui
#      (a fresh/empty postgres volume is fine — the dump's `--clean --if-exists`
#      flags make the restore idempotent against an empty OR a partially-
#      migrated schema.)
#   2. Wait for both to report healthy:
#        docker compose -f docker/docker-compose.prod.yml ps
#   3. Run this script:
#        scripts/restore.sh --apply --from .backups/applicant-full-<timestamp>.tar.gz
#   4. Run migrations (a restored dump is from SOME prior schema version; bring
#      it up to the code now on disk) and bring up the rest of the stack:
#        docker compose -f docker/docker-compose.prod.yml run --rm api uv run alembic upgrade head
#        docker compose -f docker/docker-compose.prod.yml up -d
#   5. Verify: docker compose ... ps, then open the app and confirm your
#      applications/documents/profile are back.
#
# scripts/backup-restore-drill.sh automates exactly this sequence end-to-end
# against a live compose stack (backup -> `down -v` [destroy volumes] ->
# provision -> restore -> migrate -> up -> health-check) — see its header and
# docs/backup-restore.md for the full drill.
#
# ── What this script does NOT do ─────────────────────────────────────────────
# It never overwrites an EXISTING .env in place — if one is already present at
# the destination, the restored copy is written to `.env.restored` instead so
# you can diff/merge by hand (a restore is exactly the situation where you do
# NOT want to silently swap out live credentials for a backup's).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
# Overridable (APPLICANT_ENV_FILE) so tests can point this at a scratch path
# instead of ever touching the real deploy .env — mirrors APPLICANT_BACKUP_DIR
# below. Real deploys leave this unset and get the normal repo-root .env.
ENV_FILE="${APPLICANT_ENV_FILE:-${REPO_ROOT}/.env}"
BACKUP_DIR="${APPLICANT_BACKUP_DIR:-${REPO_ROOT}/.backups}"

# shellcheck source=lib/backup-common.sh
source "${REPO_ROOT}/scripts/lib/backup-common.sh"
bkup_load_env "${ENV_FILE}"

DB_SERVICE="postgres"
UI_SERVICE="applicant-ui"
DB_NAME="${POSTGRES_DB:-applicant}"
DB_USER="${POSTGRES_USER:-applicant}"

APPLY=0
FROM=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1; shift ;;
    --from) FROM="${2:?--from requires a PATH}"; shift 2 ;;
    --from=*) FROM="${1#--from=}"; shift ;;
    -h|--help)
      echo "Usage: restore.sh [--apply] [--from PATH]"
      echo "  (default: dry-run — prints the steps it would run; --apply runs them)"
      echo "  Without --from, the newest applicant-full-*.tar.gz in ${BACKUP_DIR} is used."
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;35m[restore]\033[0m %s\n' "$*"; }

if [[ -z "${FROM}" ]]; then
  FROM="$(ls -1t "${BACKUP_DIR}"/applicant-full-*.tar.gz 2>/dev/null | head -n1 || true)"
  if [[ -z "${FROM}" ]]; then
    echo "No backup tarball found under ${BACKUP_DIR} and none given via --from. Nothing to restore." >&2
    exit 1
  fi
  log "No --from given; using the newest backup: ${FROM}"
fi

if [[ ! -f "${FROM}" ]]; then
  echo "Backup tarball not found: ${FROM}" >&2
  exit 1
fi

if [[ "${APPLY}" -eq 1 ]]; then
  STAGE_DIR="$(mktemp -d)"
  trap 'rm -rf "${STAGE_DIR}"' EXIT
else
  STAGE_DIR="${BACKUP_DIR}/.dry-run-restore-preview"
fi

log "1/4 Extracting ${FROM}"
bkup_extract_tarball "${FROM}" "${STAGE_DIR}" "${APPLY}"

if [[ "${APPLY}" -eq 1 && -f "${STAGE_DIR}/MANIFEST.txt" ]]; then
  log "Manifest:"
  sed 's/^/    /' "${STAGE_DIR}/MANIFEST.txt"
fi

log "2/4 Restoring the Postgres database"
if [[ "${APPLY}" -eq 1 && ! -f "${STAGE_DIR}/db.sql" ]]; then
  echo "    (skip) this backup has no db.sql member — nothing to restore into Postgres." >&2
else
  bkup_restore_database "${COMPOSE_FILE}" "${DB_SERVICE}" "${DB_USER}" "${DB_NAME}" \
    "${STAGE_DIR}/db.sql" "${APPLY}"
fi

log "3/4 Restoring workspace data/ (front-door UI)"
if [[ "${APPLY}" -eq 1 && ! -f "${STAGE_DIR}/workspace-data.tar.gz" ]]; then
  echo "    (skip) this backup has no workspace-data.tar.gz member." >&2
else
  bkup_restore_workspace_data "${COMPOSE_FILE}" "${UI_SERVICE}" \
    "${STAGE_DIR}/workspace-data.tar.gz" "${APPLY}"
fi

log "4/4 Restoring config (.env)"
if [[ "${APPLY}" -ne 1 ]]; then
  # The dry run never extracts the tarball, so the member check inside
  # bkup_restore_config would always (wrongly) report "no config/.env member" —
  # preview the action instead, mirroring the DB/workspace steps above.
  echo "    (would run) install -m 600 ${STAGE_DIR}/config/.env ${ENV_FILE} (or ${ENV_FILE}.restored if it exists)"
else
  bkup_restore_config "${STAGE_DIR}/config" "${ENV_FILE}" "${APPLY}"
fi

if [[ "${APPLY}" -eq 1 ]]; then
  log "Restore complete from ${FROM}."
  log "Next: run migrations + bring up the full stack (see this script's header) —"
  log "  docker compose -f ${COMPOSE_FILE} run --rm api uv run alembic upgrade head"
  log "  docker compose -f ${COMPOSE_FILE} up -d"
else
  log "DRY RUN complete (no --apply). Re-run with --apply to perform the restore."
fi
