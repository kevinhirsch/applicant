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
# The installer builds BOTH images from local source and reads the prod compose
# file relative to its own location, so it needs the repo checked out. When you
# run the one-liner above the script is piped over stdin with no file on disk, so
# it SELF-BOOTSTRAPS: it clones the repo into ./applicant (override APPLICANT_DIR)
# and re-execs itself from inside that checkout. From a checkout it runs in place.
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

# --- 0. Self-bootstrap when piped (curl | bash) -----------------------------
# install.sh builds both images from local source and references the prod compose
# file relative to its own location, so it needs the whole repo on disk. When you
# run the advertised one-liner —
#   bash -c "$(curl -fsSL .../scripts/install.sh)" -- --apply
# — the script is fed to bash over stdin with NO file on disk: BASH_SOURCE is unset
# (so the old `dirname "${BASH_SOURCE[0]}"` tripped `set -u` with "unbound variable"
# and pointed COMPOSE_FILE at a nonexistent /docker/...). Detect that and bootstrap:
# clone the repo (or reuse/update an existing checkout) and re-exec from inside it.
SELF="${BASH_SOURCE[0]:-}"
if [[ -z "${SELF}" || ! -f "${SELF}" ]]; then
  REPO_URL="${APPLICANT_REPO_URL:-https://github.com/kevinhirsch/applicant.git}"
  REPO_BRANCH="${APPLICANT_REPO_BRANCH:-main}"
  CLONE_DIR="${APPLICANT_DIR:-$(pwd)/applicant}"
  printf '\033[1;36m[install]\033[0m %s\n' "Detached run (curl | bash) — bootstrapping a checkout…"
  if ! command -v git >/dev/null 2>&1; then
    echo "git is required to bootstrap the checkout but was not found. Install git first." >&2
    exit 1
  fi
  if [[ -d "${CLONE_DIR}/.git" ]]; then
    printf '\033[1;36m[install]\033[0m %s\n' "Reusing existing checkout at ${CLONE_DIR} (git pull --ff-only)…"
    # Capture the pull result instead of swallowing it with `|| true` (issue #281):
    # `|| true` masked network/auth errors, a non-fast-forward divergence, a detached
    # HEAD, merge conflicts, etc., so the install would silently build from stale or
    # corrupt source. Only the genuinely-benign "Already up to date" outcome is
    # tolerated; any other non-zero pull is surfaced and aborts with a clear message.
    if _pull_out="$(git -C "${CLONE_DIR}" pull --ff-only 2>&1)"; then
      printf '\033[1;36m[install]\033[0m %s\n' "${_pull_out}"
    elif grep -qiE 'already up[ -]to[ -]date' <<<"${_pull_out}"; then
      printf '\033[1;36m[install]\033[0m %s\n' "Checkout already up to date."
    else
      echo "Failed to update the existing checkout at ${CLONE_DIR}:" >&2
      echo "${_pull_out}" >&2
      echo "Resolve it (e.g. 'git -C ${CLONE_DIR} status'), or set APPLICANT_DIR=<free path> for a fresh clone, then re-run." >&2
      exit 1
    fi
  elif [[ -e "${CLONE_DIR}" ]]; then
    echo "${CLONE_DIR} exists but is not an Applicant git checkout. Set APPLICANT_DIR=<free path> and re-run." >&2
    exit 1
  else
    printf '\033[1;36m[install]\033[0m %s\n' "Cloning ${REPO_URL} (${REPO_BRANCH}) into ${CLONE_DIR}…"
    git clone --depth 1 --branch "${REPO_BRANCH}" "${REPO_URL}" "${CLONE_DIR}"
  fi
  printf '\033[1;36m[install]\033[0m %s\n' "Re-executing the installer from ${CLONE_DIR}…"
  exec bash "${CLONE_DIR}/scripts/install.sh" "$@"
fi

