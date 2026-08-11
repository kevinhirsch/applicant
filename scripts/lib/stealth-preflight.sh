#!/usr/bin/env bash
#
# Shared STEALTH preflight (EPIC STEALTH) — sourced by scripts/install.sh and
# scripts/update.sh so a clean deploy ships/verifies the stealth prerequisites and
# a rebuild never silently drops them. ONE implementation, two callers (CLAUDE.md
# principle #1 — compose existing services, don't fork the logic).
#
# Principle: Applicant must NEVER egress from the home WAN IP, and hard anti-bot
# targets must exit a residential proxy. This preflight makes those prerequisites
# first-class and FAILS LOUDLY when one is missing while stealth is enabled.
#
# Contract:
#   stealth_preflight     <apply:0|1>   # host deps: WireGuard client, egress, proxy
#   stealth_verify_image  <apply:0|1>   # best-effort: camoufox baked in applicant/api
# Both return 0 unless APPLICANT_STEALTH_STRICT is truthy AND a HARD prereq failed,
# in which case they return non-zero so the caller can abort the deploy.
#
# Every stealth value is a preset DEFAULT that is CHANGEABLE (env / Settings UI):
#   APPLICANT_STEALTH_ENABLED         (default true)  master switch for this preflight
#   APPLICANT_STEALTH_STRICT          (default false) abort on a missing HARD prereq
#   APPLICANT_STEALTH_SKIP_WG_INSTALL (default false) don't apt-install WireGuard
#   A0_BROWSER_RESIDENTIAL_PROXY / EGRESS_PROXY  residential forwarder (default 10.8.0.1:8880)
#   WG_VPS_ENDPOINT                   expected VPS egress endpoint (default 173.254.204.32:51820)
#
# Safe to source multiple times; safe under `set -euo pipefail` (every fallible
# probe is guarded so it never aborts the caller by itself).

