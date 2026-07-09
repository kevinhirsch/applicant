#!/usr/bin/env bash
#
# Applicant — redacted diagnostic bundle (P5-1, "Support machinery").
#
# Collects a single shareable archive for a bug report or a support request:
# version info, compose service status, a SANITIZED copy of the deploy config,
# recent per-service logs, and health-endpoint output. Every secret-bearing
# value is redacted BY THIS SCRIPT (via scripts/lib/diagnostic_redact.py)
# before anything is written to disk or archived — there is no flag to skip
# redaction; it is never caller-controlled (CLAUDE.md principle #5-server).
#
# Read-only. Nothing here is destructive (unlike backup.sh/update.sh), so
# there is no --apply gate — safe to run any time.
#
# Usage:
#   scripts/diagnostic-bundle.sh [--output PATH]
#
# What lands in the archive (see its own MANIFEST.txt for exactly what was
# collected vs. skipped on THIS run, and why — an absent docker socket or an
# unreachable stack is reported honestly, never silently omitted):
#   version.txt          git commit/describe + docker/compose versions
#   compose-ps.txt        `docker compose ps` (service name/state/health only)
#   env-sanitized.txt      the deploy .env with every secret-bearing key's
#                          VALUE redacted (key names are kept, so support can
#                          still see WHICH knobs are set) + a value-pattern
#                          scrub as defense-in-depth on every remaining value
#   logs/<service>.log     last N lines per compose service, secret-scrubbed
#   health.txt              GET /api/health output if the stack is reachable
#   MANIFEST.txt            exactly what was collected vs skipped, and why
#
# This needs to run on the DEPLOY HOST (docker compose / the .env file live
# there) — it is not reachable from inside the `api`/`applicant-ui` containers,
# which have no Docker socket. Settings -> System in the front-door surfaces
# this same command for anyone who prefers to copy it from the UI.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${APPLICANT_DIAG_COMPOSE_FILE:-${REPO_ROOT}/docker/docker-compose.prod.yml}"
# Overridable, mirroring backup.sh's own ENV_FILE/BACKUP_DIR conventions, so
# tests can point this at scratch paths instead of ever touching a real .env
# or the real compose file (a docker binary MAY be present on the runner even
# with no reachable daemon/stack -- pointing COMPOSE_FILE at a scratch/missing
# path is what deterministically exercises the "docker unavailable" honest-skip
# path, not a PATH-manipulation trick that a docker-in-/usr/bin install defeats).
ENV_FILE="${APPLICANT_ENV_FILE:-${REPO_ROOT}/.env}"
OUTPUT_DIR="${APPLICANT_DIAG_DIR:-${REPO_ROOT}/.diagnostics}"
LOG_TAIL_LINES="${APPLICANT_DIAG_LOG_LINES:-200}"

# shellcheck source=lib/backup-common.sh
source "${REPO_ROOT}/scripts/lib/backup-common.sh"

REDACT_CMD=(python3 "${REPO_ROOT}/scripts/lib/diagnostic_redact.py")

SERVICES=(applicant-ui api postgres searxng chromadb ntfy)

OUTPUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output)
      OUTPUT="$2"
      shift 2
      ;;
    -h|--help)
      echo "Usage: diagnostic-bundle.sh [--output PATH]"
      echo "  Collects a redacted diagnostic archive (version, compose status,"
      echo "  sanitized config, scrubbed logs, health) for a bug report or"
      echo "  support request. Safe to run any time -- read-only."
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

TS="$(date -u +%Y%m%dT%H%M%SZ)"
WORKDIR="$(mktemp -d)"
trap 'rm -rf "${WORKDIR}"' EXIT
BUNDLE_NAME="diagnostic-bundle-${TS}"
BUNDLE_DIR="${WORKDIR}/${BUNDLE_NAME}"
mkdir -p "${BUNDLE_DIR}/logs"

MANIFEST="${BUNDLE_DIR}/MANIFEST.txt"
: > "${MANIFEST}"
_note() { printf '%s\n' "$1" >> "${MANIFEST}"; }

_note "Applicant diagnostic bundle -- generated ${TS} (UTC)"
_note "Every secret-bearing value below has been redacted by this script."
_note "Skim it yourself before attaching it to a public issue or message anyway."
_note ""

