#!/usr/bin/env bash
#
# Applicant — updater sidecar daemon (FR-OOBE-4, NFR-ZEROCLI-1).
#
# The api container can't rebuild the stack (no Docker, and the rebuild restarts
# the api mid-run). This daemon runs in a small sidecar that DOES have the Docker
# socket + the host repo bind-mounted, so it can run the normal one-liner update
# (scripts/update.sh --apply) against the host Docker on demand — and it survives
# the rebuild because the update only recreates the api + applicant-ui services,
# not this updater.
#
# Control plane: a shared volume (UPDATE_CONTROL_DIR, default /control) mounted in
# BOTH this sidecar and the api container:
#   request       - the api drops this; we consume it and run an update.
#   status.json   - we write {state,message,started_at,finished_at}.
#   update.log    - we capture update.sh output here for the UI to tail.
#   updater.alive - we touch this every loop so the api can tell we're deployed.
#
# Idle/dev safe: it does nothing until a request flag appears.
set -uo pipefail

CONTROL_DIR="${UPDATE_CONTROL_DIR:-/control}"
REPO_DIR="${APPLICANT_REPO_DIR_IN_CONTAINER:-/repo}"
UPDATE_SCRIPT="${REPO_DIR}/scripts/update.sh"
POLL_SECONDS="${UPDATER_POLL_SECONDS:-5}"

mkdir -p "${CONTROL_DIR}"

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# write_status STATE MESSAGE STARTED_AT FINISHED_AT  (JSON, single line)
write_status() {
  local state="$1" message="$2" started="${3:-}" finished="${4:-}"
  # Escape the only field that can carry arbitrary text.
  message="${message//\\/\\\\}"; message="${message//\"/\\\"}"
  printf '{"state":"%s","message":"%s","started_at":"%s","finished_at":"%s"}\n' \
    "${state}" "${message}" "${started}" "${finished}" >"${CONTROL_DIR}/status.json"
}

# Seed an idle status on first boot so the UI has something to read.
[[ -f "${CONTROL_DIR}/status.json" ]] || write_status idle "" "" ""

echo "[updater] watching ${CONTROL_DIR} for update requests (repo=${REPO_DIR})" >&2

while true; do
  # Heartbeat: presence + freshness of this file tells the api the updater is live.
  : >"${CONTROL_DIR}/updater.alive"

  if [[ -f "${CONTROL_DIR}/request" ]]; then
    rm -f "${CONTROL_DIR}/request"
    started_at="$(now_utc)"
    if [[ ! -x "/bin/bash" && ! -x "/usr/bin/bash" ]] || [[ ! -f "${UPDATE_SCRIPT}" ]]; then
      write_status failed "Update script not found at ${UPDATE_SCRIPT}." "${started_at}" "$(now_utc)"
    else
      write_status running "Updating Applicant…" "${started_at}" ""
      : >"${CONTROL_DIR}/update.log"
      # Run the normal guarded update against the host Docker. update.sh reads
      # the bind-mounted ${REPO_DIR}/.env for credentials itself.
      if bash "${UPDATE_SCRIPT}" --apply >>"${CONTROL_DIR}/update.log" 2>&1; then
        write_status success "Update complete." "${started_at}" "$(now_utc)"
      else
        write_status failed "Update failed — see the log below." "${started_at}" "$(now_utc)"
      fi
    fi
  fi

  sleep "${POLL_SECONDS}"
done
