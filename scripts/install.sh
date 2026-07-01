#!/usr/bin/env bash
#
# Applicant — one-liner installer / lifecycle manager (FR-INSTALL-1/3, NFR-ZEROCLI-1).
#
# Proxmox-helper-script style: a single curl-pipe-bash bootstrap that provisions
# the whole Docker Compose stack (front-door UI + engine api + postgres + searxng
# + chromadb + ntfy) with sane, EDITABLE defaults and zero CLI knowledge required.
# The user opens the front-door UI on ${APP_PORT}; the engine api is internal.
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/install.sh)" -- --apply
#
# This is a LONG-RUNNING installer, so it is built to be:
#   • package-aware   — a preflight matrix of every dependency (present / version / missing)
#   • adaptive        — TTY vs headless, apt vs non-apt, root vs sudo, fresh vs existing volumes
#   • self-healing    — retries with backoff, starts the docker daemon, and repairs the
#                       classic non-root volume-ownership failure automatically
#   • communicative   — verbose streaming output + a live, redrawing health monitor
#   • progress-aware  — numbered phases with an overall progress bar
#   • health-checked  — a built-in `--doctor` self-check of a running install
#   • reversible      — `--uninstall` (keep data) and `--purge` (remove everything)
#
# The rich UI is a dependency-free ANSI/ASCII TUI (good color, no ncurses/whiptail).
# It is ADDITIVE and auto-detects an interactive terminal: on a non-TTY run (cloud-init,
# CI) it degrades to plain, greppable log lines. No new prompts are added on the install
# path — setup finishes in the browser (NFR-ZEROCLI-1). Force plain output with
# APPLICANT_NO_TUI=1 or the standard NO_COLOR.
#
# Modes (default is a SAFE DRY RUN — prints the steps it would run; nothing is changed):
#   --apply       build + start the stack, migrate, then health-check until green
#   --doctor      health self-check of an existing install, then exit (read-only)
#   --uninstall   stop & remove the containers, KEEPING data volumes and .env
#   --purge       --uninstall + REMOVE data volumes, built images and .env (destructive)
#   -y, --yes     assume "yes" (required to --purge non-interactively)
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

# ============================================================================
#  UI: dependency-free ANSI/ASCII TUI with a plain-text fallback
# ============================================================================
# Rich mode = interactive terminal, colors allowed, not explicitly disabled. Every
# helper below no-ops its escapes when UI_RICH=0, so headless/CI output stays clean.
if [[ -t 1 && "${TERM:-dumb}" != "dumb" && -z "${NO_COLOR:-}" && "${APPLICANT_NO_TUI:-0}" != "1" ]]; then
  UI_RICH=1
else
  UI_RICH=0
fi

if [[ "${UI_RICH}" -eq 1 ]]; then
  C0=$'\033[0m'; CB=$'\033[1m'; CD=$'\033[2m'
  CR=$'\033[31m'; CG=$'\033[32m'; CY=$'\033[33m'; CBL=$'\033[34m'; CC=$'\033[36m'; CGY=$'\033[90m'
else
  C0=''; CB=''; CD=''; CR=''; CG=''; CY=''; CBL=''; CC=''; CGY=''
fi

# ASCII glyphs by default (the operator asked for ASCII); upgrade to a few tasteful
# Unicode marks only when the locale is UTF-8 AND we're in rich mode.
if [[ "${UI_RICH}" -eq 1 && "${LC_ALL:-${LC_CTYPE:-${LANG:-}}}" == *[Uu][Tt][Ff]* ]]; then
  G_OK='✔'; G_NO='○'; G_BAD='✘'; G_DOT='•'; G_ARR='➜'
else
  G_OK='ok'; G_NO='..'; G_BAD='XX'; G_DOT='*'; G_ARR='>'
fi

STEP=0
STEPS_TOTAL=6
RENDER_LINES=0   # lines drawn by the last render_health_block (for in-place redraw)

# Legacy line logger kept so existing call sites / greppers still work.
log() { printf '%s[install]%s %s\n' "${CC}" "${C0}" "$*"; }

# A horizontal rule sized to the terminal (bounded), pure ASCII.
_rule() {
  local w cols; cols="$(tput cols 2>/dev/null || echo 80)"; (( cols > 72 )) && w=72 || w=$(( cols - 2 ))
  (( w < 20 )) && w=20
  printf '%s' "${CGY}"; printf '%*s' "${w}" '' | tr ' ' '-'; printf '%s\n' "${C0}"
}