REPO_ROOT="$(cd "$(dirname "${SELF}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_ROOT}/.env"
APPLY=0

# Append-only, line-based build output (no redraw frames) so the cloud-init log
# and any `tail`/`tail -f` of it stays readable instead of dumping progress frames.
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"
# Skip the default provenance/SBOM attestations on local builds: they add an
# "exporting attestation manifest" + "manifest list" round to every image export
# (slower, and wraps the image in a manifest list) with no value for a self-hosted
# build that is never published to a registry.
export BUILDX_NO_DEFAULT_ATTESTATIONS="${BUILDX_NO_DEFAULT_ATTESTATIONS:-1}"

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

# --- Credential-regeneration guard (issue #283) -----------------------------
# Postgres bakes its superuser password into the data volume the first time it
# initializes and NEVER changes it on later boots. If an operator deleted .env
# (where we persisted that password) and re-ran the installer, we used to mint a
# brand-new random password while the volume still carried the OLD one — so the
# app could no longer authenticate ("password authentication failed").
#
# Guard it on the ACTUAL volume state, not just `! -f .env`: when we have no
# password (none in the env, none persisted in .env) but a Postgres data volume
# already exists, the database is already initialized — refuse to regenerate
# credentials and tell the operator to restore .env (or opt in explicitly with
# APPLICANT_FORCE_CRED_REGEN=1 after wiping the volume).
if [[ -z "${POSTGRES_PASSWORD:-}" && "${APPLICANT_FORCE_CRED_REGEN:-0}" != "1" ]]; then
  _pg_volume=""
  if command -v docker >/dev/null 2>&1; then
    # Match the project's pgdata volume (compose prefixes it with the project name).
    _pg_volume="$(docker volume ls --quiet 2>/dev/null | grep -E '(^|_)pgdata$' | head -n1 || true)"
  fi
  if [[ -n "${_pg_volume}" ]]; then
    echo "Refusing to regenerate database credentials: the Postgres data volume" >&2
    echo "  '${_pg_volume}' already exists and is already initialized with a password" >&2
    echo "we no longer have (no POSTGRES_PASSWORD in the environment and no ${ENV_FILE})." >&2
    echo "Minting a new password here would break authentication against that volume." >&2
    echo "Restore the original ${ENV_FILE} (or set POSTGRES_PASSWORD to the volume's" >&2
    echo "password). To start over from a clean database, remove the volume and re-run:" >&2
    echo "  docker volume rm ${_pg_volume}    # DESTROYS all data" >&2
    echo "  APPLICANT_FORCE_CRED_REGEN=1 bash scripts/install.sh --apply   # explicit opt-in" >&2
    exit 1
  fi
fi

# --- Editable defaults (override via environment; FR-INSTALL-1) -------------
export POSTGRES_USER="${POSTGRES_USER:-applicant}"
# No weak default password. On first install (none provided and none persisted in
# .env above) GENERATE a strong random one; it is written to .env below and reused by
# every later run/update. The prod compose REQUIRES this be set, so a weak/blank
# fallback is never baked into the Postgres data volume on first init.
if [[ -z "${POSTGRES_PASSWORD:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    POSTGRES_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"
  else
    POSTGRES_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  fi
fi
export POSTGRES_PASSWORD
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
# SearXNG secret_key: substituted into the mounted settings.yml on first boot (the
# searxng service enables ?format=json, which discovery needs). Minted ONCE here and
# persisted to .env (same lifecycle as the credentials above) so the rendered config
# is stable across restarts; the container falls back to its own random one if unset.
if [[ -z "${SEARXNG_SECRET:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    SEARXNG_SECRET="$(openssl rand -hex 32)"
  else
    SEARXNG_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
fi
export SEARXNG_SECRET
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
# A bare Ubuntu/Debian VM has no Docker, which used to abort the one-liner on
# step 1 ("Install Docker first") and leave the operator to do it by hand — the
# opposite of a one-liner. On an apt-based host we now install Docker Engine +
# the Compose v2 plugin via Docker's official convenience script (idempotent;
# it no-ops when Docker is already present), then enable + start the daemon.
# Set APPLICANT_SKIP_DOCKER_INSTALL=1 to opt out (e.g. rootless/hardened hosts).
log "Checking prerequisites (docker, docker compose)…"
_maybe_sudo() { if [[ "$(id -u)" -eq 0 ]]; then "$@"; elif command -v sudo >/dev/null 2>&1; then sudo "$@"; else "$@"; fi; }
if ! command -v docker >/dev/null 2>&1; then
  if [[ "${APPLICANT_SKIP_DOCKER_INSTALL:-0}" != "1" ]] && command -v apt-get >/dev/null 2>&1; then
    log "Docker not found — installing Docker Engine + Compose v2 (get.docker.com)…"
    if ! curl -fsSL https://get.docker.com | _maybe_sudo sh; then
      echo "Automatic Docker install failed. Install Docker Engine + Compose v2 manually, then re-run." >&2
      exit 1
    fi
    # Start the daemon (systemd hosts) so the build/up steps below can reach it.
    _maybe_sudo systemctl enable --now docker >/dev/null 2>&1 || true
  else
    echo "docker is required but not found, and auto-install is unavailable here." >&2
    echo "Install Docker Engine + Compose v2 (https://docs.docker.com/engine/install/), then re-run." >&2
    exit 1
  fi
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker is still not on PATH after install — open a new shell or check the install logs, then re-run." >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "docker compose v2 is required but not found (the Compose plugin did not install)." >&2
  echo "Install it: https://docs.docker.com/compose/install/linux/  then re-run." >&2
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
SEARXNG_SECRET=${SEARXNG_SECRET}
APP_URL=${APP_URL}
APP_PORT=${APP_PORT}
APPLICANT_REPO_DIR=${REPO_ROOT}
EOF
  )
fi

# --- 3. Build the images ----------------------------------------------------
# Build BOTH locally-built images (neither is published to a registry): the
# front-door UI (built from ../workspace) and the engine api.
log "Building the local images (front-door UI + engine api)…"
run docker compose -f "${COMPOSE_FILE}" build applicant-ui api

# --- 4. Migrate the schema BEFORE the api serves ----------------------------
# The engine queries the app_config table AS IT BOOTS (container.py build_container
# → setup_service.build_ladder), so the schema must exist first. Bring up only
# Postgres, then run alembic in a throwaway api container — alembic's env.py imports
# only the model metadata (never the app factory), so it runs cleanly against an
# empty DB. Doing a full `up -d` here instead would crash-loop the api on the missing
# table and, because applicant-ui depends_on api: service_healthy, `up` would ABORT
# ("dependency failed to start") before this migration ever ran. `run --rm api` starts
# Postgres as a dependency and waits for its healthcheck; `alembic upgrade head` is
# idempotent.
log "Starting Postgres and migrating the schema (alembic upgrade head) BEFORE the api serves…"
run docker compose -f "${COMPOSE_FILE}" up -d postgres
run docker compose -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head

# --- 5. Bring up the full stack (api now boots against the migrated schema) --
log "Bringing up the Applicant stack (UI + api + postgres + searxng + chromadb + ntfy, detached)…"
run docker compose -f "${COMPOSE_FILE}" up -d

# --- 6. Heartbeat: don't claim success until the stack is actually green -----
if [[ "${APPLY}" -eq 1 ]]; then
  # APP_PORT was derived from APP_URL and exported above (same value compose published).
  heartbeat "${APP_PORT}" || { echo "Install did not come up healthy — see logs above." >&2; exit 1; }
fi

# --- 7. Done ----------------------------------------------------------------
if [[ "${APPLY}" -eq 1 ]]; then
  log "Install complete. Open the Applicant UI at ${APP_URL} and finish setup in-browser (no CLI, NFR-ZEROCLI-1)."
else
  log "DRY RUN complete (no --apply). Re-run with --apply to provision the stack."
fi
