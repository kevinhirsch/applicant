#!/usr/bin/env bash
#
# Applicant — Proxmox VE one-liner deployer (FR-INSTALL-1, NFR-ZEROCLI-1).
#
# Paste this on a Proxmox VE *node* shell:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/proxmox-deploy.sh)"
#
# Proxmox VE Helper-Scripts style: a whiptail wizard that creates a Debian 12
# LXC container (Docker-ready: unprivileged + nesting), installs Docker, clones
# Applicant, brings up the production Docker Compose stack, runs the database
# migrations, and prints the URL. Everything after that is configured in-browser
# (the OOBE wizard) — zero further CLI.
#
# Re-runnable and safe: it only *creates* a new container; it never deletes data.
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Constants (override via environment if you must)
# ---------------------------------------------------------------------------
REPO_OWNER="${REPO_OWNER:-kevinhirsch}"
REPO_NAME="${REPO_NAME:-applicant}"
REPO_BRANCH="${REPO_BRANCH:-main}"
REPO_URL="https://github.com/${REPO_OWNER}/${REPO_NAME}.git"
APP_NAME="Applicant"
TEMPLATE_PREFIX="debian-12-standard"
APP_PORT="${APP_PORT:-8000}"

# ---------------------------------------------------------------------------
# Pretty output (Helper-Scripts style)
# ---------------------------------------------------------------------------
RD=$'\033[01;31m'; GN=$'\033[1;92m'; YW=$'\033[33m'; BL=$'\033[36m'; CL=$'\033[m'
INFO="${BL}i${CL}"; OK="${GN}OK${CL}"; ERR="${RD}x${CL}"
msg_info() { printf ' %s  %s\n' "$INFO" "$*"; }
msg_ok()   { printf ' %s  %s\n' "$OK" "$*"; }
die()      { printf '\n %s  %s%s%s\n' "$ERR" "$RD" "$*" "$CL" >&2; exit 1; }

