#!/usr/bin/env bash
#
# Applicant — Proxmox VE one-liner deployer (FR-INSTALL-1/3, NFR-ZEROCLI-1).
#
# Paste this on a Proxmox VE *node* shell:
#
#   bash -c "$(curl -fsSL https://raw.githubusercontent.com/kevinhirsch/applicant/main/scripts/proxmox-deploy.sh)"
#
# Proxmox VE Helper-Scripts style: a whiptail wizard that creates a **Proxmox VM**
# (per spec FR-INSTALL-1 — "targeting a Proxmox VM (decided)") from the **Ubuntu
# Server 24.04 LTS** cloud image, presets the root password, AUTO-IMPORTS the node's
# detectable SSH keys, and uses cloud-init to self-provision on first boot: install
# Docker, clone Applicant, bring up the production Docker Compose stack, and run the
# DB migrations. Everything after that is configured in-browser (OOBE) — zero CLI.
#
# A VM (not an LXC) is used deliberately: it matches the spec, gives Docker + the
# browser sandbox clean isolation, and supports the residential-egress posture
# (FR-STEALTH-4). The whole stack ships inside the VM via Compose (FR-INSTALL-3).
#
# The host VM is kept LEAN and HEADLESS (Ubuntu Server, no desktop). The full Ubuntu
# desktop the user takes over (TAKEOVER_DESKTOP: cinnamon default / xfce / gnome) is a
# separate web-streamed CONTAINER, not installed on the host (FR-SANDBOX-2/3).
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
APP_PORT="${APP_PORT:-8000}"
# Ubuntu Server 24.04 LTS (noble) cloud image. The .img is qcow2-format and imports
# cleanly via `qm set ... import-from` just like the old Debian qcow2 did. Override
# with a noble-daily URL if a newer point release is wanted.
CLOUDIMG_URL="${CLOUDIMG_URL:-https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img}"

# ---------------------------------------------------------------------------
# Pretty output
# ---------------------------------------------------------------------------
RD=$'\033[01;31m'; GN=$'\033[1;92m'; BL=$'\033[36m'; CL=$'\033[m'
msg_info() { printf ' %si%s  %s\n' "$BL" "$CL" "$*"; }
msg_ok()   { printf ' %sOK%s %s\n' "$GN" "$CL" "$*"; }
die()      { printf '\n %sx  %s%s\n' "$RD" "$*" "$CL" >&2; exit 1; }