ui_banner() {
  if [[ "${UI_RICH}" -ne 1 ]]; then log "Applicant installer"; return; fi
  printf '\n%s%s' "${CB}" "${CC}"
  cat <<'ART'
    _              _ _                 _
   / \   _ __  _ __| (_) ___ __ _ _ __ | |_
  / _ \ | '_ \| '_ \ | |/ __/ _` | '_ \| __|
 / ___ \| |_) | |_) | | | (_| (_| | | | | |_
/_/   \_\ .__/| .__/|_|_|\___\__,_|_| |_|\__|
        |_|   |_|
ART
  printf '%s' "${C0}"
  printf '  %sSelf-hosted autonomous job-application engine%s\n' "${CD}" "${C0}"
}

# A colored ASCII progress bar: [=====.....]  pct%
ui_bar() {
  local pct="${1:-0}" width="${2:-28}" filled fill empty
  (( pct < 0 )) && pct=0; (( pct > 100 )) && pct=100
  filled=$(( pct * width / 100 ))
  fill="$(printf '%*s' "${filled}" '' | tr ' ' '=')"
  empty="$(printf '%*s' "$(( width - filled ))" '' | tr ' ' '.')"
  printf '%s[%s%s%s%s%s]%s %3d%%' "${CGY}" "${CG}" "${fill}" "${CGY}" "${empty}" "${CGY}" "${C0}" "${pct}"
}

# Numbered phase header + overall progress bar. Six phases end-to-end.
phase() {
  STEP=$(( STEP + 1 ))
  local pct=$(( STEP * 100 / STEPS_TOTAL ))
  printf '\n%s%s%s Step %d/%d %s%s%s\n' "${CB}" "${CC}" "${G_ARR}" "${STEP}" "${STEPS_TOTAL}" "$*" "${C0}" ""
  printf '  %s  %soverall%s\n' "$(ui_bar "${pct}" 30)" "${CD}" "${C0}"
}

ui_step() { printf '  %s%s%s %s\n' "${CGY}" "${G_DOT}" "${C0}" "$*"; }
ui_ok()   { printf '  %s%s%s %s\n' "${CG}"  "${G_OK}"  "${C0}" "$*"; }
ui_warn() { printf '  %s%s%s %s\n' "${CY}"  '!'        "${C0}" "$*"; }
ui_err()  { printf '  %s%s%s %s\n' "${CR}"  "${G_BAD}" "${C0}" "$*" >&2; }

# Config domain: everything that can be preset BEFORE install. Shown up front so the
# operator sees exactly what will be provisioned and how to override it.
show_config() {
  _rule
  printf '  %sConfiguration%s  %s(preset any of these in the environment before --apply)%s\n' "${CB}" "${C0}" "${CD}" "${C0}"
  printf '    %-20s %s%s%s\n' "APP_URL"       "${CBL}" "$(_display_url)" "${C0}"
  printf '    %-20s %s%s%s%s\n' "APP_PORT"    "${CB}"  "${APP_PORT}" "${C0}" "$([[ "${APP_PORT}" == "80" || "${APP_PORT}" == "443" ]] && printf ' %s(privileged — bound by the Docker daemon)%s' "${CD}" "${C0}")"
  printf '    %-20s %s\n' "POSTGRES_USER" "${POSTGRES_USER}"
  printf '    %-20s %s\n' "POSTGRES_DB"   "${POSTGRES_DB}"
  printf '    %-20s %s\n' "POSTGRES_PASSWORD" "$([[ -f "${ENV_FILE}" ]] && echo '•••••••• (from .env)' || echo '•••••••• (generated on first apply)')"
  printf '    %-20s %s\n' "APT mirror"    "${APT_MIRROR}"
  printf '    %-20s %s\n' "Checkout"      "${REPO_ROOT}"
  printf '  %sExample:%s APP_PORT=80 APP_URL=http://your-host POSTGRES_PASSWORD=… bash scripts/install.sh --apply\n' "${CD}" "${C0}"
  _rule
}

# The launch pad: after a successful apply/update, tell the operator exactly where
# to go — open the app and where the first-run onboarding (OOBE) appears.
launch_pad() {
  echo
  ui_banner
  _rule
  printf '  %s%s Applicant is running%s\n\n' "${CB}${CG}" "${G_OK}" "${C0}"
  printf '    %sOpen the app:%s        %s%s%s\n' "${CB}" "${C0}" "${CBL}${CB}" "$(_display_url)" "${C0}"
  printf '    %sFirst-run setup:%s     the %sOOBE onboarding wizard%s launches automatically at that\n' "${CB}" "${C0}" "${CB}" "${C0}"
  printf '                         URL on first login — %sConnect a model %s➜%s Your profile%s.\n' "${CD}" "${CD}" "${CD}" "${C0}"
  printf '                         Re-openable later from Settings.\n'
  if [[ "${APP_PORT}" == "80" ]]; then
    printf '    %sPort:%s                bound on privileged port 80 (served by the Docker daemon).\n' "${CD}" "${C0}"
  fi
  echo
  printf '    %sHealth check:%s   bash scripts/install.sh --doctor\n' "${CD}" "${C0}"
  printf '    %sUpdate:%s         bash scripts/install.sh --update\n' "${CD}" "${C0}"
  printf '    %sUninstall:%s      bash scripts/install.sh --uninstall   %s(--purge also removes data)%s\n' "${CD}" "${C0}" "${CD}" "${C0}"
  _rule
}

# ============================================================================
#  Build-environment flags (unchanged behaviour)
# ============================================================================
# Append-only, line-based build output (no redraw frames) so the cloud-init log
# and any `tail -f` of it stays readable instead of dumping progress frames.
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"
# Skip the default provenance/SBOM attestations on local builds: they add an
# "exporting attestation manifest" round to every image export (slower, and wraps
# the image in a manifest list) with no value for a never-published local build.
export BUILDX_NO_DEFAULT_ATTESTATIONS="${BUILDX_NO_DEFAULT_ATTESTATIONS:-1}"
# Optional faster Debian apt mirror for the image builds (a bad Fastly edge node can
# crawl at ~80KB/s and the texlive layer is ~700MB → hours). Flows to the Dockerfiles
# via the compose build arg APT_MIRROR; default keeps the official CDN.
export APT_MIRROR="${APPLICANT_APT_MIRROR:-deb.debian.org}"

# ============================================================================
#  Argument parsing → MODE
# ============================================================================
APPLY=0
ASSUME_YES=0
MODE="dryrun"   # dryrun | apply | doctor | uninstall | purge
for arg in "$@"; do
  case "$arg" in
    --apply)          MODE="apply"; APPLY=1 ;;
    --update|--upgrade) MODE="update"; APPLY=1 ;;
    --doctor|--health) MODE="doctor" ;;
    --uninstall)      MODE="uninstall" ;;
    --purge)          MODE="purge" ;;
    -y|--yes)         ASSUME_YES=1 ;;
    -h|--help)
      cat <<EOF
Usage: install.sh [--apply | --update | --doctor | --uninstall | --purge] [-y]
  (default: dry-run — prints the steps it would run; nothing is changed)

  --apply       build + start the stack, migrate, then health-check until green
  --update      git-sync the checkout, back up the DB, rebuild, migrate, restart, health-check
  --doctor      health self-check of an existing install, then exit (read-only)
  --uninstall   stop & remove containers, KEEPING data volumes and .env
  --purge       uninstall + REMOVE data volumes, built images and .env (destructive)
  -y, --yes     assume "yes" (required to --purge non-interactively)

Preconfigurable env (preset any before --apply; persisted to .env and reused):
  APP_URL           public URL of the front door        (e.g. http://your-host)
  APP_PORT          host port to publish                 (e.g. 80, 443, 8000)
  POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB        database credentials
  APPLICANT_APT_MIRROR   faster Debian mirror hostname for the image builds
UI env: APPLICANT_NO_TUI=1 or NO_COLOR forces plain output.
EOF
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Overall progress denominator per mode (an update adds a source-sync phase; the
# single-shot modes are just one phase).
case "${MODE}" in
  update)                 STEPS_TOTAL=7 ;;
  doctor|uninstall|purge) STEPS_TOTAL=1 ;;
  *)                      STEPS_TOTAL=6 ;;
esac

# ============================================================================
#  Persisted settings + credentials
# ============================================================================
# Load any saved .env FIRST so re-runs/updates reuse the SAME database password.
# Postgres bakes its password into the data volume on first init; a divergent
# default here would break authentication. Explicit env vars still win.
if [[ -f "${ENV_FILE}" ]]; then
  while IFS='=' read -r _k _v; do
    [[ "${_k}" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue   # skip blanks/comments
    [[ -n "${!_k:-}" ]] || export "${_k}=${_v}"
  done <"${ENV_FILE}"
fi

# Credential generation + the regeneration guard only apply to the provisioning
# modes (apply / dry-run). doctor/uninstall/purge just need enough env for compose
# to interpolate `${POSTGRES_PASSWORD:?...}` when talking to existing containers.
if [[ "${MODE}" == "apply" || "${MODE}" == "dryrun" || "${MODE}" == "update" ]]; then
  # --- Credential-regeneration guard (issue #283) ---------------------------
  # Postgres bakes its superuser password into the data volume on first init and
  # never changes it. If .env was deleted and we minted a NEW random password while
  # the volume carried the OLD one, the app could no longer authenticate. Guard on
  # the ACTUAL volume state, not just `! -f .env`.
  if [[ -z "${POSTGRES_PASSWORD:-}" && "${APPLICANT_FORCE_CRED_REGEN:-0}" != "1" ]]; then
    _pg_volume=""
    if command -v docker >/dev/null 2>&1; then
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

  # --- Editable defaults (override via environment; FR-INSTALL-1) -----------
  export POSTGRES_USER="${POSTGRES_USER:-applicant}"
  _gen_secret() {  # $1 = openssl-style length; falls back to python3
    if command -v openssl >/dev/null 2>&1; then
      case "$1" in hex32) openssl rand -hex 32 ;; *) openssl rand -base64 24 | tr -d '/+=' | cut -c1-24 ;; esac
    else
      case "$1" in hex32) python3 -c 'import secrets; print(secrets.token_hex(32))' ;; *) python3 -c 'import secrets; print(secrets.token_urlsafe(24))' ;; esac
    fi
  }
  [[ -n "${POSTGRES_PASSWORD:-}" ]] || POSTGRES_PASSWORD="$(_gen_secret pw)"
  export POSTGRES_PASSWORD
  export POSTGRES_DB="${POSTGRES_DB:-applicant}"
  # Stage-2.5 reverse channel shared secret (api ↔ front-door UI) — minted once,
  # persisted to .env, read by BOTH containers.
  [[ -n "${APPLICANT_INTERNAL_TOKEN:-}" ]] || APPLICANT_INTERNAL_TOKEN="$(_gen_secret hex32)"
  export APPLICANT_INTERNAL_TOKEN
  # SearXNG secret_key: substituted into the mounted settings.yml on first boot.
  [[ -n "${SEARXNG_SECRET:-}" ]] || SEARXNG_SECRET="$(_gen_secret hex32)"
  export SEARXNG_SECRET
else
  # Non-provisioning modes: harmless placeholder just so compose can interpolate
  # required-without-default vars while stopping/inspecting existing containers.
  export POSTGRES_USER="${POSTGRES_USER:-applicant}"
  export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-unused-for-teardown}"
  export POSTGRES_DB="${POSTGRES_DB:-applicant}"
  export APPLICANT_INTERNAL_TOKEN="${APPLICANT_INTERNAL_TOKEN:-}"
  export SEARXNG_SECRET="${SEARXNG_SECRET:-}"
fi

# Best-effort primary IP of THIS host so the launch pad shows a URL reachable from
# other machines rather than localhost. Falls back to localhost if none is found.
_host_ip() {
  local ip=""
  ip="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
  [[ -z "${ip}" ]] && ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -z "${ip}" ]] && ip="localhost"
  printf '%s' "${ip}"
}
HOST_IP="$(_host_ip)"

# The URL to SHOW the operator: APP_URL with a localhost/127.0.0.1 host swapped for
# the detected IP so it is reachable from another machine. Health probes still hit
# localhost (this host), so this only affects what is printed.
_display_url() {
  local u="${APP_URL}"
  case "${u}" in
    *localhost*) u="${u/localhost/${HOST_IP}}" ;;
    *127.0.0.1*) u="${u/127.0.0.1/${HOST_IP}}" ;;
  esac
  printf '%s' "${u}"
}

APP_URL="${APP_URL:-http://${HOST_IP}:8000}"
# The compose file publishes the front door on ${APP_PORT:-8000}. Derive APP_PORT
# from APP_URL (unless explicitly set) and EXPORT it so the published port, the
# heartbeat target, and the persisted .env all agree. An explicit :port in APP_URL
# wins; otherwise infer from the scheme so a bare `http://host` binds :80 and
# `https://host` binds :443 (first-class port-80 support — set APP_PORT=80 directly
# too). Docker's daemon (root) binds privileged ports, so :80 needs no extra setup.
if [[ -z "${APP_PORT:-}" ]]; then
  case "${APP_URL}" in
    *://*:[0-9]*) APP_PORT="${APP_URL##*:}"; APP_PORT="${APP_PORT%%/*}" ;;
    https://*)    APP_PORT=443 ;;
    http://*)     APP_PORT=80 ;;
    *)            APP_PORT=8000 ;;
  esac