header() {
  cat <<'EOF'
    _                _ _                 _
   / \   _ __  _ __ | (_) ___ __ _ _ __ | |_
  / _ \ | '_ \| '_ \| | |/ __/ _` | '_ \| __|
 / ___ \| |_) | |_) | | | (_| (_| | | | | |_
/_/   \_\ .__/| .__/|_|_|\___\__,_|_| |_|\__|
        |_|   |_|   Autonomous job-application engine
EOF
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
header
[[ "$(id -u)" -eq 0 ]] || die "Run this as root on a Proxmox VE node."
command -v pveversion >/dev/null 2>&1 || die "This must run on a Proxmox VE host (pveversion not found)."
command -v pct >/dev/null 2>&1 || die "pct not found — is this a Proxmox VE node?"
if ! command -v whiptail >/dev/null 2>&1; then
  msg_info "Installing whiptail…"; apt-get update -qq && apt-get install -y -qq whiptail
fi
msg_ok "Proxmox VE detected: $(pveversion | head -n1)"

# ---------------------------------------------------------------------------
# Storage discovery helpers
# ---------------------------------------------------------------------------
# Storages that can hold a container rootfs.
mapfile -t ROOTFS_STORES < <(pvesm status -content rootdir 2>/dev/null | awk 'NR>1{print $1}')
[[ ${#ROOTFS_STORES[@]} -gt 0 ]] || die "No storage with 'rootdir' content found. Enable container storage in Datacenter → Storage."
# Storages that can hold CT templates.
mapfile -t TMPL_STORES < <(pvesm status -content vztmpl 2>/dev/null | awk 'NR>1{print $1}')
[[ ${#TMPL_STORES[@]} -gt 0 ]] || die "No storage with 'vztmpl' content (CT templates). Usually 'local'."

pick_default_store() { # prefer local-lvm, then local, then first
  local s; for s in "$@"; do [[ "$s" == "local-lvm" ]] && { echo "$s"; return; }; done
  for s in "$@"; do [[ "$s" == "local" ]] && { echo "$s"; return; }; done
  echo "$1"
}

# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------
NEXTID="$(pvesh get /cluster/nextid 2>/dev/null || echo 100)"
DEF_ROOTFS="$(pick_default_store "${ROOTFS_STORES[@]}")"
DEF_TMPL="$(pick_default_store "${TMPL_STORES[@]}")"

CTID="$NEXTID"; HOSTNAME="applicant"; DISK="16"; CORES="2"; RAM="4096"
BRIDGE="vmbr0"; ROOTFS_STORE="$DEF_ROOTFS"; TMPL_STORE="$DEF_TMPL"; UNPRIV="1"

MODE="$(whiptail --title "$APP_NAME deploy" --menu \
  "Create a Docker-ready LXC and deploy $APP_NAME.\nChoose a setup mode:" 15 70 2 \
  "default"  "Use sensible defaults (recommended)" \
  "advanced" "Customize CTID, resources, storage, network" \
  3>&1 1>&2 2>&3)" || die "Cancelled."

if [[ "$MODE" == "advanced" ]]; then
  CTID="$(whiptail --inputbox "Container ID (CTID)" 8 60 "$CTID" --title "CTID" 3>&1 1>&2 2>&3)" || die "Cancelled."
  HOSTNAME="$(whiptail --inputbox "Hostname" 8 60 "$HOSTNAME" --title "Hostname" 3>&1 1>&2 2>&3)" || die "Cancelled."
  CORES="$(whiptail --inputbox "CPU cores" 8 60 "$CORES" --title "Cores" 3>&1 1>&2 2>&3)" || die "Cancelled."
  RAM="$(whiptail --inputbox "RAM (MB)" 8 60 "$RAM" --title "Memory" 3>&1 1>&2 2>&3)" || die "Cancelled."
  DISK="$(whiptail --inputbox "Root disk (GB)" 8 60 "$DISK" --title "Disk" 3>&1 1>&2 2>&3)" || die "Cancelled."
  BRIDGE="$(whiptail --inputbox "Network bridge" 8 60 "$BRIDGE" --title "Bridge" 3>&1 1>&2 2>&3)" || die "Cancelled."
  # Storage pickers
  rs_args=(); for s in "${ROOTFS_STORES[@]}"; do rs_args+=("$s" ""); done
  ROOTFS_STORE="$(whiptail --title "Root filesystem storage" --menu "Where to place the container disk:" 15 60 6 "${rs_args[@]}" 3>&1 1>&2 2>&3)" || die "Cancelled."
  ts_args=(); for s in "${TMPL_STORES[@]}"; do ts_args+=("$s" ""); done
  TMPL_STORE="$(whiptail --title "Template storage" --menu "Where the Debian template lives:" 15 60 6 "${ts_args[@]}" 3>&1 1>&2 2>&3)" || die "Cancelled."
  if whiptail --title "Privilege" --yesno "Use an UNPRIVILEGED container? (recommended)" 8 60; then UNPRIV="1"; else UNPRIV="0"; fi
fi

whiptail --title "Confirm" --yesno \
"Create CT ${CTID} (${HOSTNAME})
  cores=${CORES}  ram=${RAM}MB  disk=${DISK}G
  rootfs=${ROOTFS_STORE}  bridge=${BRIDGE}  unprivileged=${UNPRIV}
and deploy ${APP_NAME} from ${REPO_OWNER}/${REPO_NAME}@${REPO_BRANCH}?" 13 70 || die "Cancelled."

# ---------------------------------------------------------------------------
# Resolve / download the Debian 12 template
# ---------------------------------------------------------------------------
msg_info "Resolving Debian 12 template…"
pveam update >/dev/null 2>&1 || true
TEMPLATE="$(pveam available -section system 2>/dev/null | awk -v p="$TEMPLATE_PREFIX" '$2 ~ p {print $2}' | sort -V | tail -n1)"
[[ -n "$TEMPLATE" ]] || die "Could not find a ${TEMPLATE_PREFIX} template via pveam."
if ! pveam list "$TMPL_STORE" 2>/dev/null | grep -q "$TEMPLATE"; then
  msg_info "Downloading $TEMPLATE to $TMPL_STORE…"
  pveam download "$TMPL_STORE" "$TEMPLATE" >/dev/null || die "Template download failed."
fi
TEMPLATE_REF="${TMPL_STORE}:vztmpl/${TEMPLATE}"
msg_ok "Template ready: $TEMPLATE"

# ---------------------------------------------------------------------------
# Create + start the container (Docker-ready: nesting + keyctl)
# ---------------------------------------------------------------------------
CT_PASS="$(openssl rand -base64 18 2>/dev/null || head -c18 /dev/urandom | base64)"
msg_info "Creating LXC ${CTID}…"
pct create "$CTID" "$TEMPLATE_REF" \
  --hostname "$HOSTNAME" \
  --cores "$CORES" --memory "$RAM" --swap 512 \
  --rootfs "${ROOTFS_STORE}:${DISK}" \
  --net0 "name=eth0,bridge=${BRIDGE},ip=dhcp" \
  --features "nesting=1,keyctl=1" \
  --unprivileged "$UNPRIV" \
  --onboot 1 \
  --password "$CT_PASS" \
  --description "Applicant — autonomous job-application engine" >/dev/null \
  || die "pct create failed."
msg_ok "Container ${CTID} created."

msg_info "Starting container…"
pct start "$CTID" >/dev/null || die "pct start failed."

# Wait for networking (DHCP lease).
msg_info "Waiting for network…"
IP=""
for _ in $(seq 1 30); do
  IP="$(pct exec "$CTID" -- bash -c "hostname -I 2>/dev/null | awk '{print \$1}'" 2>/dev/null || true)"
  [[ -n "$IP" ]] && break
  sleep 2
done
[[ -n "$IP" ]] || die "Container did not obtain an IP. Check the bridge ($BRIDGE)."
msg_ok "Container IP: $IP"

# ---------------------------------------------------------------------------
# Deploy Applicant inside the container
# ---------------------------------------------------------------------------
DB_PASS="$(openssl rand -base64 24 2>/dev/null | tr -d '/+=' | cut -c1-24)"

run_in_ct() { pct exec "$CTID" -- bash -lc "$1"; }

msg_info "Installing base packages…"
run_in_ct "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq curl ca-certificates git >/dev/null" \
  || die "apt install failed inside the container."

msg_info "Installing Docker…"
run_in_ct "curl -fsSL https://get.docker.com | sh >/dev/null 2>&1 && systemctl enable --now docker >/dev/null 2>&1" \
  || die "Docker install failed inside the container."

msg_info "Cloning ${REPO_OWNER}/${REPO_NAME}@${REPO_BRANCH}…"
run_in_ct "rm -rf /opt/${REPO_NAME} && git clone --depth 1 --branch ${REPO_BRANCH} ${REPO_URL} /opt/${REPO_NAME} >/dev/null 2>&1" \
  || die "git clone failed inside the container."

msg_info "Building and starting the stack (this can take a few minutes)…"
run_in_ct "cd /opt/${REPO_NAME} && POSTGRES_PASSWORD='${DB_PASS}' APP_URL='http://${IP}:${APP_PORT}' bash scripts/install.sh --apply" \
  || die "Stack bring-up failed. Inspect with: pct exec ${CTID} -- docker compose -f /opt/${REPO_NAME}/docker/docker-compose.prod.yml logs"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
cat <<EOF

$(msg_ok "${APP_NAME} is deployed.")

  ${GN}Open:${CL}        http://${IP}:${APP_PORT}
  ${GN}Container:${CL}   CT ${CTID} (${HOSTNAME})  —  root password: ${CT_PASS}
  ${GN}Next:${CL}        finish the in-browser OOBE wizard (LLM → channels → fonts → onboarding).

  Manage:  pct enter ${CTID}        # shell into the container
           cd /opt/${REPO_NAME} && bash scripts/update.sh --apply   # update later

EOF
