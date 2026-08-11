# Stealth prerequisites — host setup (EPIC STEALTH)

`scripts/install.sh` and `scripts/update.sh` run a **stealth preflight**
(`scripts/lib/stealth-preflight.sh`) so a clean deploy is stealthy out of the box:
Applicant must **never egress from the home WAN IP** and hard anti-bot targets
must exit a **residential** proxy with a matched fingerprint. The preflight
ships/verifies the host-level prerequisites and **fails loudly** when one is
missing while stealth is enabled.

Every stealth value is a **preset DEFAULT that is changeable** (env / Settings UI).

## What the install/update preflight does
1. **WireGuard client** (`wg` + `wg-quick`) — installed via apt when missing on a
   `--apply`/`--update` run (skip with `APPLICANT_STEALTH_SKIP_WG_INSTALL=1`).
2. **VPS egress routing** — checks a WireGuard interface is up and (best-effort)
   that outbound traffic exits the VPS, **not** the home IP. If no tunnel is up it
   stages the config template (below) and prints the exact activation steps.
3. **Residential proxy** — confirms the residential forwarder is configured
   (`A0_BROWSER_RESIDENTIAL_PROXY` / `EGRESS_PROXY`, default
   `http://10.8.0.1:8880`) and best-effort reachable.
4. **Camoufox** — reports that the anti-detect browser is **baked into the engine
   image** at build (`docker/Dockerfile`); after a build it best-effort verifies
   the binary is present in `applicant/api:latest`.

### Fail-loud behaviour
- `APPLICANT_STEALTH_ENABLED` (default `true`) — master switch for the preflight.
- Missing prereqs always print a **loud error block**.
- `APPLICANT_STEALTH_STRICT` (default `false`) — when `true`, a missing **hard**
  prereq (WireGuard client absent/uninstallable, or no active VPS egress) **aborts
  the install/update** instead of only warning. Turn this on once ST-1 is wired so
  a regression that would leak the home IP can never deploy silently.

## One-time WireGuard egress setup (ST-1)
The VPS-side `[Peer]` add and this host's private key are operator steps (secrets
never live in the repo):

1. Generate this host's keypair:
   ```
   umask 077; wg genkey | tee /etc/wireguard/egress.key | wg pubkey > /etc/wireguard/egress.pub
   ```
2. Send the **public** key (`/etc/wireguard/egress.pub`) to the VPS operator; they
   add it as a `[Peer]` on the VPS and give you back: the VPS **public key**, the
   VPS **endpoint** (`173.254.204.32:51820`), and your assigned **peer address**
   (e.g. `10.8.0.11/32`).
3. Render the config from the template (placeholders are shell-expanded):
   ```
   export WG_PRIVATE_KEY="$(cat /etc/wireguard/egress.key)" \
          WG_PEER_ADDRESS=10.8.0.11/32 \
          WG_VPS_PUBKEY=<vps-public-key> \
          WG_VPS_ENDPOINT=173.254.204.32:51820
   envsubst < scripts/stealth/wg-egress.conf.template | sudo tee /etc/wireguard/wg0.conf >/dev/null
   sudo chmod 600 /etc/wireguard/wg0.conf
   ```
4. Bring it up and confirm the egress IP flipped to the VPS:
   ```
   sudo wg-quick up wg0
   curl -s https://api.ipify.org    # expect 173.254.204.32, NOT the home IP
   ```
5. Apply the Docker source-policy-routing (container subnets -> table 200 -> wg0;
   LAN `10.0.1.0/24` + local-model + SSH stay DIRECT) per [[VPS Egress Node]], then
   re-run `scripts/install.sh --doctor` (or an update) — the preflight should now
   report the VPS egress green.

See also: `docs/stealth-prereqs.md`, `docker/a0-browser-patch/README.md`
(the baked browser residential-escalation patch), and the Obsidian notes
[[VPS Egress Node]] · [[Camoufox Install]].