header() {
  cat <<'EOF'
    _                _ _                 _
   / \   _ __  _ __ | (_) ___ __ _ _ __ | |_
  / _ \ | '_ \| '_ \| | |/ __/ _` | '_ \| __|
 / ___ \| |_) | |_) | | | (_| (_| | | | | |_
/_/   \_\ .__/| .__/|_|_|\___\__,_|_| |_|\__|
        |_|   |_|   Autonomous job-application engine — Proxmox VM deploy
EOF
}

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------
header
[[ "$(id -u)" -eq 0 ]] || die "Run this as root on a Proxmox VE node."
command -v pveversion >/dev/null 2>&1 || die "This must run on a Proxmox VE host (pveversion not found)."
command -v qm >/dev/null 2>&1 || die "qm not found — is this a Proxmox VE node?"
for bin in whiptail wget openssl; do
  command -v "$bin" >/dev/null 2>&1 || { msg_info "Installing $bin…"; apt-get update -qq && apt-get install -y -qq "$bin"; }
done
msg_ok "Proxmox VE detected: $(pveversion | head -n1)"

# ---------------------------------------------------------------------------
# Storage discovery
# ---------------------------------------------------------------------------
mapfile -t IMG_STORES  < <(pvesm status -content images   2>/dev/null | awk 'NR>1{print $1}')
mapfile -t SNIP_STORES < <(pvesm status -content snippets 2>/dev/null | awk 'NR>1{print $1}')
[[ ${#IMG_STORES[@]} -gt 0 ]] || die "No storage with 'images' content (VM disks). Enable it in Datacenter → Storage."

pick_default() { local s; for s in "$@"; do [[ "$s" == "local-lvm" ]] && { echo "$s"; return; }; done; \
                 for s in "$@"; do [[ "$s" == "local" ]] && { echo "$s"; return; }; done; echo "$1"; }

# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------
NEXTID="$(pvesh get /cluster/nextid 2>/dev/null || echo 100)"
DEF_IMG="$(pick_default "${IMG_STORES[@]}")"

VMID="$NEXTID"; NAME="applicant"; DISK="16"; CORES="2"; RAM="4096"; BRIDGE="vmbr0"; IMG_STORE="$DEF_IMG"

MODE="$(whiptail --title "$APP_NAME deploy (Proxmox VM)" --menu \
  "Create a Docker-ready Ubuntu Server 24.04 LTS VM and deploy $APP_NAME.\nChoose a setup mode:" 15 70 2 \
  "default"  "Sensible defaults (recommended)" \
  "advanced" "Customize VMID, resources, storage, network" \
  3>&1 1>&2 2>&3)" || die "Cancelled."

if [[ "$MODE" == "advanced" ]]; then
  VMID="$(whiptail --inputbox "VM ID (VMID)" 8 60 "$VMID" --title "VMID" 3>&1 1>&2 2>&3)" || die "Cancelled."
  NAME="$(whiptail --inputbox "VM name" 8 60 "$NAME" --title "Name" 3>&1 1>&2 2>&3)" || die "Cancelled."
  CORES="$(whiptail --inputbox "CPU cores" 8 60 "$CORES" --title "Cores" 3>&1 1>&2 2>&3)" || die "Cancelled."
  RAM="$(whiptail --inputbox "RAM (MB)" 8 60 "$RAM" --title "Memory" 3>&1 1>&2 2>&3)" || die "Cancelled."
  DISK="$(whiptail --inputbox "Disk (GB)" 8 60 "$DISK" --title "Disk" 3>&1 1>&2 2>&3)" || die "Cancelled."
  BRIDGE="$(whiptail --inputbox "Network bridge" 8 60 "$BRIDGE" --title "Bridge" 3>&1 1>&2 2>&3)" || die "Cancelled."
  is_args=(); for s in "${IMG_STORES[@]}"; do is_args+=("$s" ""); done
  IMG_STORE="$(whiptail --title "VM disk storage" --menu "Where to place the VM disk:" 15 60 6 "${is_args[@]}" 3>&1 1>&2 2>&3)" || die "Cancelled."
fi

# ---------------------------------------------------------------------------
# Root password (operator-set) + SSH key auto-import
# ---------------------------------------------------------------------------
# Prompt the operator to SET the VM root password (console + SSH login). Leaving
# it blank generates a strong random one. Confirm on entry to avoid typos.
VM_PASS=""; VM_PASS_SOURCE="set"
while true; do
  VM_PASS="$(whiptail --title "Root password" --passwordbox \
    "Set the root password for VM ${VMID} (console + SSH login).\n\nLeave blank to generate a strong random password." \
    11 70 3>&1 1>&2 2>&3)" || die "Cancelled."
  if [[ -z "$VM_PASS" ]]; then
    VM_PASS="$(openssl rand -base64 18)"; VM_PASS_SOURCE="generated"; break
  fi
  VM_PASS2="$(whiptail --title "Root password" --passwordbox "Confirm the root password:" 9 70 3>&1 1>&2 2>&3)" || die "Cancelled."
  [[ "$VM_PASS" == "$VM_PASS2" ]] && break
  whiptail --title "Root password" --msgbox "Passwords did not match — please try again." 8 60
done

DB_PASS="$(openssl rand -base64 24 | tr -d '/+=' | cut -c1-24)"

SSHKEYS_FILE=""
SSH_TMP="$(mktemp)"
for f in /root/.ssh/authorized_keys /root/.ssh/*.pub /etc/ssh/authorized_keys; do
  [[ -f "$f" ]] && cat "$f" >> "$SSH_TMP" 2>/dev/null || true
done
if [[ -s "$SSH_TMP" ]]; then
  sort -u "$SSH_TMP" -o "$SSH_TMP"; SSHKEYS_FILE="$SSH_TMP"
  msg_ok "Auto-importing $(grep -c . "$SSH_TMP") detectable SSH key(s)."
else
  msg_info "No SSH keys detected on the node; root password login only."
fi

whiptail --title "Confirm" --yesno \
"Create VM ${VMID} (${NAME})
  cores=${CORES}  ram=${RAM}MB  disk=${DISK}G
  disk-storage=${IMG_STORE}  bridge=${BRIDGE}  ip=dhcp
  root password: $([[ "$VM_PASS_SOURCE" == "set" ]] && echo "the one you entered" || echo "generated (shown at the end)")
  SSH keys: $([[ -n "$SSHKEYS_FILE" ]] && echo "auto-imported" || echo "none")
and deploy ${APP_NAME} from ${REPO_OWNER}/${REPO_NAME}@${REPO_BRANCH}?" 14 72 || die "Cancelled."

# ---------------------------------------------------------------------------
# Snippets storage (for cloud-init custom user-data); auto-enable on 'local' if needed
# ---------------------------------------------------------------------------
SNIP_STORE=""
if [[ ${#SNIP_STORES[@]} -gt 0 ]]; then
  SNIP_STORE="$(pick_default "${SNIP_STORES[@]}")"
else
  msg_info "No snippets-capable storage; enabling 'snippets' content on 'local'…"
  CUR="$(pvesh get /storage/local --output-format json 2>/dev/null | grep -oP '"content"\s*:\s*"\K[^"]+' || echo "vztmpl,iso,backup")"
  pvesm set local --content "${CUR},snippets" >/dev/null 2>&1 || die "Could not enable snippets on 'local'. Enable a snippets storage manually."
  SNIP_STORE="local"
fi
SNIP_DIR="$(pvesh get /storage/${SNIP_STORE} --output-format json 2>/dev/null | grep -oP '"path"\s*:\s*"\K[^"]+' || echo "/var/lib/vz")"
mkdir -p "${SNIP_DIR}/snippets"
USERDATA="${SNIP_DIR}/snippets/applicant-${VMID}.yaml"

cat > "$USERDATA" <<EOF
#cloud-config
hostname: ${NAME}
manage_etc_hosts: true
package_update: true
packages: [qemu-guest-agent, ca-certificates, curl, git]
runcmd:
  - systemctl enable --now qemu-guest-agent
  - curl -fsSL https://get.docker.com | sh
  - systemctl enable --now docker
  - git clone --depth 1 --branch ${REPO_BRANCH} ${REPO_URL} /opt/${REPO_NAME}
  - bash -lc 'cd /opt/${REPO_NAME} && POSTGRES_PASSWORD="${DB_PASS}" APP_URL="http://0.0.0.0:${APP_PORT}" bash scripts/install.sh --apply'
  - touch /opt/${REPO_NAME}/.provisioned
EOF
msg_ok "Cloud-init user-data written: ${SNIP_STORE}:snippets/applicant-${VMID}.yaml"

# ---------------------------------------------------------------------------
# Download the Ubuntu Server 24.04 LTS cloud image
# ---------------------------------------------------------------------------
IMG_TMP="$(mktemp --suffix=.img)"
msg_info "Downloading Ubuntu Server 24.04 LTS cloud image…"
wget -qO "$IMG_TMP" "$CLOUDIMG_URL" || die "Cloud image download failed: $CLOUDIMG_URL"
msg_ok "Cloud image downloaded."

# ---------------------------------------------------------------------------
# Create the VM (cloud-init), import the disk, wire networking + ci
# ---------------------------------------------------------------------------
msg_info "Creating VM ${VMID}…"
qm create "$VMID" \
  --name "$NAME" --memory "$RAM" --cores "$CORES" --cpu host \
  --net0 "virtio,bridge=${BRIDGE}" --scsihw virtio-scsi-pci \
  --serial0 socket --vga serial0 --agent enabled=1 --ostype l26 \
  --description "Applicant — autonomous job-application engine" >/dev/null \
  || die "qm create failed."

# Import the cloud image as scsi0 (one-step import-from; PVE 7.2+).
qm set "$VMID" --scsi0 "${IMG_STORE}:0,import-from=${IMG_TMP}" >/dev/null || die "disk import failed."
qm set "$VMID" --ide2 "${IMG_STORE}:cloudinit" --boot order=scsi0 >/dev/null || die "cloudinit drive failed."
qm set "$VMID" --ipconfig0 "ip=dhcp" --ciuser root --cipassword "$VM_PASS" >/dev/null || die "cloud-init net/user failed."
[[ -n "$SSHKEYS_FILE" ]] && { qm set "$VMID" --sshkeys "$SSHKEYS_FILE" >/dev/null || true; }
qm set "$VMID" --cicustom "user=${SNIP_STORE}:snippets/applicant-${VMID}.yaml" >/dev/null || die "cicustom failed."
qm resize "$VMID" scsi0 "${DISK}G" >/dev/null || die "disk resize failed."
qm set "$VMID" --onboot 1 >/dev/null || true
msg_ok "VM ${VMID} created."

rm -f "$IMG_TMP" "$SSH_TMP" 2>/dev/null || true

msg_info "Starting VM…"
qm start "$VMID" >/dev/null || die "qm start failed."

# ---------------------------------------------------------------------------
# Wait for the guest agent + IP (cloud-init installs the agent, then provisions).
# Provisioning (apt + docker build) can take several minutes on first boot.
# ---------------------------------------------------------------------------
msg_info "Waiting for the VM to boot and self-provision (this can take several minutes)…"
IP=""
for _ in $(seq 1 90); do
  IP="$(qm guest cmd "$VMID" network-get-interfaces 2>/dev/null \
        | grep -oP '"ip-address"\s*:\s*"\K[0-9.]+' | grep -v '^127\.' | head -n1 || true)"
  [[ -n "$IP" ]] && break
  sleep 5
done

cat <<EOF

$([[ -n "$IP" ]] && msg_ok "${APP_NAME} VM is up." || msg_info "VM created; still provisioning.")

  ${GN}VM:${CL}            ${VMID} (${NAME})
  ${GN}Root password:${CL} $([[ "$VM_PASS_SOURCE" == "set" ]] && echo "(the password you set)" || echo "${VM_PASS}")
EOF
if [[ -n "$IP" ]]; then
cat <<EOF
  ${GN}Open:${CL}          http://${IP}:${APP_PORT}   (allow a few minutes for the first build)
  ${GN}Next:${CL}          finish the in-browser OOBE wizard (LLM → channels → fonts → onboarding).

  Watch first-boot provisioning:
    qm guest exec ${VMID} -- tail -n40 /var/log/cloud-init-output.log
EOF
else
cat <<EOF
  The guest agent isn't reachable yet (first-boot provisioning installs it).
  Find the IP from your router/DHCP or:  qm guest cmd ${VMID} network-get-interfaces
  Then open http://<vm-ip>:${APP_PORT} once the stack finishes building.
EOF
fi
echo
echo "  Update later:  qm guest exec ${VMID} -- bash -lc 'cd /opt/${REPO_NAME} && bash scripts/update.sh --apply'"
echo

# ---------------------------------------------------------------------------
# Live-follow first-boot provisioning over SSH (no copy/paste, auto-stops)
# ---------------------------------------------------------------------------
# Stream the cloud-init log to THIS terminal in real time until provisioning
# finishes (cloud-init touches /opt/${REPO_NAME}/.provisioned at the end), then
# stop on its own. Set NO_FOLLOW=1 to skip. Uses the IP discovered above — no
# hardcoded address. SSH auth uses the auto-imported key, else the root password
# you just set.
if [[ -n "$IP" && "${NO_FOLLOW:-0}" != "1" ]]; then
  echo "  Following first-boot provisioning live (Ctrl-C to detach; it stops itself when done)…"
  echo
  # Wait briefly for sshd to come up on the freshly booted VM.
  for _ in $(seq 1 30); do
    ssh -o ConnectTimeout=4 -o StrictHostKeyChecking=accept-new \
        -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        "root@${IP}" true 2>/dev/null && break
    sleep 3
  done
  ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
      "root@${IP}" \
      "tail -n +1 -F /var/log/cloud-init-output.log & TP=\$!; \
       until [ -f /opt/${REPO_NAME}/.provisioned ] || grep -q 'Cloud-init.*finished' /var/log/cloud-init-output.log 2>/dev/null; do sleep 2; done; \
       sleep 2; kill \$TP 2>/dev/null" 2>/dev/null || \
    echo "  (Could not auto-attach over SSH — run: ssh root@${IP} 'tail -f /var/log/cloud-init-output.log')"
  echo
  msg_ok "Provisioning finished. Open http://${IP}:${APP_PORT} and complete setup in the browser."
fi
