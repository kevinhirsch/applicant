#!/usr/bin/env bash
#
# Applicant — one-liner installer (FR-INSTALL-1/3, NFR-ZEROCLI-1).
#
# Proxmox-helper-script style: a single curl-pipe-bash bootstrap that provisions
# the whole Docker Compose stack (front-door UI + engine api + postgres + searxng
# + chromadb + ntfy) with sane, EDITABLE defaults and zero CLI knowledge required.
# The user opens the front-door UI on ${APP_PORT}; the engine api is internal.
# Typical usage:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/install.sh)" -- --apply
#
# What --apply does (idempotent — safe to re-run; data volumes are never deleted):
#   1. Preflight: require docker + docker compose v2.
#   2. Validate the production compose file.
#   3. Bring up the stack (front-door UI + api + postgres + searxng + chromadb
#      + ntfy, detached).
#   4. Wait for Postgres to be healthy, then run the engine's Alembic migrations.
#   5. Print where the UI is reachable; OOBE finishes setup in-browser (no CLI).
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
ENV_FILE="${REPO_ROOT}/.env"
APPLY=0

# Append-only, line-based build output (no redraw frames) so the cloud-init log
# and any `tail`/`tail -f` of it stays readable instead of dumping progress frames.
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"

# --- Persisted settings: load any saved .env FIRST so re-runs and updates reuse
# the SAME database password. Postgres bakes its password into the data volume on
# first init; if a later run fell back to a different default the app could no
# longer authenticate. Explicit environment variables still win over the file.
if [[ -f "${ENV_FILE}" ]]; then
  while IFS='=' read -r _k _v; do
    [[ "${_k}" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue   # skip blanks/comments
    # Only adopt a saved value when the variable isn't already set in the env.
    [[ -n "${!_k:-}" ]] || export "${_k}=${_v}"
  done <"${ENV_FILE}"
fi

# --- Editable defaults (override via environment; FR-INSTALL-1) -------------
export POSTGRES_USER="${POSTGRES_USER:-applicant}"
export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-applicant}"
export POSTGRES_DB="${POSTGRES_DB:-applicant}"
# Stage-2.5 reverse channel: the SHARED secret that authenticates the engine's
# callbacks into the front-door UI's /api/applicant/internal/* routes. Generated
# ONCE here and persisted to .env (same lifecycle as POSTGRES_PASSWORD) so BOTH
# containers (api + applicant-ui) read the same value. The loaded .env above
# already populated it on re-runs, so this only mints one on first install.
if [[ -z "${APPLICANT_INTERNAL_TOKEN:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    APPLICANT_INTERNAL_TOKEN="$(openssl rand -hex 32)"
  else
    APPLICANT_INTERNAL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
fi
export APPLICANT_INTERNAL_TOKEN
APP_URL="${APP_URL:-http://localhost:8000}"
# The compose file publishes the front door on ${APP_PORT:-8000}. Derive APP_PORT
# from APP_URL (unless explicitly set) and EXPORT it so the host port compose
# publishes, the heartbeat target below, and the persisted .env all agree — without
# this a custom APP_URL port would be polled while compose still published 8000.
if [[ -z "${APP_PORT:-}" ]]; then APP_PORT="${APP_URL##*:}"; fi
[[ "${APP_PORT}" =~ ^[0-9]+$ ]] || APP_PORT=8000
export APP_PORT

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

# Heartbeat: block until the front-door UI answers /api/health on the public
# port, then confirm the internal engine's /healthz. Returns non-zero if the
# stack never goes green so the caller can fail loudly instead of claiming success.
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

# --- 2b. Persist the DB credentials so every later run/update reuses them ----
# Write the .env ONCE (first apply). This is what keeps `update.sh` authenticating
# against the password Postgres baked into its volume at first init.
if [[ "${APPLY}" -eq 1 && ! -f "${ENV_FILE}" ]]; then
  log "Persisting database credentials to ${ENV_FILE} (re-used by every update)…"
  ( umask 077; cat >"${ENV_FILE}" <<EOF
POSTGRES_USER=${POSTGRES_USER}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=${POSTGRES_DB}
APPLICANT_INTERNAL_TOKEN=${APPLICANT_INTERNAL_TOKEN}
APP_URL=${APP_URL}
APP_PORT=${APP_PORT}
EOF
  )
fi

# --- 3. Bring up the stack --------------------------------------------------
# Build BOTH locally-built images (neither is published to a registry): the
# front-door UI (built from ../workspace) and the engine api.
log "Building the local images (front-door UI + engine api)…"
run docker compose -f "${COMPOSE_FILE}" build applicant-ui api

log "Bringing up the Applicant stack (UI + api + postgres + searxng + chromadb + ntfy, detached)…"
run docker compose -f "${COMPOSE_FILE}" up -d --build

# --- 4. Run database migrations (after Postgres is healthy) -----------------
# Postgres has a healthcheck + the api depends_on service_healthy, so by the time
# we run this the DB is reachable. `alembic upgrade head` is idempotent.
log "Running database migrations (alembic upgrade head)…"
run docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head

# --- 5. Heartbeat: don't claim success until the stack is actually green -----
if [[ "${APPLY}" -eq 1 ]]; then
  # APP_PORT was derived from APP_URL and exported above (same value compose published).
  heartbeat "${APP_PORT}" || { echo "Install did not come up healthy — see logs above." >&2; exit 1; }
fi

# --- 6. Done ----------------------------------------------------------------
if [[ "${APPLY}" -eq 1 ]]; then
  log "Install complete. Open the Applicant UI at ${APP_URL} and finish setup in-browser (no CLI, NFR-ZEROCLI-1)."
else
  log "DRY RUN complete (no --apply). Re-run with --apply to provision the stack."
fi
