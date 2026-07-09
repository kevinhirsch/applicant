#!/usr/bin/env bash
# =============================================================================
# setup-integration-runner.sh — one-command provisioning for a self-hosted
# GitHub Actions runner that runs the Applicant Integration Lane
# (.github/workflows/ci-integration.yml).
#
# WHAT IT DOES
#   Pre-bakes everything the Integration Lane's "Verify ..." steps require on a
#   fresh runner host, so onboarding a new runner is one command instead of a
#   pile of manual apt/usermod pastes:
#     * Docker without sudo — adds the GitHub Actions runner's service user to
#       the `docker` group and restarts the runner service (the "K9" fix) so the
#       lane's `docker version` / postgres service container works without sudo.
#     * TeX Live (lualatex/xelatex + moderncv/fontspec/fontawesome5 + fonts) for
#       the FR-RESUME-3/4 real-render path (P2-10 LaTeX leg).
#     * LibreOffice Writer for the P2-10 docx-fallback render path.
#     * Xvfb for the FR-PREFILL/FR-STEALTH browser tests' virtual X display.
#     * (Best-effort) warms the TeX font cache once so the first real render in
#       the timed integration suite does not hit a cold-cache pytest-timeout.
#
# REQUIREMENTS
#   Must be run as root (or via sudo) — it installs system packages, edits group
#   membership, and restarts a systemd service.
#
# IDEMPOTENT
#   Safe to re-run any number of times: `apt-get install` and `usermod -aG` are
#   both no-ops when already satisfied, and the verify block only reports state.
#
# USAGE
#   sudo bash scripts/setup-integration-runner.sh
#
# See docs/integration-runner-setup.md for the full onboarding procedure, how
# the runner user is detected, the manual-fallback commands, and the checklist.
# =============================================================================
set -euo pipefail