if [[ -n "${_APPLICANT_STEALTH_PREFLIGHT_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
_APPLICANT_STEALTH_PREFLIGHT_LOADED=1

# --- UI shims: reuse the caller's renderer when present, else plain fallbacks ---
_sp_phase() { if declare -F phase >/dev/null 2>&1; then phase "$*"; elif declare -F log >/dev/null 2>&1; then log "$*"; else printf '\n[stealth] %s\n' "$*"; fi; }
_sp_step()  { if declare -F ui_step >/dev/null 2>&1; then ui_step "$*"; elif declare -F log >/dev/null 2>&1; then log "  $*"; else printf '  - %s\n' "$*"; fi; }
_sp_ok()    { if declare -F ui_ok   >/dev/null 2>&1; then ui_ok   "$*"; elif declare -F log >/dev/null 2>&1; then log "  OK: $*"; else printf '  [OK] %s\n' "$*"; fi; }
_sp_warn()  { if declare -F ui_warn >/dev/null 2>&1; then ui_warn "$*"; elif declare -F log >/dev/null 2>&1; then log "  WARN: $*"; else printf '  [!] %s\n' "$*" >&2; fi; }
_sp_err()   { if declare -F ui_err  >/dev/null 2>&1; then ui_err  "$*"; elif declare -F log >/dev/null 2>&1; then log "  ERROR: $*"; else printf '  [x] %s\n' "$*" >&2; fi; }

_sp_truthy() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

stealth_is_enabled() { _sp_truthy "${APPLICANT_STEALTH_ENABLED:-true}"; }
stealth_is_strict()  { _sp_truthy "${APPLICANT_STEALTH_STRICT:-false}"; }

_sp_sudo() {
  if [[ "$(id -u)" -eq 0 ]]; then "$@";
  elif command -v sudo >/dev/null 2>&1; then sudo "$@";
  else "$@"; fi
}

# The residential forwarder the a0 browser patch + discovery escalate onto. Same
# default as the baked default_config.yaml and the compose a0 service.
_sp_residential_proxy() {
  printf '%s' "${A0_BROWSER_RESIDENTIAL_PROXY:-${EGRESS_PROXY:-http://10.8.0.1:8880}}"
}
# Expected VPS egress IP (host:port stripped to host). Used to detect a home-IP leak
# WITHOUT ever hardcoding the private home IP: if the host's public IP is NOT the
# VPS, egress is leaking.
_sp_expected_vps_ip() {
  local ep="${WG_VPS_ENDPOINT:-173.254.204.32:51820}"
  ep="${ep%%:*}"
  printf '%s' "${ep}"
}

# --- Host preflight ----------------------------------------------------------
# $1 = apply (1 = may install packages / stage files; 0 = report only / dry-run)
stealth_preflight() {
  local apply="${1:-0}"
  local hard_fail=0

  if ! stealth_is_enabled; then
    _sp_phase "Stealth preflight — DISABLED (APPLICANT_STEALTH_ENABLED=false), skipping"
    return 0
  fi

  _sp_phase "Stealth preflight — verifying no-home-IP-leak prerequisites"
  local strict_note="warn-only"; stealth_is_strict && strict_note="STRICT (missing hard prereq aborts)"
  _sp_step "mode: ${strict_note}  (set APPLICANT_STEALTH_STRICT=true to hard-gate)"

  # 1) WireGuard client (HARD) — the host must be able to route egress via the VPS.
  if command -v wg >/dev/null 2>&1 && command -v wg-quick >/dev/null 2>&1; then
    _sp_ok "WireGuard client  present ($(wg --version 2>/dev/null | head -n1))"
  else
    if [[ "${apply}" -eq 1 ]] && ! _sp_truthy "${APPLICANT_STEALTH_SKIP_WG_INSTALL:-false}" && command -v apt-get >/dev/null 2>&1; then
      _sp_step "WireGuard client  missing — installing (apt: wireguard wireguard-tools)…"
      if _sp_sudo apt-get update >/dev/null 2>&1 && \
         _sp_sudo apt-get install -y --no-install-recommends wireguard wireguard-tools >/dev/null 2>&1; then
        _sp_ok "WireGuard client  installed."
      else
        _sp_err "WireGuard client  install FAILED — Applicant would egress the HOME IP."
        _sp_err "                  Install manually: apt-get install wireguard wireguard-tools"
        hard_fail=1
      fi
    else
      _sp_err "WireGuard client  MISSING (wg/wg-quick) — Applicant would egress the HOME IP."
      _sp_err "                  Install: apt-get install wireguard wireguard-tools"
      [[ "${apply}" -ne 1 ]] && _sp_step "                  (dry-run: --apply would auto-install it)"
      hard_fail=1
    fi
  fi

  # 2) VPS egress routing (HARD under strict) — is a tunnel up, and does egress exit
  #    the VPS rather than the home IP? Stage the config template + steps if not.
  local wg_up=0
  if command -v wg >/dev/null 2>&1 && [[ -n "$(wg show interfaces 2>/dev/null || true)" ]]; then
    wg_up=1
    _sp_ok "WireGuard tunnel  up ($(wg show interfaces 2>/dev/null | tr '\n' ' '))"
  else
    _sp_warn "WireGuard tunnel  NOT up — egress is not yet routed via the VPS (ST-1)."
    _stealth_stage_wg_template "${apply}"
    stealth_is_strict && hard_fail=1
  fi

  # Best-effort host egress-IP check (no hardcoded home IP: compare to the VPS).
  local expected_vps pub_ip
  expected_vps="$(_sp_expected_vps_ip)"
  if command -v curl >/dev/null 2>&1; then
    pub_ip="$(curl -fsS --max-time 6 https://api.ipify.org 2>/dev/null || true)"
    if [[ -z "${pub_ip}" ]]; then
      _sp_step "egress IP         could not be probed (offline?) — skipping leak check"
    elif [[ "${pub_ip}" == "${expected_vps}" ]]; then
      _sp_ok "egress IP         ${pub_ip} == VPS egress (no home-IP leak)"
    else
      _sp_warn "egress IP         ${pub_ip} is NOT the VPS (${expected_vps}) — HOME-IP LEAK RISK."
      _sp_warn "                  Bring up the WireGuard egress before running live automation."
      [[ "${wg_up}" -eq 1 ]] && stealth_is_strict && hard_fail=1
    fi
  fi

  # 3) Residential proxy config (SOFT) — the a0 patch + discovery escalate onto it.
  local proxy; proxy="$(_sp_residential_proxy)"
  if [[ -n "${proxy}" ]]; then
    _sp_ok "residential proxy configured: ${proxy}"
    if command -v curl >/dev/null 2>&1; then
      if curl -fsS --max-time 5 -x "${proxy}" https://api.ipify.org >/dev/null 2>&1; then
        _sp_ok "residential proxy reachable."
      else
        _sp_warn "residential proxy ${proxy} not reachable yet (needs the VPS tunnel up) — escalation on-block will no-op until it is."
      fi
    fi
  else
    _sp_warn "residential proxy NOT configured — hard anti-bot targets have no residential fallback."
  fi

  if [[ "${hard_fail}" -eq 1 ]]; then
    if stealth_is_strict; then
      _sp_err "Stealth preflight FAILED (strict) — refusing to deploy with a stealth prereq missing."
      _sp_err "Fix the item(s) above, or set APPLICANT_STEALTH_STRICT=false to proceed with warnings."
      return 1
    fi
    _sp_warn "Stealth preflight found MISSING prereq(s) above — proceeding (non-strict)."
    _sp_warn "Applicant may egress the HOME IP until they are fixed. Set APPLICANT_STEALTH_STRICT=true to hard-gate."
  else
    _sp_ok "Stealth prerequisites satisfied."
  fi
  return 0
}

# Stage the WG client config template + print the activation steps (never auto-up:
# it needs an operator-generated private key + a VPS-side [Peer] add).
_stealth_stage_wg_template() {
  local apply="${1:-0}"
  local root="${REPO_ROOT:-.}"
  local tmpl="${root}/scripts/stealth/wg-egress.conf.template"
  local dest="${root}/.stealth/wg-egress.conf.example"
  [[ -f "${tmpl}" ]] || { _sp_step "                  (WG template missing at ${tmpl})"; return 0; }
  if [[ "${apply}" -eq 1 ]]; then
    mkdir -p "${root}/.stealth" 2>/dev/null || true
    cp -f "${tmpl}" "${dest}" 2>/dev/null || true
    _sp_step "                  staged WG config template -> ${dest}"
  fi
  _sp_step "                  setup: scripts/stealth/README.md (generate key -> VPS [Peer] add -> wg-quick up)"
}

# --- Post-build image verification -------------------------------------------
# $1 = apply. Best-effort: after a build, confirm Camoufox (the DEFAULT anti-detect
# browser) is actually baked into applicant/api:latest so live automation launches
# offline instead of silently degrading. Never fatal (the a0 apply-flow browser uses
# the base image's Playwright chromium; camoufox lives in the engine image).
stealth_verify_image() {
  local apply="${1:-0}"
  stealth_is_enabled || return 0
  [[ "${apply}" -eq 1 ]] || return 0
  command -v docker >/dev/null 2>&1 || return 0
  docker image inspect applicant/api:latest >/dev/null 2>&1 || return 0
  if docker run --rm --entrypoint sh applicant/api:latest -c \
       'ls -d /app/.cache/camoufox /app/.local/share/camoufox 2>/dev/null | head -n1' >/dev/null 2>&1; then
    _sp_ok "Camoufox          baked into applicant/api:latest (engine automation browser)."
  else
    _sp_warn "Camoufox          not detected in applicant/api:latest — the engine's DEFAULT"
    _sp_warn "                  BROWSER_ENGINE=camoufox may degrade. Check docker/Dockerfile 'camoufox fetch'."
  fi
  return 0
}