# -- version -------------------------------------------------------------------
{
  echo "generated_at: ${TS}"
  if command -v git >/dev/null 2>&1 && git -C "${REPO_ROOT}" rev-parse HEAD >/dev/null 2>&1; then
    echo "git_commit: $(git -C "${REPO_ROOT}" rev-parse HEAD)"
    echo "git_describe: $(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo unknown)"
  else
    echo "git_commit: unavailable (not a git checkout, or git not installed)"
  fi
  if command -v docker >/dev/null 2>&1; then
    echo "docker_version: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unavailable)"
    echo "compose_version: $(docker compose version 2>/dev/null || echo unavailable)"
  else
    echo "docker: not found on PATH"
  fi
} > "${BUNDLE_DIR}/version.txt"
_note "version.txt: collected"

# -- compose service status + which services exist on this compose file --------
HAVE_DOCKER=0
AVAILABLE_SERVICES=""
if command -v docker >/dev/null 2>&1 && [[ -f "${COMPOSE_FILE}" ]]; then
  HAVE_DOCKER=1
  if docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" ps \
      > "${BUNDLE_DIR}/compose-ps.txt" 2>&1; then
    _note "compose-ps.txt: collected"
  else
    _note "compose-ps.txt: SKIPPED -- \`docker compose ps\` failed (stack not running?)"
  fi
  AVAILABLE_SERVICES="$(docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" config --services 2>/dev/null || true)"
else
  _note "compose-ps.txt: SKIPPED -- docker not on PATH or compose file not found (run this on the deploy host)"
fi

# -- sanitized config ------------------------------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
  "${REDACT_CMD[@]}" < "${ENV_FILE}" > "${BUNDLE_DIR}/env-sanitized.txt"
  _note "env-sanitized.txt: collected (every secret-bearing key's VALUE redacted; key names kept)"
else
  _note "env-sanitized.txt: SKIPPED -- no .env file at ${ENV_FILE}"
fi

# -- per-service logs --------------------------------------------------------------
if [[ "${HAVE_DOCKER}" -eq 1 ]]; then
  for svc in "${SERVICES[@]}"; do
    if printf '%s\n' "${AVAILABLE_SERVICES}" | grep -qx "${svc}"; then
      if docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" logs --no-color --tail "${LOG_TAIL_LINES}" "${svc}" 2>&1 \
          | "${REDACT_CMD[@]}" > "${BUNDLE_DIR}/logs/${svc}.log"; then
        _note "logs/${svc}.log: collected (last ${LOG_TAIL_LINES} lines, secret-scrubbed)"
      else
        rm -f "${BUNDLE_DIR}/logs/${svc}.log"
        _note "logs/${svc}.log: SKIPPED -- \`docker compose logs\` failed for this service"
      fi
    else
      _note "logs/${svc}.log: SKIPPED -- service not defined in this compose file"
    fi
  done
else
  _note "logs/: SKIPPED -- docker not on PATH or compose file not found"
fi

# -- health endpoint (best-effort; the front-door's own health, not the internal engine) --
bkup_load_env "${ENV_FILE}"
HEALTH_URL="${APP_URL:-http://localhost:${APP_PORT:-8000}}/api/health"
if command -v curl >/dev/null 2>&1; then
  {
    echo "--- GET ${HEALTH_URL} ---"
    curl -fsS --max-time 5 "${HEALTH_URL}" 2>&1 || echo "(unreachable)"
  } | "${REDACT_CMD[@]}" > "${BUNDLE_DIR}/health.txt"
  _note "health.txt: collected (best-effort -- '(unreachable)' if the stack isn't up)"
else
  _note "health.txt: SKIPPED -- curl not on PATH"
fi

# -- package -----------------------------------------------------------------------
mkdir -p "${OUTPUT_DIR}"
ARCHIVE="${OUTPUT:-${OUTPUT_DIR}/applicant-diagnostic-${TS}.tar.gz}"
mkdir -p "$(dirname "${ARCHIVE}")"
( umask 077; tar -czf "${ARCHIVE}" -C "${WORKDIR}" "${BUNDLE_NAME}" )

echo "Diagnostic bundle written to: ${ARCHIVE}"
echo "Every value has been redacted before being written -- but please skim it"
echo "yourself before attaching it to a public issue or support message."