fi
[[ "${APP_PORT}" =~ ^[0-9]+$ ]] || APP_PORT=8000
export APP_PORT

# Persist the settings + secrets to .env (0600) so every later run/update reuses the
# SAME values (esp. the DB password Postgres baked into its volume at first init).
# Single writer so first-install and reconfigure stay in lock-step.
write_env() {
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
}

# The web-server / network settings the operator can tune: HOW the app is reached
# (address mode + host) and the PORT it is published on. APP_URL is DERIVED from
# these so the published port and the printed URL can never disagree — the port-80
# reconfigure that still printed :8000 was exactly that divergence.
#
# Current values are pre-filled as defaults; pressing Enter keeps each one. The host
# is chosen as either the auto-detected IP (DHCP-style) or a manually entered static
# IP / DNS hostname. This ONLY touches web-server settings — secrets are never
# prompted (changing POSTGRES_* against an initialized volume would break auth).
configure_web_server() {
  printf '\n  %sWeb-server / network settings%s  %s(Enter keeps the default in [brackets])%s\n' \
    "${CB}" "${C0}" "${CD}" "${C0}"

  # 1) Address: how users reach Applicant.
  printf '    %sAddress%s\n' "${CB}" "${C0}"
  printf '      1) Automatic — use this host'"'"'s detected IP  %s(%s)%s  %s[default]%s\n' "${CD}" "${HOST_IP}" "${C0}" "${CD}" "${C0}"
  printf '      2) Static — enter an IP or DNS hostname\n'
  local mode="" host="${HOST_IP}"
  printf '    Choice [1]: '; read -r mode || true
  if [[ "${mode}" == "2" ]]; then
    printf '    IP or hostname [%s]: ' "${HOST_IP}"; read -r host || true
    [[ -n "${host}" ]] || host="${HOST_IP}"
  fi

  # 2) Port (80/443 are privileged but bound by the Docker daemon, so they just work).
  local port="${APP_PORT}" new=""
  printf '    %sPort%s [%s]  %s(e.g. 80, 443, 8000)%s: ' "${CB}" "${C0}" "${port}" "${CD}" "${C0}"
  read -r new || true
  if [[ -n "${new}" ]]; then
    if [[ "${new}" =~ ^[0-9]+$ ]] && (( new >= 1 && new <= 65535 )); then
      port="${new}"
    else
      ui_warn "Invalid port '${new}' — keeping ${port}."
    fi
  fi

  # 3) Derive a single, consistent scheme://host[:port]. 80 → http (no port shown),
  #    443 → https, anything else → http://host:port. APP_PORT is what compose
  #    actually publishes; APP_URL is the display/heartbeat URL built from the same.
  case "${port}" in
    80)  APP_URL="http://${host}" ;;
    443) APP_URL="https://${host}" ;;
    *)   APP_URL="http://${host}:${port}" ;;
  esac
  APP_PORT="${port}"
  export APP_URL APP_PORT
}

