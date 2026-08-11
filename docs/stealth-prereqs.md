# Stealth prerequisites — what a clean install ships and bakes (EPIC STEALTH)

Principle: **Applicant must never egress from the home WAN IP**, hard anti-bot
targets must exit a **residential** proxy with a matched fingerprint, and the
residential-IP reputation must be conserved. This page documents what the
install/update flow now **ships** and what the a0 image now **bakes** so a clean
`main` deploy is stealthy out of the box. Every stealth value is a **preset
DEFAULT that is changeable** (env / Settings UI).

## Baked into the images
| Prereq | Where it's baked | Detail |
| --- | --- | --- |
| Residential-escalation `_browser` patch | `docker/Dockerfile.a0` → `/a0/plugins/_browser/` | Full-file overlay from `docker/a0-browser-patch/` (config.py + runtime.py + default_config.yaml). The build **grep-asserts** the escalation marker after the COPY, so a clobbered overlay fails the build loudly. Replaces the old hot-patch that was wiped on every rebuild. |
| Camoufox (anti-detect browser) | `docker/Dockerfile` (engine image) | `camoufox fetch` + Firefox runtime libs + Xvfb (headful). The a0 `_browser` apply-flow uses the base image's Playwright chromium; Camoufox is the ENGINE's default automation browser. |
| Real Google Chrome + patchright Chromium | `docker/Dockerfile` | Fallback `BROWSER_ENGINE=chromium` + Proxmox CDP backend. |

## Shipped / verified by the install & update scripts
`scripts/install.sh` and `scripts/update.sh` run a shared stealth preflight
(`scripts/lib/stealth-preflight.sh`) that ships/verifies the **host-level**
prerequisites and **fails loudly** when one is missing while stealth is enabled:

1. **WireGuard client** (`wg` + `wg-quick`) — apt-installed on `--apply`/`--update`
   when missing (`APPLICANT_STEALTH_SKIP_WG_INSTALL=1` to skip).
2. **VPS egress routing** — checks a tunnel is up and (best-effort, no hardcoded
   home IP) that the host's public IP **is the VPS**, not something else
   (home-IP-leak canary). Stages the WG config template + prints the steps if not.
3. **Residential proxy** — confirms the forwarder is configured
   (`A0_BROWSER_RESIDENTIAL_PROXY` / `EGRESS_PROXY`, default `http://10.8.0.1:8880`)
   and best-effort reachable.
4. **Camoufox** — after a build, best-effort confirms the binary baked into
   `applicant/api:latest`.

`--doctor` runs the same preflight **read-only** (diagnoses a leak; never installs
or aborts).

### Controls (env; all defaulted)
| Var | Default | Effect |
| --- | --- | --- |
| `APPLICANT_STEALTH_ENABLED` | `true` | Master switch for the preflight. |
| `APPLICANT_STEALTH_STRICT` | `false` | When `true`, a missing **hard** prereq (no WireGuard client, or an active tunnel whose egress isn't the VPS) **aborts** the install/update. Turn on once ST-1 is wired so a home-IP-leak regression can never deploy silently. |
| `APPLICANT_STEALTH_SKIP_WG_INSTALL` | `false` | Don't apt-install WireGuard. |
| `A0_BROWSER_RESIDENTIAL_PROXY_ENABLED` | `true` | a0 browser residential escalation on/off (compose → the baked patch). |
| `A0_BROWSER_RESIDENTIAL_PROXY` | `http://10.8.0.1:8880` | Residential forwarder endpoint. |
| `WG_VPS_ENDPOINT` | `173.254.204.32:51820` | Expected VPS egress (used by the leak canary + the WG template). |

## One-time host setup (ST-1)
The VPS-side `[Peer]` add + this host's private key are operator steps (secrets
never live in the repo). Full walkthrough: `scripts/stealth/README.md`. Summary:
generate a keypair → send the public key to the VPS operator → render
`scripts/stealth/wg-egress.conf.template` with the returned VPS pubkey/endpoint +
your peer address → `wg-quick up` → confirm `curl https://api.ipify.org` returns
the VPS IP → apply the Docker source-policy-routing so LAN/SSH/local-model stay
direct.

## Related
- `docker/a0-browser-patch/README.md` — the baked browser patch + base-digest coupling.
- `scripts/stealth/README.md` — the WireGuard egress setup.
- Obsidian: [[VPS Egress Node]], [[Camoufox Install]], and the EPIC STEALTH section
  of `docs/APPLICANT-BACKLOG.md`.