log()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN:\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31mERROR:\033[0m %s\n' "$*" >&2; }

# --- 1. Require root ---------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
  err "This script must run as root — it installs packages and edits group membership."
  err "Re-run it with sudo:"
  err "    sudo bash scripts/setup-integration-runner.sh"
  exit 1
fi

# --- 2. Detect the GitHub Actions runner service + its user ------------------
# The lane needs Docker WITHOUT sudo. Adding the runner's service user to the
# `docker` group only takes effect on the NEXT start of the runner service, so
# we detect the unit, add the user, and restart the service below.
log "Detecting the GitHub Actions runner service..."
SVC=""
# Prefer a loaded/active unit; fall back to the installed unit file.
SVC="$(systemctl list-units --type=service --all --no-legend 'actions.runner.*' 2>/dev/null \
        | awk '{print $1}' | grep -E '^actions\.runner\..*\.service$' | head -1 || true)"
if [ -z "$SVC" ]; then
  SVC="$(systemctl list-unit-files --no-legend 'actions.runner.*.service' 2>/dev/null \
          | awk '{print $1}' | grep -E '^actions\.runner\..*\.service$' | head -1 || true)"
fi

RUNNER_USER=""
if [ -n "$SVC" ]; then
  log "Found runner service: ${SVC}"
  RUNNER_USER="$(systemctl show -p User --value "$SVC" 2>/dev/null || true)"
else
  warn "No 'actions.runner.*' systemd service found."
fi

# Fall back to the owner of the running Runner.Listener process if the unit did
# not declare a User= (or no unit was found). On ubnthost01 this user is `actions`.
if [ -z "$RUNNER_USER" ]; then
  RUNNER_USER="$(ps -o user= -C Runner.Listener 2>/dev/null | head -1 | tr -d '[:space:]' || true)"
fi

if [ -z "$RUNNER_USER" ]; then
  warn "Could not determine the runner service user (no systemd User= and no Runner.Listener process)."
  warn "The Docker-without-sudo group fix will be SKIPPED. If the runner is not up yet,"
  warn "re-run this script after the runner is registered and started, or add the user manually:"
  warn "    sudo usermod -aG docker <runner-user> && sudo systemctl restart '<actions.runner...service>'"
else
  log "Runner service user: ${RUNNER_USER}"
fi

# --- 3. Install system dependencies -----------------------------------------
# Each package group maps to exactly which Integration-Lane prerequisite it
# satisfies (echoed so an admin can see WHY each is installed).
log "Installing system dependencies (apt-get)..."
echo "  texlive-* + fonts-open-sans/fonts-font-awesome -> FR-RESUME-3/4 LaTeX real-render path (P2-10)"
echo "  libreoffice-writer                              -> P2-10 docx-fallback render path (soffice --convert-to pdf)"
echo "  xvfb                                            -> FR-PREFILL/FR-STEALTH browser tests need a virtual X display"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  texlive-latex-extra \
  texlive-fonts-recommended \
  texlive-fonts-extra \
  texlive-luatex \
  texlive-xetex \
  fonts-open-sans \
  fonts-font-awesome \
  libreoffice-writer \
  xvfb

# --- 4. Docker-without-sudo (K9): group + runner restart ---------------------
# Ensure the `docker` group exists (it normally does after a docker install),
# then add the runner user to it. usermod -aG is idempotent.
if [ -n "$RUNNER_USER" ]; then
  log "Granting Docker socket access to '${RUNNER_USER}' (K9 fix)..."
  if ! getent group docker >/dev/null 2>&1; then
    warn "The 'docker' group does not exist yet — creating it. Install Docker Engine so the socket exists."
    groupadd docker
  fi
  if id -nG "$RUNNER_USER" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
    log "'${RUNNER_USER}' is already in the 'docker' group (no change)."
  else
    usermod -aG docker "$RUNNER_USER"
    log "Added '${RUNNER_USER}' to the 'docker' group."
  fi

  # Group membership only takes effect on the next start of the runner service.
  if [ -n "$SVC" ]; then
    log "Restarting the runner service so it picks up the new group membership: ${SVC}"
    systemctl restart "$SVC" || warn "Could not restart ${SVC} — restart it manually so the group change takes effect."
  else
    warn "No runner systemd service to restart — restart the runner (or reboot) so the 'docker' group takes effect."
  fi
else
  warn "Skipping the Docker-group + runner-restart step (no runner user detected)."
fi

# --- 5. Warm the TeX font cache once (best-effort) ---------------------------
# Ties into bucket 2 of the lane fix: the FIRST lualatex/xelatex compile builds
# the luaotfload font-name database, which alone can exceed the per-test 60s
# pytest-timeout. Priming it here means the timed integration tests hit a warm
# cache on this host. Best-effort — never fails provisioning.
log "Warming the TeX font cache (best-effort; primes the first-render cache)..."
if command -v luaotfload-tool >/dev/null 2>&1; then
  luaotfload-tool --update || warn "luaotfload-tool --update failed (non-fatal warm-up)."
else
  warn "luaotfload-tool not found — skipping cache warm-up (the first real render will build it, once)."
fi

# --- 6. Verify -------------------------------------------------------------
# Optional/expected-missing checks must NOT hard-exit, so relax errexit here.
set +e
log "Verifying the runner is ready..."

if [ -n "$RUNNER_USER" ]; then
  echo "-- Docker reachable as '${RUNNER_USER}' (proves the runner user can reach the socket):"
  if sudo -u "$RUNNER_USER" docker version >/dev/null 2>&1; then
    echo "   OK: '${RUNNER_USER}' can talk to the Docker daemon."
  else
    echo "   NOTE: '${RUNNER_USER}' cannot reach Docker yet. Group membership takes effect on the"
    echo "         NEXT runner-service start (the restart above handles that for the runner's own"
    echo "         processes); a login shell for this user may still need a fresh session."
  fi
fi

echo "-- Required binaries:"
missing=0
for bin in xelatex lualatex soffice xvfb-run; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "   FOUND   $bin -> $(command -v "$bin")"
  else
    echo "   MISSING $bin"
    missing=1
  fi
done

echo
if [ "$missing" -eq 0 ]; then
  log "SUCCESS: all Integration-Lane system dependencies are present."
else
  warn "One or more binaries are still missing above — re-check the apt-get install output."
fi
echo "Next steps:"
echo "  * Ensure the GitHub Actions runner is registered and started (it needs the 'self-hosted' label)."
echo "  * Trigger the Integration Lane (workflow_dispatch) or wait for the weekly Sunday 02:00 UTC run."
echo "  * If Docker still needs sudo for the runner, restart the runner service (or reboot) once more."