# When a prior install is detected AND we're interactive, offer to change the web-
# server settings before rebuilding. On a non-TTY run (cloud-init) or a fresh box
# this is a silent no-op, so the zero-prompt install path is unchanged (NFR-ZEROCLI-1).
maybe_reconfigure() {
  [[ "${APPLY}" -eq 1 ]] || return 0
  [[ "${UI_RICH}" -eq 1 ]] || return 0     # need a TTY to prompt
  local detected=0
  [[ -f "${ENV_FILE}" ]] && detected=1
  if [[ "${detected}" -eq 0 ]] && command -v docker >/dev/null 2>&1; then
    docker volume ls --quiet 2>/dev/null | grep -qE '(^|_)pgdata$' && detected=1
  fi
  [[ "${detected}" -eq 1 ]] || return 0

  _rule
  ui_warn "Existing Applicant installation detected."
  printf '    %-14s %s\n' "Current URL"  "$(_display_url)"
  printf '    %-14s %s\n' "Published port" "${APP_PORT}"
  local ans=""
  printf '  %sReconfigure the web-server / network settings? [y/N]:%s ' "${CB}" "${C0}"
  read -r ans || true
  if [[ ! "${ans}" =~ ^[Yy] ]]; then ui_step "Keeping the current configuration."; _rule; return 0; fi

  configure_web_server
  write_env
  ui_ok "Saved to ${ENV_FILE} — URL $(_display_url), publishing port ${APP_PORT}."
  _rule
}

