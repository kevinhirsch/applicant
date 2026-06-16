#!/usr/bin/env bash
#
# Applicant — one-liner installer (FR-INSTALL-1/3, NFR-ZEROCLI-1).
#
# Proxmox-helper-script style: a single curl-pipe-bash bootstrap that brings up
# the Docker Compose stack (api + postgres + searxng) with sane defaults and zero
# CLI knowledge required. Typical usage (documented for the operator):
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/<org>/applicant/main/scripts/install.sh)"
#
# SAFETY: this is a WELL-COMMENTED SCAFFOLD STUB. It performs NO destructive
# operations by default. It validates the environment and PRINTS the steps it
# would run; pass --apply to actually bring the stack up. Nothing is deleted, and
# existing data volumes are never touched.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${REPO_ROOT}/docker/docker-compose.prod.yml"
APPLY=0

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    -h|--help)
      echo "Usage: install.sh [--apply]"
      echo "  (default: dry-run — prints steps; --apply runs them)"
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log() { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }

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
if [[ "${APPLY}" -eq 1 ]]; then
  log "Starting the Applicant stack (detached)…"
  docker compose -f "${COMPOSE_FILE}" up -d
  log "Stack started. The app will be reachable on http://localhost:8000"
  log "Next: open the app and complete the OOBE wizard (no CLI needed, NFR-ZEROCLI-1)."
else
  log "DRY RUN (no --apply). Would run:"
  echo "    docker compose -f ${COMPOSE_FILE} up -d"
  log "Re-run with --apply to start the stack."
fi
