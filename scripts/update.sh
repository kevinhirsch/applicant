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
ENV_FILE="${REPO_ROOT}/.env"
BACKUP_DIR="${APPLICANT_BACKUP_DIR:-${REPO_ROOT}/.backups}"

# Append-only, line-based build output (no redraw frames) so update logs stay readable.
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"

# Load persisted DB credentials so backup/migrate/restart authenticate with the
# SAME password Postgres baked into its data volume at first install. Without this
# the migration step fails ("password authentication failed"). Explicit env wins.
if [[ -f "${ENV_FILE}" ]]; then
  while IFS='=' read -r _k _v; do
    [[ "${_k}" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    [[ -n "${!_k:-}" ]] || export "${_k}=${_v}"
  done <"${ENV_FILE}"
fi

DB_SERVICE="postgres"
DB_NAME="${POSTGRES_DB:-applicant}"
DB_USER="${POSTGRES_USER:-applicant}"
# set -u safe default; .env (sourced above) overrides it. Used by the heartbeat.
APP_URL="${APP_URL:-http://localhost:8000}"
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

# Heartbeat: block until the front-door UI answers /api/health on the public
# port, then confirm the internal engine's /healthz. Non-zero if never green.
heartbeat() {
  local port="$1" tries=60 i
  log "Heartbeat: waiting for the UI on :${port}/api/health …"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS -o /dev/null "http://localhost:${port}/api/health" 2>/dev/null; then
      log "UI is up (/api/health 200)."
      if docker compose -f "${COMPOSE_FILE}" exec -T api \
           python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=5).status==200 else 1)" 2>/dev/null; then
        log "Engine is healthy (/healthz). Stack is green."
      else
        log "Engine /healthz not green yet (UI is up); check: docker compose -f ${COMPOSE_FILE} ps"
      fi
      return 0
    fi
    sleep 5
  done
  echo "Heartbeat FAILED: UI did not become healthy on :${port} after $((tries * 5))s." >&2
  docker compose -f "${COMPOSE_FILE}" ps || true
  return 1
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
  # Feed the dump to the container's psql over STDIN (host-side redirect). Do NOT
  # use `psql -f "${LATEST}"`: -f opens the file INSIDE the postgres container,
  # where this host path does not exist, so the restore would fail with "No such
  # file or directory". The backup is written host-side via `pg_dump > file`, so
  # the restore must read it host-side and pipe it in the same way.
  if [[ "${APPLY}" -eq 1 ]]; then
    docker compose -f "${COMPOSE_FILE}" exec -T "${DB_SERVICE}" \
      psql -U "${DB_USER}" -d "${DB_NAME}" <"${LATEST}"
  else
    echo "    (would run) docker compose -f ${COMPOSE_FILE} exec -T ${DB_SERVICE} psql -U ${DB_USER} -d ${DB_NAME} <${LATEST}"
  fi
  log "Rollback complete (or dry-run printed above)."
  exit 0
fi

# --- update path ------------------------------------------------------------
log "Update flow (sync code → backup → build → migrate → restart)."
run mkdir -p "${BACKUP_DIR}"
# Belt-and-suspenders: the default BACKUP_DIR lives inside the repo, and the dumps
# contain ALL user data. Drop a `*`-ignore so a stray `git add -A` can never commit
# a database dump even if the repo-root .gitignore lacks a .backups/ entry.
if [[ "${APPLY}" -eq 1 && ! -e "${BACKUP_DIR}/.gitignore" ]]; then
  ( umask 077; printf '*\n' >"${BACKUP_DIR}/.gitignore" )
fi

# --- 0/5 Sync the source checkout -------------------------------------------
# The whole point of an "update" is to run NEW code. The api image is built from
# this local checkout (pull_policy: build), so without syncing git first every
# rebuild just reproduces the old image. Fetch + hard-reset to the tracked branch
# (the deploy tree is not edited by hand). .env / .backups are untracked/ignored
# and survive the reset.
APPLICANT_BRANCH="${APPLICANT_BRANCH:-main}"
# APPLICANT_SELFTEST=1 skips the destructive git reset (set by the test suite so a
# unit test can never hard-reset the working tree to origin/main).
if [[ "${APPLICANT_SELFTEST:-0}" != "1" && -d "${REPO_ROOT}/.git" ]]; then
  log "0/5 Syncing source to origin/${APPLICANT_BRANCH}"
  run git -C "${REPO_ROOT}" fetch origin "${APPLICANT_BRANCH}"
  run git -C "${REPO_ROOT}" reset --hard "origin/${APPLICANT_BRANCH}"
else
  log "0/5 No git checkout at ${REPO_ROOT}; skipping source sync."
fi

log "1/5 Backing up the database to ${DUMP_FILE}"
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

log "2/5 Pulling base images + rebuilding local images (front-door UI + engine api) from synced source"
run docker compose -f "${COMPOSE_FILE}" pull --ignore-buildable
run docker compose -f "${COMPOSE_FILE}" build applicant-ui api

log "3/5 Running database migrations"
run docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head

log "4/5 Restarting the stack on the freshly built image"
run docker compose -f "${COMPOSE_FILE}" up -d --build

log "5/5 Update applied."

# Heartbeat: verify the stack came back green before declaring success; if not,
# point the operator at rollback.
if [[ "${APPLY}" -eq 1 && "${APPLICANT_SELFTEST:-0}" != "1" ]]; then
  # Prefer APP_PORT from .env (the value compose publishes); else derive from APP_URL.
  APP_PORT="${APP_PORT:-${APP_URL##*:}}"; [[ "${APP_PORT}" =~ ^[0-9]+$ ]] || APP_PORT=8000
  if ! heartbeat "${APP_PORT}"; then
    echo "Update did not come up healthy. Roll back with: scripts/update.sh --rollback --apply" >&2
    exit 1
  fi
fi

if [[ "${APPLY}" -eq 1 ]]; then
  log "Update complete. If anything looks wrong, run: scripts/update.sh --rollback --apply"
else
  log "DRY RUN complete (no --apply). Re-run with --apply to perform the update."
fi