# ============================================================================
#  Generic helpers: sudo, retries, run wrappers, docker plumbing
# ============================================================================
_maybe_sudo() { if [[ "$(id -u)" -eq 0 ]]; then "$@"; elif command -v sudo >/dev/null 2>&1; then sudo "$@"; else "$@"; fi; }

# Self-healing: retry a flaky command with exponential backoff (network builds,
# apt, transient daemon hiccups). Streams the command's own output as it goes.
retry() {
  local tries="$1" label="$2"; shift 2
  local n=1 delay=2
  until "$@"; do
    if (( n >= tries )); then ui_err "${label} failed after ${n} attempts."; return 1; fi
    ui_warn "${label} failed (attempt ${n}/${tries}) — retrying in ${delay}s…"
    sleep "${delay}"; delay=$(( delay * 2 )); n=$(( n + 1 ))
  done
  return 0
}

# In apply mode run for real; otherwise print what WOULD run (dry-run parity).
run() {
  if [[ "${APPLY}" -eq 1 ]]; then "$@"; else printf '  %s(would run)%s %s\n' "${CD}" "${C0}" "$*"; fi
}
run_retry() {
  local label="$1"; shift
  if [[ "${APPLY}" -eq 1 ]]; then retry 3 "${label}" "$@"; else printf '  %s(would run)%s %s\n' "${CD}" "${C0}" "$*"; fi
}

DOCKER_PREFIX=()
dc() { ${DOCKER_PREFIX[@]+"${DOCKER_PREFIX[@]}"} docker compose "$@"; }

# One "service<TAB>state<TAB>health" line per running compose service, parsed from
# `docker compose ps` JSON with python3 (jq is not guaranteed on a bare host).
_service_health_lines() {
  dc -f "${COMPOSE_FILE}" ps --format json 2>/dev/null | python3 -c '
import sys, json
data = sys.stdin.read().strip()
rows = []
if data:
    try:
        objs = json.loads(data)
        if isinstance(objs, dict):
            objs = [objs]
    except json.JSONDecodeError:
        objs = [json.loads(line) for line in data.splitlines() if line.strip()]
    for o in objs:
        svc = o.get("Service") or o.get("Name") or "?"
        rows.append("%s\t%s\t%s" % (svc, o.get("State") or "", o.get("Health") or ""))
for r in sorted(rows):
    print(r)
' 2>/dev/null || true
}

# Reduce health lines to "<ok> <total>". A service is ok when running AND (healthy
# OR it declares no healthcheck at all — an always-empty Health field).
_health_progress() {
  printf '%s\n' "$1" | awk -F'\t' '
    NF { total++; if ($2=="running" && ($3=="healthy" || $3=="")) ok++ }
    END { printf "%d %d", ok+0, total+0 }'
}

# Render the health block (services + bar). Sets RENDER_LINES to the number of lines
# printed so a caller can move the cursor up and redraw in place (rich mode).
render_health_block() {
  local lines="$1" svc state health mark n=0 ok total pr pct
  pr="$(_health_progress "${lines}")"; ok="${pr%% *}"; total="${pr##* }"
  pct=0; (( total > 0 )) && pct=$(( ok * 100 / total ))
  printf '\033[K  %sServices%s  %s  %s%d/%d%s\n' "${CB}" "${C0}" "$(ui_bar "${pct}" 20)" "${CD}" "${ok}" "${total}" "${C0}"
  n=$(( n + 1 ))
  if [[ -z "${lines}" ]]; then
    printf '\033[K    %s(no containers up yet)%s\n' "${CD}" "${C0}"; RENDER_LINES=2; return
  fi
  while IFS=$'\t' read -r svc state health; do
    [[ -z "${svc}" ]] && continue
    if [[ "${state}" == "running" && ( "${health}" == "healthy" || -z "${health}" ) ]]; then
      mark="${CG}${G_OK}${C0}"
    elif [[ "${state}" == "running" ]]; then
      mark="${CY}${G_NO}${C0}"
    else
      mark="${CR}${G_BAD}${C0}"
    fi
    printf '\033[K    %s  %-16s %s%s%s\n' "${mark}" "${svc}" "${CD}" "${state}${health:+/${health}}" "${C0}"
    n=$(( n + 1 ))
  done <<<"${lines}"
  RENDER_LINES=$(( n + 1 ))
}

# Live health monitor. Rich: redraw the block in place until green or timeout.
# Plain: emit a fresh table every few polls. Returns 0 once the UI answers on the
# public port AND all services are ok; non-zero on timeout.
monitor_health() {
  local port="$1" tries="${2:-90}" i lines ok total pr first=1 web_ok=0
  for (( i = 1; i <= tries; i++ )); do
    lines="$(_service_health_lines)"
    pr="$(_health_progress "${lines}")"; ok="${pr%% *}"; total="${pr##* }"
    if [[ "${UI_RICH}" -eq 1 ]]; then
      (( first == 0 )) && printf '\033[%dA' "${RENDER_LINES}"
      render_health_block "${lines}"
      first=0
    elif (( i == 1 || i % 4 == 0 )); then
      log "Waiting for services to become healthy… (${ok}/${total})"
    fi
    web_ok=0
    curl -fsS -o /dev/null "http://localhost:${port}/api/health" 2>/dev/null && web_ok=1
    if (( total > 0 && ok == total && web_ok == 1 )); then return 0; fi
    sleep 3
  done
  return 1
}

