# Release-Readiness Gate — Overview (#859)

## What It Checks

The release-readiness gate (`tests/unit/test_release_readiness.py`) enforces four invariants before releasing a new version of the applicant plugin:

### (a) Proxy-Panel Coherence

Scans `a0-applicant/api/*.py` and `a0-applicant/webui/*.html` to ensure no orphan exists on either side. Every API proxy that has a corresponding WebUI panel must be matched; every WebUI panel that has a corresponding API proxy must be matched. Known asymmetric pairs are documented in `BACKEND_ONLY` and `FRONTEND_ONLY` constants:

- **Backend-only** (no panel): `agent_runs`, `base_resume`, `features`, `hello`, `onboarding`, `pending`, `update_panel`
- **Frontend-only** (no proxy): `activity`, `config`, `help`, `main`, `today`, `update`

### (b) Sidebar Wiring

Reads `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html` and parses every `window.openModal` call. Asserts that every WebUI panel except `config.html` (a settings panel intentionally excluded from the main nav) is reachable from the sidebar, and that no duplicate references exist.

### (c) Theme CSS Loading

Confirms `a0-applicant/webui/applicant-theme.css` exists and is non-empty. Spot-checks `health.html` and `config.html` to verify they load the theme via a `<link>` tag with the expected href.

### (d) plugin.yaml Presence

Checks whether `plugin.yaml` exists at the project root. If missing, the test reports it as **MISSING** (fails). This file is needed for plugin discovery metadata.

## Current Status

| Check | Passes? | Detail |
|-------|---------|--------|
| (a) Proxy-Panel Coherence | ✅ PASS | 31 API proxies, 31 WebUI panels. 7 backend-only + 6 frontend-only documented exceptions. No orphans. |
| (b) Sidebar Wiring | ✅ PASS | 30 of 31 panels wired in sidebar. Only `config.html` excluded. No duplicates. |
| (c) Theme CSS Loading | ✅ PASS | `applicant-theme.css` (7666 bytes) loaded by all 31 panels. Both spot-checks confirmed. |
| (d) plugin.yaml | ❌ MISSING | `plugin.yaml` not found at project root. This must be created for plugin discovery. |

### Action Required

1. **Create `plugin.yaml`** at project root with proper plugin metadata (name, version, description, author, entry points).
2. After creation, re-run the release-readiness gate to confirm all four checks pass.

## Enforcement Point

Single test file: [`tests/unit/test_release_readiness.py`](../tests/unit/test_release_readiness.py)

Run the gate with:
```
cd /a0/usr/projects/applicant
PYTHONPATH=src .venv/bin/pytest tests/unit/test_release_readiness.py -v
```

## References

- Issue: #859
- Plugin API proxies: `a0-applicant/api/`
- WebUI panels: `a0-applicant/webui/`
- Sidebar extension: `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`
- Theme CSS: `a0-applicant/webui/applicant-theme.css`
