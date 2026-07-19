#!/usr/bin/env bash
#
# Applicant — diagnostic bundle (lightweight).
#
# Collects system info into a timestamped .tar.gz archive.
# - Docker Compose version & config (sanitized)
# - Container logs (last 200 lines each)
# - Disk usage (df -h)
# - System info (uname -a, free -m)
#
# Secrets are redacted where possible. A note about redacting secrets
# is included in the manifest.
#
# Usage:
#   scripts/diag.sh [--output|-o PATH]
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${APPLICANT_DIAG_COMPOSE_FILE:-${REPO_ROOT}/docker/docker-compose.prod.yml}"
ENV_FILE="${APPLICANT_ENV_FILE:-${REPO_ROOT}/.env}"
OUTPUT="${1:-}"

# Parse --output / -o flag
while [[ $# -gt 0 ]]; do
  case "$1" in
    --output|-o) OUTPUT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
BUNDLE_DIR=$(mktemp -d "${REPO_ROOT}/.diagnostics-XXXXXX")
mkdir -p "${BUNDLE_DIR}/logs"

# Cleanup on exit (remove temp dir if archive not yet written)
cleanup() {
  local exit_code=$?
  if [[ ! -f "${OUTPUT:-}" ]]; then
    rm -rf "${BUNDLE_DIR}"
  fi
  exit $exit_code
}
trap cleanup EXIT

# Helper: append to manifest
_note() {
  echo "- $1" >> "${BUNDLE_DIR}/MANIFEST.txt"
}

echo "MANIFEST — Applicant Diagnostic Bundle ${TIMESTAMP}" > "${BUNDLE_DIR}/MANIFEST.txt"
echo "" >> "${BUNDLE_DIR}/MANIFEST.txt"
echo "Collected items:" >> "${BUNDLE_DIR}/MANIFEST.txt"
echo "" >> "${BUNDLE_DIR}/MANIFEST.txt"

# -- Version info -----------------------------------------------------------
{
  echo "=== Version Info ==="
  if command -v git >/dev/null 2>&1 && git -C "${REPO_ROOT}" rev-parse HEAD >/dev/null 2>&1; then
    echo "Git commit: $(git -C "${REPO_ROOT}" rev-parse --short HEAD)"
    echo "Git describe: $(git -C "${REPO_ROOT}" describe --tags --always 2>/dev/null || echo unknown)"
  else
    echo "Git: unavailable"
  fi
  if command -v docker >/dev/null 2>&1; then
    echo "Docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unavailable)"
    echo "Compose: $(docker compose version 2>/dev/null || echo unavailable)"
  else
    echo "Docker: not found on PATH"
  fi
} > "${BUNDLE_DIR}/version.txt" 2>&1
_note "version.txt: collected (git + docker/compose versions)"

# -- Docker Compose config (sanitized) --------------------------------------
if [[ -f "${COMPOSE_FILE}" ]]; then
  if [[ -f "${ENV_FILE}" ]]; then
    # Sanitize: replace values of common secret keys
    sed -E 's/(APP_PORT|APP_URL|DB_.*|API_KEY|API_SECRET|SECRET|PASSWORD|PASSWORD|TOKEN)=([^,\n]*)/\1=\"\"/g' "${COMPOSE_FILE}" > "${BUNDLE_DIR}/compose-config.txt" 2>/dev/null || cp "${COMPOSE_FILE}" "${BUNDLE_DIR}/compose-config.txt"
    _note "compose-config.txt: collected (sanitized — secret key values redacted)"
  else
    cp "${COMPOSE_FILE}" "${BUNDLE_DIR}/compose-config.txt"
    _note "compose-config.txt: collected (no .env to cross-reference; raw copy)"
  fi
else
  _note "compose-config.txt: SKIPPED — compose file not found at ${COMPOSE_FILE}"
fi

# -- Container logs (last 200 lines each) -----------------------------------
if command -v docker >/dev/null 2>&1 && [[ -f "${COMPOSE_FILE}" ]]; then
  SERVICES=$(docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" config --services 2>/dev/null || true)
  for svc in ${SERVICES}; do
    if docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" logs --no-color --tail 200 "${svc}" 2>&1 | sed 's/"$([\"\\])/\"/g' > "${BUNDLE_DIR}/logs/${svc}.log" 2>/dev/null; then
      _note "logs/${svc}.log: collected (last 200 lines)"
    else
      rm -f "${BUNDLE_DIR}/logs/${svc}.log"
      _note "logs/${svc}.log: SKIPPED — docker compose logs failed for this service"
    fi
  done
  if [[ -z "${SERVICES}" ]]; then
    _note "logs/: SKIPPED — no services found in compose config (stack may not be running)"
  fi
else
  _note "logs/: SKIPPED — docker not available or compose file not found"
fi

# -- Disk usage -------------------------------------------------------------
{
  echo "=== Disk Usage ==="
  df -h 2>/dev/null || echo "df -h: unavailable"
} > "${BUNDLE_DIR}/disk-usage.txt" 2>&1
_note "disk-usage.txt: collected (df -h)"

# -- System info ------------------------------------------------------------
{
  echo "=== System Info ==="
  echo "uname -a: $(uname -a 2>/dev/null || echo unavailable)"
  echo ""
  echo "free -m:"
  free -m 2>/dev/null || echo "free -m: unavailable"
} > "${BUNDLE_DIR}/system-info.txt" 2>&1
_note "system-info.txt: collected (uname -a, free -m)"

# -- Secret redaction note --------------------------------------------------
echo "" >> "${BUNDLE_DIR}/MANIFEST.txt"
echo "Note: Secret values (API keys, passwords, tokens, database credentials) are redacted" >> "${BUNDLE_DIR}/MANIFEST.txt"
echo "where possible. For a fully sanitized bundle, also run scripts/diagnostic-bundle.sh." >> "${BUNDLE_DIR}/MANIFEST.txt"

# -- Create archive ---------------------------------------------------------
if [[ -n "${OUTPUT}" ]]; then
  ARCHIVE_PATH="${OUTPUT}"
else
  ARCHIVE_PATH="${REPO_ROOT}/.diagnostics/applicant-diag-${TIMESTAMP}.tar.gz"
  mkdir -p "${REPO_ROOT}/.diagnostics"
fi

tar -czf "${ARCHIVE_PATH}" -C "${BUNDLE_DIR}" . 2>/dev/null
rm -rf "${BUNDLE_DIR}"

# Disable trap since we cleaned up manually
trap - EXIT

echo "Diagnostic bundle written to: ${ARCHIVE_PATH}"
echo "Contents: version.txt, compose-config.txt, logs/*, disk-usage.txt, system-info.txt, MANIFEST.txt"