# Plain, one-shot health table (used by --doctor and the plain success/finish path).
print_health_table() {
  local lines; lines="$(_service_health_lines)"
  if [[ -z "${lines}" ]]; then ui_warn "No running services reported."; return; fi
  printf '%s\n' "${lines}" | while IFS=$'\t' read -r svc state health; do
    if [[ "${state}" == "running" && ( "${health}" == "healthy" || -z "${health}" ) ]]; then
      ui_ok "$(printf '%-16s %s' "${svc}" "${state}${health:+/${health}}")"
    elif [[ "${state}" == "running" ]]; then
      ui_warn "$(printf '%-16s %s' "${svc}" "${state}${health:+/${health}}")"
    else
      ui_err "$(printf '%-16s %s' "${svc}" "${state}${health:+/${health}}")"
    fi
  done
}

# ============================================================================
#  Docker reachability (install/apply/doctor/uninstall all need the daemon)
# ============================================================================
# Set up DOCKER_PREFIX (transparent sudo when the socket isn't reachable as this
# user yet) so every dc() call is consistent. Self-healing: start the daemon if it
# is installed but not running.
ensure_docker_reachable() {
  if ! command -v docker >/dev/null 2>&1; then return 1; fi
  if docker info >/dev/null 2>&1; then return 0; fi
  # Installed but not answering — try to start it (systemd hosts), then re-check.
  if command -v systemctl >/dev/null 2>&1; then
    ui_warn "Docker daemon not responding — attempting to start it…"
    _maybe_sudo systemctl start docker >/dev/null 2>&1 || true
    sleep 2
    docker info >/dev/null 2>&1 && { ui_ok "Docker daemon started."; return 0; }
  fi
  # Socket permission (fresh 'docker' group membership needs a new login) → sudo.
  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    ui_warn "Can't reach the Docker socket as $(id -un) yet (group needs a re-login) — using sudo for this run."
    DOCKER_PREFIX=(sudo "--preserve-env=POSTGRES_USER,POSTGRES_PASSWORD,POSTGRES_DB,APPLICANT_INTERNAL_TOKEN,SEARXNG_SECRET,APP_URL,APP_PORT,APPLICANT_REPO_DIR,APT_MIRROR,BUILDKIT_PROGRESS,BUILDX_NO_DEFAULT_ATTESTATIONS")
    return 0
  fi
  return 1
}

# ============================================================================
#  Preflight: package-aware dependency matrix
# ============================================================================
# Reports every dependency (present + version, or missing) so a long install fails
# fast and legibly instead of dying deep in a build. Docker + Compose v2 are the
# only hard requirements; the rest are informational / used by specific paths.
_ver() { "$@" 2>/dev/null | head -n1; }
preflight_packages() {
  phase "Preflight — checking packages"
  local hard_missing=0

  if command -v docker >/dev/null 2>&1; then ui_ok "docker            $(_ver docker --version)"
  else ui_err "docker            missing (required)"; hard_missing=1; fi

  if docker compose version >/dev/null 2>&1; then ui_ok "docker compose    $(_ver docker compose version)"
  else ui_warn "docker compose    not detected yet (will verify after install)"; fi

  if command -v git  >/dev/null 2>&1; then ui_ok "git               $(_ver git --version)"; else ui_warn "git               missing (needed only for curl|bash bootstrap)"; fi
  if command -v curl >/dev/null 2>&1; then ui_ok "curl              $(_ver curl --version)"; else ui_warn "curl              missing (health heartbeat uses it)"; fi
  if command -v python3 >/dev/null 2>&1; then ui_ok "python3           $(_ver python3 --version)"; else ui_warn "python3           missing (health parsing / secret fallback)"; fi
  if command -v openssl >/dev/null 2>&1; then ui_ok "openssl           $(_ver openssl version)"; else ui_step "openssl           absent (python3 used for secrets)"; fi
  if command -v apt-get >/dev/null 2>&1; then ui_step "apt-get           present (auto-install available)"; else ui_step "apt-get           absent (manual dependency install)"; fi

  # Adaptive context line.
  local ctx tty_yn=no root_yn=no
  [[ "${UI_RICH}" -eq 1 ]] && tty_yn=yes
  [[ "$(id -u)" -eq 0 ]] && root_yn=yes
  ctx="tty=${tty_yn} user=$(id -un) root=${root_yn} arch=$(uname -m)"
  ui_step "environment: ${ctx}"

  return "${hard_missing}"
}

