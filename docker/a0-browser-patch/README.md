# a0 `_browser` residential-proxy escalation patch (image-baked)

These three files are a **full-file overlay** of the upstream Agent Zero
`_browser` core plugin, carrying the selective **residential-proxy escalation**
behaviour (EPIC STEALTH / ST-3). `docker/Dockerfile.a0` COPYs them onto
`/a0/plugins/_browser/` at build time so the patch is **baked into the
`applicant/a0:latest` image** and survives container recreation / image rebuilds
— replacing the old hot-patch (`~/agent-zero-ops/browser-proxy-patch/deploy.sh`)
that had to be re-`docker cp`'d after every rebuild (the standing TODO).

## What it does
- Normal browsing → the **default egress lane** (no proxy; on the deployed host
  that lane is the VPS WireGuard egress `173.254.204.32`, see ST-1).
- On a **hard block** — HTTP `403 / 429 / 503`, or a page signature (Cloudflare
  "just a moment" / "attention required", DataDome, `captcha-delivery`, "access
  denied", "verify you are human") — the runtime relaunches its Playwright
  context through the **DataImpulse residential forwarder** and re-navigates.
- Escalation is **sticky for the runtime's lifetime** (browse → open-role →
  apply share ONE residential IP) and attempted **at most once per runtime**;
  a failed relaunch falls back to a plain context (no crash).
- WebRTC IP leak is suppressed on the proxied context
  (`--force-webrtc-ip-handling-policy=disable_non_proxied_udp`).

## Preset DEFAULTS (all changeable in the Settings UI / via env)
`default_config.yaml` ships:
- `residential_proxy_enabled: true`
- `residential_proxy_server: "http://10.8.0.1:8880"` (the VPS tunnel forwarder)

Env overrides (surfaced in `docker/docker-compose.prod.yml`, a0 service) win:
- `A0_BROWSER_RESIDENTIAL_PROXY_ENABLED` (default `true`)
- `A0_BROWSER_RESIDENTIAL_PROXY` (default `http://10.8.0.1:8880`)

## Files
- `helpers/config.py`  — `get_residential_proxy_config()` + the residential keys.
- `helpers/runtime.py` — proxy at launch (`_start`), block detection +
  escalate/retry in `open`/`navigate`, `_goto` returns the response.
- `default_config.yaml` — documented defaults.

## Provenance & base-digest coupling (IMPORTANT)
Source of truth: `~/agent-zero-ops/browser-proxy-patch/` (built 2026-08-07 by
piloting agent-zero to write the code; see Obsidian [[Piloting Not Coding]] /
[[VPS Egress Node]]). Because `config.py` and `runtime.py` are **full-file
replacements** of the upstream `_browser` plugin, they are pinned to the exact
upstream `_browser` version shipped in the base image that `Dockerfile.a0` builds
`FROM` (the `agent0ai/agent-zero` digest pinned there — v2.4, 2026-07-10).

**When you bump that base digest**, re-reconcile: extract the new base's
`/a0/plugins/_browser/{helpers/config.py,helpers/runtime.py,default_config.yaml}`,
re-apply `~/agent-zero-ops/browser-proxy-patch/patch.diff` onto them, and refresh
these three files — otherwise this frozen copy would clobber upstream `_browser`
changes. The Dockerfile build asserts the escalation marker is present after the
COPY, so a broken overlay fails the build loudly rather than silently shipping an
un-patched browser.
