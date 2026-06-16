#!/usr/bin/env bash
#
# Applicant — one-liner installer (FR-INSTALL-1/3, NFR-ZEROCLI-1).
#
# Proxmox-helper-script style: a single curl-pipe-bash bootstrap that provisions
# the whole Docker Compose stack (api + postgres + searxng) with sane, EDITABLE
# defaults and zero CLI knowledge required. Typical usage:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/<org>/applicant/main/scripts/install.sh)" -- --apply
#
# What --apply does (idempotent — safe to re-run; data volumes are never deleted):
#   1. Preflight: require docker + docker compose v2.
#   2. Validate the production compose file.
#   3. Bring up Postgres + SearXNG + the API (detached).
#   4. Wait for Postgres to be healthy, then run Alembic migrations.
#   5. Print where the app is reachable; OOBE finishes setup in-browser (no CLI).
#
# VM / host path (FR-INSTALL-1): on a fresh Proxmox VM or bare host, set the
# editable defaults below via the environment before running, e.g.:
#   POSTGRES_PASSWORD=... APP_PORT=8000 bash scripts/install.sh --apply
#
# SAFETY: default mode is a DRY RUN — it validates the environment and PRINTS the
# steps it would run. Pass --apply to actually run them. Nothing is deleted.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
APPLY=0

# --- Editable defaults (override via environment; FR-INSTALL-1) -------------
export POSTGRES_USER="${POSTGRES_USER:-applicant}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-applicant}"
export POSTGRES_DB="${POSTGRES_DB:-applicant}"
APP_URL="${APP_URL:-http://localhost:8000}"

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      echo "Usage: install.sh [--apply]"
      echo "  (default: dry-run — prints steps; --apply runs them)"
      echo "  Editable env defaults: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, APP_URL"
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
run() {
  if [[ "${APPLY}" -eq 1 ]]; then "$@"; else echo "    (would run) $*"; fi
}

# --- 1. Preflight: required tooling ----------------------------------------
log "Checking prerequisites (docker, docker compose)…"
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not found. Install Docker first." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose v2 is required but not found." >&2
  exit 1
fi

# --- 2. Validate the production compose file --------------------------------
log "Validating compose file: ${COMPOSE_FILE}"
docker compose -f "${COMPOSE_FILE}" config >/dev/null

# --- 3. Bring up the stack --------------------------------------------------
log "Bringing up the Applicant stack (postgres + searxng + api, detached)…"
run docker compose -f "${COMPOSE_FILE}" up -d

# --- 4. Run database migrations (after Postgres is healthy) -----------------
# Postgres has a healthcheck + the api depends_on service_healthy, so by the time
# we run this the DB is reachable. `alembic upgrade head` is idempotent.
log "Running database migrations (alembic upgrade head)…"
run docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head

# --- 5. Done ----------------------------------------------------------------
if [[ "${APPLY}" -eq 1 ]]; then
  log "Install complete. Open ${APP_URL} and finish the OOBE wizard (no CLI, NFR-ZEROCLI-1)."
else
  log "DRY RUN complete (no --apply). Re-run with --apply to provision the stack."
fi