# Install Docker Engine + Compose v2 on apt hosts (idempotent) when missing.
ensure_docker_installed() {
  if command -v docker >/dev/null 2>&1; then return 0; fi
  if [[ "${APPLICANT_SKIP_DOCKER_INSTALL:-0}" != "1" ]] && command -v apt-get >/dev/null 2>&1; then
    ui_step "Docker not found — installing Docker Engine + Compose v2 (get.docker.com)…"
    if [[ "${APPLY}" -eq 1 ]]; then
      if ! retry 3 "Docker install" bash -c 'curl -fsSL https://get.docker.com | '"$([[ $(id -u) -eq 0 ]] && echo sh || echo 'sudo sh')"; then
        ui_err "Automatic Docker install failed. Install Docker Engine + Compose v2 manually, then re-run."
        return 1
      fi
      _maybe_sudo systemctl enable --now docker >/dev/null 2>&1 || true
    else
      printf '  %s(would run)%s curl -fsSL https://get.docker.com | sh\n' "${CD}" "${C0}"
    fi
  else
    ui_err "docker is required but not found, and auto-install is unavailable here."
    ui_err "Install Docker Engine + Compose v2 (https://docs.docker.com/engine/install/), then re-run."
    return 1
  fi
  return 0
}

# ============================================================================
#  Modes: doctor / uninstall / purge
# ============================================================================
mode_doctor() {
  ui_banner
  phase "Doctor — health self-check"
  if ! command -v docker >/dev/null 2>&1 || ! ensure_docker_reachable; then
    ui_err "Docker is not reachable — cannot inspect the stack."; exit 1
  fi
  ui_step "Compose file: ${COMPOSE_FILE}"
  print_health_table
  # Deep engine probe: exec /healthz inside the api container and show the verdict.
  if dc -f "${COMPOSE_FILE}" exec -T api \
       python -c "import urllib.request,sys; r=urllib.request.urlopen('http://localhost:8000/healthz',timeout=5); sys.exit(0 if r.status==200 else 1)" 2>/dev/null; then
    ui_ok "engine /healthz    200 (database reachable, vault key dir writable)"
  else
    ui_warn "engine /healthz    not green (see: docker compose -f ${COMPOSE_FILE} logs api)"
  fi
  if curl -fsS -o /dev/null "http://localhost:${APP_PORT}/api/health" 2>/dev/null; then
    ui_ok "front door        http://localhost:${APP_PORT} answering"
  else
    ui_warn "front door        not answering on :${APP_PORT}"
  fi
  # Overall verdict from the same criteria the installer waits on.
  local pr ok total; pr="$(_health_progress "$(_service_health_lines)")"; ok="${pr%% *}"; total="${pr##* }"
  echo
  if (( total > 0 && ok == total )); then
    ui_ok "Diagnosis: all ${total} services healthy. Open ${APP_URL}"
    exit 0
  fi
  ui_err "Diagnosis: ${ok}/${total} services healthy. Investigate the ones marked above."
  exit 1
}

_confirm_destructive() {
  local what="$1"
  [[ "${ASSUME_YES}" -eq 1 ]] && return 0
  if [[ "${UI_RICH}" -eq 1 ]]; then
    local reply
    printf '%s%s%s %sType "yes" to %s: %s' "${CY}" "${G_NO}" "${C0}" "${CB}" "${what}" "${C0}"
    read -r reply
    [[ "${reply}" == "yes" ]] && return 0
    ui_step "Aborted."; return 1
  fi
  ui_err "${what} needs confirmation; re-run with -y/--yes (no TTY to prompt)."
  return 1
}

mode_uninstall() {
  ui_banner
  phase "Uninstall — stop & remove containers (keeping data)"
  ensure_docker_reachable || { ui_err "Docker not reachable."; exit 1; }
  ui_step "Stopping and removing the Applicant containers (volumes are KEPT)…"
  dc -f "${COMPOSE_FILE}" down --remove-orphans || true
  ui_ok "Containers removed. Data volumes and ${ENV_FILE} are preserved."
  ui_step "To also remove data + images + .env: bash scripts/install.sh --purge"
  exit 0
}

mode_purge() {
  ui_banner
  phase "Purge — remove containers, volumes, images and .env"
  ensure_docker_reachable || { ui_err "Docker not reachable."; exit 1; }
  ui_warn "This DESTROYS all Applicant data: database, vault key, browser sessions, fonts."
  _confirm_destructive "permanently delete all Applicant data" || exit 1
  ui_step "Removing containers + named volumes + locally-built images…"
  dc -f "${COMPOSE_FILE}" down --volumes --rmi local --remove-orphans || true
  if [[ -f "${ENV_FILE}" ]]; then
    ui_step "Removing ${ENV_FILE}…"; rm -f "${ENV_FILE}"
  fi
  ui_ok "Purge complete. Nothing Applicant-related remains (aside from the checkout)."
  exit 0
}

# ============================================================================
#  Dispatch non-install modes early
# ============================================================================
case "${MODE}" in
  doctor)    mode_doctor ;;
  uninstall) mode_uninstall ;;
  purge)     mode_purge ;;
esac

# ============================================================================
#  Install / update / dry-run flow
# ============================================================================
ui_banner
maybe_reconfigure
show_config

# --- Phase 1: preflight packages + ensure docker ----------------------------
preflight_packages || ui_warn "A required package is missing — will try to remediate below."
ensure_docker_installed || exit 1
if [[ "${APPLY}" -eq 1 ]]; then
  ensure_docker_reachable || {
    ui_err "Cannot reach the Docker daemon at /var/run/docker.sock as $(id -un)."
    ui_err "Grant access and start a NEW shell, then re-run:"
    ui_err "    sudo usermod -aG docker $(id -un) && newgrp docker"
    ui_err "…or re-run this installer as root (sudo)."
    exit 1
  }
  if ! docker compose version >/dev/null 2>&1 && ! dc version >/dev/null 2>&1; then
    ui_err "docker compose v2 is required but not found (the Compose plugin did not install)."
    ui_err "Install it: https://docs.docker.com/compose/install/linux/  then re-run."
    exit 1
  fi
