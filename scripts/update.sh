#!/usr/bin/env bash
#
# Applicant — one-liner updater (FR-INSTALL-2, FR-OOBE-4, NFR-ZEROCLI-1).
#
# Invoked by the in-UI Update button (via /api/update/trigger) OR directly:
#   bash scripts/update.sh [--apply] [--rollback]
#
# Update flow (the safe order — backup BEFORE migrate, so rollback is always
# possible):
#   1. Back up the Postgres database (timestamped dump).
#   2. Pull the new images / code.
#   3. Run database migrations (Alembic).
#   4. Restart the stack.
# A failure at any step leaves the prior DB dump intact for --rollback.
#
# SAFETY: this is a WELL-COMMENTED SCAFFOLD STUB. It performs NO destructive
# operations by default — it PRINTS the steps it would run. Pass --apply to run
# them. --rollback restores the most recent backup (also dry-run unless --apply).
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
BACKUP_DIR="${APPLICANT_BACKUP_DIR:-${REPO_ROOT}/.backups}"
DB_SERVICE="postgres"
DB_NAME="${POSTGRES_DB:-applicant}"
DB_USER="${POSTGRES_USER:-applicant}"
APPLY=0
ROLLBACK=0

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --rollback) ROLLBACK=1 ;;
    -h|--help)
      echo "Usage: update.sh [--apply] [--rollback]"
      echo "  (default: dry-run — prints steps; --apply runs them)"
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;33m[update]\033[0m %s\n' "$*"; }
run() {
  # Execute when --apply, otherwise echo the command (dry-run default).
  if [[ "${APPLY}" -eq 1 ]]; then "$@"; else echo "    (would run) $*"; fi
}

TS="$(date +%Y%m%d-%H%M%S)"
DUMP_FILE="${BACKUP_DIR}/applicant-${TS}.sql"

# --- rollback path ----------------------------------------------------------
if [[ "${ROLLBACK}" -eq 1 ]]; then
  log "Rollback requested — restoring the most recent backup."
  LATEST="$(ls -1t "${BACKUP_DIR}"/applicant-*.sql 2>/dev/null | head -n1 || true)"
  if [[ -z "${LATEST}" ]]; then
    echo "No backup found in ${BACKUP_DIR}; nothing to roll back." >&2
    exit 1
  fi
  log "Latest backup: ${LATEST}"
  run docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
    psql -U "${DB_USER}" -d "${DB_NAME}" -f "${LATEST}"
  log "Rollback complete (or dry-run printed above)."
  exit 0
fi

# --- update path ------------------------------------------------------------
log "Update flow (backup → pull → migrate → restart)."
run mkdir -p "${BACKUP_DIR}"

log "1/4 Backing up the database to ${DUMP_FILE}"
# Back up BEFORE migrate so rollback is always possible (FR-INSTALL-2). A failed or
# empty backup MUST abort the update — never proceed to migrate with no valid dump.
if [[ "${APPLY}" -eq 1 ]]; then
  if ! docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
      pg_dump -U "${DB_USER}" "${DB_NAME}" >"${DUMP_FILE}"; then
    echo "Backup failed (pg_dump errored); aborting before migrate." >&2
    rm -f "${DUMP_FILE}"
    exit 1
  fi
  if [[ ! -s "${DUMP_FILE}" ]]; then
    echo "Backup is empty (${DUMP_FILE}); aborting before migrate." >&2
    rm -f "${DUMP_FILE}"
    exit 1
  fi
  log "Backup OK ($(wc -c <"${DUMP_FILE}") bytes)."
else
  # Dry-run: print the command WITHOUT redirecting anything into the dump file.
  echo "    (would run) docker compose -f ${COMPOSE_FILE} exec -T ${DB_SERVICE} pg_dump -U ${DB_USER} ${DB_NAME} >${DUMP_FILE}"
fi

log "2/4 Pulling new images"
run docker compose -f "${COMPOSE_FILE}" pull

log "3/4 Running database migrations"
run docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head

log "4/4 Restarting the stack"
run docker compose -f "${COMPOSE_FILE}" up -d

if [[ "${APPLY}" -eq 1 ]]; then
  log "Update complete. If anything looks wrong, run: scripts/update.sh --rollback --apply"
else
  log "DRY RUN complete (no --apply). Re-run with --apply to perform the update."
fi
