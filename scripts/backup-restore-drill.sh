#!/usr/bin/env bash
#
# Applicant — backup -> destroy volumes -> restore drill (P1-7, issue #659, DoD
# item 3: "A scripted backup -> destroy volumes -> restore drill on the compose
# stack passes clean (app returns whole)").
#
# NEEDS A LIVE COMPOSE STACK. This is deliberately NOT part of the hermetic test
# suite or CI: it runs `docker compose down -v` against whatever stack
# COMPOSE_FILE points at, which is a genuinely destructive operation (it deletes
# the `pgdata`/`ui-data`/etc. named volumes). Run it against a real or
# disposable staging deployment, never against production data you have not
# already backed up some OTHER way too.
#
# What it does, in order:
#   1. scripts/backup.sh --apply           (a fresh full backup, right now)
#   2. docker compose down -v               (DESTROYS every named volume —
#                                            Postgres data, workspace data/,
#                                            fonts, checkpoints, everything)
#   3. docker compose up -d postgres applicant-ui   (fresh, empty volumes)
#   4. scripts/restore.sh --apply --from <the backup step 1 just took>
#   5. docker compose run --rm api uv run alembic upgrade head
#   6. docker compose up -d                 (the full stack)
#   7. Heartbeat: poll the UI's /api/health and the engine's /healthz until
#      both are green (mirrors update.sh's own heartbeat() — "the app returns
#      whole").
#
# Usage:
#   scripts/backup-restore-drill.sh --confirm-destroy   # actually run it
#   scripts/backup-restore-drill.sh                      # dry-run: prints the
#                                                         # plan, touches nothing
#
# Exit 0 only if every step above (including the final heartbeat) succeeded.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
# Overridable (APPLICANT_ENV_FILE), same convention as backup.sh/restore.sh —
# read-only here (just for APP_PORT/etc.), but kept consistent for tests.
ENV_FILE="${APPLICANT_ENV_FILE:-${REPO_ROOT}/.env}"
BACKUP_DIR="${APPLICANT_BACKUP_DIR:-${REPO_ROOT}/.backups}"

CONFIRM=0
for arg in "$@"; do
  case "$arg" in
    --confirm-destroy) CONFIRM=1 ;;
    -h|--help)
      echo "Usage: backup-restore-drill.sh [--confirm-destroy]"
      echo "  Without --confirm-destroy: prints the plan only, runs nothing destructive."
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;31m[drill]\033[0m %s\n' "$*"; }

if [[ -f "${ENV_FILE}" ]]; then
  while IFS='=' read -r _k _v; do
    [[ "${_k}" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    [[ -n "${!_k:-}" ]] || export "${_k}=${_v}"
  done <"${ENV_FILE}"
fi
APP_PORT="${APP_PORT:-8000}"

heartbeat() {
  local tries=60 i
  log "Heartbeat: waiting for the UI on :${APP_PORT}/api/health and the engine /healthz …"
  for ((i = 1; i <= tries; i++)); do
    if curl -fsS -o /dev/null "http://localhost:${APP_PORT}/api/health" 2>/dev/null; then
      if docker compose -f "${COMPOSE_FILE}" exec -T api \
           python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=5).status==200 else 1)" 2>/dev/null; then
        log "The app returns whole: UI /api/health 200 and engine /healthz green."
        return 0
      fi
    fi
    sleep 5
  done
  echo "Heartbeat FAILED after $((tries * 5))s — the app did NOT come back whole." >&2
  docker compose -f "${COMPOSE_FILE}" ps || true
  return 1
}

if [[ "${CONFIRM}" -ne 1 ]]; then
  cat <<PLAN
DRY RUN — the following destructive drill would run against:
  COMPOSE_FILE=${COMPOSE_FILE}
  BACKUP_DIR=${BACKUP_DIR}

  1. scripts/backup.sh --apply
  2. docker compose -f "\${COMPOSE_FILE}" down -v      # DESTROYS all named volumes
  3. docker compose -f "\${COMPOSE_FILE}" up -d postgres applicant-ui
  4. scripts/restore.sh --apply --from <the tarball step 1 produced>
  5. docker compose -f "\${COMPOSE_FILE}" run --rm api uv run alembic upgrade head
  6. docker compose -f "\${COMPOSE_FILE}" up -d
  7. heartbeat: poll /api/health + /healthz until both are green

Re-run with --confirm-destroy to actually perform it. This is DESTRUCTIVE
(step 2 deletes every named volume) — run it against a real/disposable compose
stack you can afford to lose, never blind against production.
PLAN
  exit 0
fi

log "1/7 Taking a fresh full backup"
"${REPO_ROOT}/scripts/backup.sh" --apply
BACKUP_FILE="$(ls -1t "${BACKUP_DIR}"/applicant-full-*.tar.gz 2>/dev/null | head -n1 || true)"
if [[ -z "${BACKUP_FILE}" ]]; then
  echo "Drill FAILED: scripts/backup.sh --apply did not produce a tarball." >&2
  exit 1
fi
log "    backup: ${BACKUP_FILE}"

log "2/7 Destroying all named volumes (docker compose down -v)"
docker compose -f "${COMPOSE_FILE}" down -v

log "3/7 Bringing up fresh, empty postgres + applicant-ui"
docker compose -f "${COMPOSE_FILE}" up -d postgres applicant-ui

log "4/7 Restoring from the backup just taken"
if ! "${REPO_ROOT}/scripts/restore.sh" --apply --from "${BACKUP_FILE}"; then
  echo "Drill FAILED: restore.sh reported an error." >&2
  exit 1
fi

log "5/7 Migrating the restored schema to the code now on disk"
if ! docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head; then
  echo "Drill FAILED: alembic upgrade head failed against the restored database." >&2
  exit 1
fi

log "6/7 Bringing up the full stack"
docker compose -f "${COMPOSE_FILE}" up -d

log "7/7 Verifying the app returns whole"
if [[ "${APPLICANT_SELFTEST:-0}" == "1" ]]; then
  # Mirrors update.sh's own APPLICANT_SELFTEST guard around its live heartbeat:
  # lets the rest of this script's control flow run hermetically under test
  # (fake docker on PATH, no real server to poll) without waiting out a real
  # 5-minute retry loop against nothing.
  log "APPLICANT_SELFTEST=1 — skipping the live heartbeat (unit-test mode)."
elif ! heartbeat; then
  echo "Drill FAILED: the stack did not come back healthy after restore." >&2
  exit 1
fi

log "DRILL PASSED — backup -> destroy volumes -> restore -> migrate -> up came back clean."