fi

# --- Update-only phase: sync the source checkout ----------------------------
# `--update` fast-forwards the checkout so the rebuild below picks up new code, then
# flows through the SAME idempotent build → migrate → up → health path as install.
if [[ "${MODE}" == "update" ]]; then
  phase "Syncing the source checkout (git)"
  if [[ -d "${REPO_ROOT}/.git" ]]; then
    if [[ "${APPLY}" -eq 1 ]]; then
      run_retry "git fetch" git -C "${REPO_ROOT}" fetch --prune origin
      if _pull_out="$(git -C "${REPO_ROOT}" pull --ff-only 2>&1)"; then
        ui_ok "${_pull_out}"
      else
        ui_warn "Could not fast-forward the checkout: ${_pull_out}"
        ui_step "Continuing the update with the CURRENT checkout."
      fi
    else
      printf '  %s(would run)%s git -C %s pull --ff-only\n' "${CD}" "${C0}" "${REPO_ROOT}"
    fi
  else
    ui_warn "${REPO_ROOT} is not a git checkout — skipping source sync (rebuilding as-is)."
  fi
fi

# --- Phase 2: validate the production compose file --------------------------
phase "Validating the production compose file"
ui_step "Compose file: ${COMPOSE_FILE}"
if [[ "${APPLY}" -eq 1 ]]; then
  dc -f "${COMPOSE_FILE}" config >/dev/null && ui_ok "Compose file is valid."
else
  printf '  %s(would run)%s docker compose -f %s config\n' "${CD}" "${C0}" "${COMPOSE_FILE}"
fi

# --- Persist the DB credentials so every later run/update reuses them --------
# Write .env ONCE (first apply). This keeps `update.sh` authenticating against the
# password Postgres baked into its volume at first init.
if [[ "${APPLY}" -eq 1 && ! -f "${ENV_FILE}" ]]; then
  ui_step "Persisting credentials to ${ENV_FILE} (re-used by every update)…"
  write_env
  ui_ok "Credentials persisted (0600)."
fi

# --- Phase 3: build the images ----------------------------------------------
# Build BOTH locally-built images (neither is published to a registry): the
# front-door UI (built from ../workspace) and the engine api. Output streams
# verbosely (BUILDKIT_PROGRESS=plain); retried with backoff on transient failures.
phase "Building the local images (front-door UI + engine api)"
ui_step "Streaming build output below (this is the long part — texlive + browsers)…"
run_retry "Image build" dc -f "${COMPOSE_FILE}" build applicant-ui api

# --- Phase 4: migrate the schema BEFORE the api serves ----------------------
# The engine queries app_config AS IT BOOTS, so the schema must exist first. Bring
# up only Postgres, then run alembic in a throwaway api container (env.py imports
# model metadata only). A full `up -d` here would crash-loop the api on the missing
# table and, because applicant-ui depends_on api: service_healthy, abort the up.
phase "Migrating the schema (alembic upgrade head) BEFORE the api serves"
run dc -f "${COMPOSE_FILE}" up -d postgres
# On --update, snapshot the DB into the pgbackups volume BEFORE migrating so a bad
# migration is recoverable (parity with update.sh's backup step). Best-effort.
if [[ "${MODE}" == "update" && "${APPLY}" -eq 1 ]]; then
  ui_step "Backing up the database before migrating (into the pgbackups volume)…"
  if dc -f "${COMPOSE_FILE}" exec -T postgres \
       sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" > "/backups/pre-update-$(date -u +%Y%m%dT%H%M%SZ).sql"' 2>/dev/null; then
    ui_ok "Database backed up (see the pgbackups volume)."
  else
    ui_warn "DB backup skipped (postgres not reachable yet) — migration is still idempotent."
  fi
fi
run_retry "Alembic migrate" dc -f "${COMPOSE_FILE}" run --rm api uv run alembic upgrade head

# --- Phase 5: bring up the full stack ---------------------------------------
phase "Bringing up the full stack (UI + api + postgres + searxng + chromadb + ntfy)"
run dc -f "${COMPOSE_FILE}" up -d

# --- Phase 6: health monitor + self-heal ------------------------------------
phase "Health — waiting for the stack to go green"
if [[ "${APPLY}" -eq 1 ]]; then
  if ! monitor_health "${APP_PORT}"; then
    # Self-heal the classic failure: the non-root api can't write its root-owned
    # /data volumes (pre-existing volumes created before the ownership fix). chown
    # them to the runtime uid via a throwaway root container, restart, and re-wait.
    ui_warn "Stack not green yet — attempting self-heal (repair /data volume ownership)…"
    dc -f "${COMPOSE_FILE}" run --rm --user 0:0 --no-deps --entrypoint sh api \
        -c 'chown -R 10001:10001 /data /control 2>/dev/null || true' >/dev/null 2>&1 || true
    dc -f "${COMPOSE_FILE}" up -d --force-recreate api applicant-ui >/dev/null 2>&1 || true
    if monitor_health "${APP_PORT}"; then
      ui_ok "Self-heal succeeded — the stack is green."
    else
      echo
      ui_err "Install did not come up healthy after self-heal."
      print_health_table
      ui_err "Inspect: docker compose -f ${COMPOSE_FILE} ps    (and: … logs api)"
      exit 1
    fi
  fi
  launch_pad
else
  echo
  ui_step "DRY RUN complete (no --apply). Re-run with --apply to provision the stack."
  ui_step "Other modes: --update, --doctor (health check), --uninstall, --purge."
fi
