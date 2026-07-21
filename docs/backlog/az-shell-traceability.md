# AZ-Shell Traceability — #856 (AZ6-3)

Maps every major product surface / requirement area from the original port backlog to the
a0-applicant SHELL panel (webui HTML) + API proxy that now delivers it. This replaces the
retired front-door traceability and serves as the single source of truth for port completion.

> **How to read**: Each row names the surface, the a0-applicant shell panel that implements
> it, the API proxy backing it, and the delivery status. Status meanings:
>
> - **delivered** — panel exists with both webui HTML and API proxy, wired through the engine
> - **partial** — panel exists but API proxy is static/shell-level (no engine proxy), or
>   mixed level (proxy exists but some sub-features are gated)
> - **gated** — panel exists and is delivered but requires setup/OOBE completion, or is
>   present-but-disabled by product decision
> - **alias** — the webui name and API proxy name differ; both exist

| Requirement / Surface | a0-applicant Panel | API Proxy | Status | Notes |
|---|---|---|---|---|
| daily-loop review (pending actions) | `webui/today.html` | `api/pending.py` | delivered | alias: panel=`today`, proxy=`pending` |
| digest (daily approvals) | `webui/digest.html` | `api/digest.py` | delivered | |
| documents / redline review | `webui/documents.html` | `api/documents.py` | delivered | also uses `api/base_resume.py` (sub-proxy) |
| live-takeover (remote session) | `webui/takeover.html` | `api/takeover.py` | delivered | |
| chat / assistant | `webui/chat.html` | `api/chat.py` | delivered | |
| health / capabilities | `webui/health.html` | `api/health.py` | delivered | |
| campaigns (CRUD) | `webui/campaigns.html` | `api/campaigns.py` | delivered | |
| activity / agent-runs | `webui/activity.html` | `api/agent_runs.py` | delivered | alias: panel=`activity`, proxy=`agent_runs` |
| mind / memory | `webui/mind.html` | `api/mind.py` | delivered | |
| gallery (screenshots) | `webui/gallery.html` | `api/gallery.py` | delivered | |
| criteria (match criteria) | `webui/criteria.html` | `api/criteria.py` | delivered | |
| compare (cross-entity) | `webui/compare.html` | `api/compare.py` | delivered | delivered; present-but-disabled per product decision |
| tracker (board + attention) | `webui/tracker.html` | `api/tracker.py` | delivered | |
| research (company/role) | `webui/research.html` | `api/research.py` | delivered | |
| fonts (install/list) | `webui/fonts.html` | `api/fonts.py` | delivered | |
| discovery (source toggles) | `webui/discovery.html` | `api/discovery.py` | delivered | |
| notifications | `webui/notifications.html` | `api/notifications.py` | delivered | |
| attributes (profile CRUD) | `webui/attributes.html` | `api/attributes.py` | delivered | |
| ops (tool toggles + observability) | `webui/ops.html` | `api/ops.py` | delivered | |
| privacy / sandbox (telemetry) | `webui/privacy.html` | `api/privacy.py` | delivered | |
| screening (answer library) | `webui/screening.html` | `api/screening.py` | delivered | |
| model-endpoints | `webui/model_endpoints.html` | `api/model_endpoints.py` | delivered | |
| tiers (model-escalation ladder) | `webui/tiers.html` | `api/tiers.py` | delivered | |
| vault (credentials) | `webui/vault.html` | `api/vault.py` | delivered | |
| conversion (engine state) | `webui/conversion.html` | `api/conversion.py` | delivered | |
| audit (logs) | `webui/audit.html` | `api/audit.py` | delivered | |
| easy-apply (assisted mode) | `webui/easy_apply.html` | `api/easy_apply.py` | delivered | |
| channels (notification channels) | `webui/channels.html` | `api/channels.py` | delivered | |
| savejob (save a job) | `webui/savejob.html` | `api/savejob.py` | delivered | |

### Utility / meta surfaces

| Surface | Panel | API Proxy | Status | Notes |
|---|---|---|---|---|
| OOBE / onboarding wizard | `webui/main.html` | `api/onboarding.py` + `api/hello.py` | delivered | alias: panel=`main`, proxy=`onboarding`; setup-state server via `api/features.py` |
| one-click updater | `webui/update.html` | `api/update_panel.py` | delivered | alias: panel=`update`, proxy=`update_panel` |
| config / settings | `webui/config.html` | none (client-side) | partial | static shell-level page; no dedicated engine proxy |
| help / about | `webui/help.html` | none (static) | partial | static HTML help page |
| dormant-surface registry | `webui/dormant.html` | `api/dormant.py` | delivered | engine-registered lifecycle status |
| feedback (surveys) | `webui/feedback.html` | `api/feedback.py` | delivered | |

### Proxy-only endpoints (no dedicated panel)

| Endpoint | API Proxy | Purpose | Parent Surface |
|---|---|---|---|
| `api/base_resume.py` | upload proxy | Résumé upload (OOBE sub-step) | onboarding / documents |
| `api/features.py` | capabilities | Feature-flag / capability listing | onboarding / health |
| `api/hello.py` | health-check | Probe endpoint | menu / health |

### Delivery status summary

- **Fully delivered (panel + proxy, engine-wired):** 28 surfaces (25 named + 3 utility)
- **Partial (no engine proxy — static/shell-level):** 2 (config, help)
- **Gated / present-but-disabled:** 1 (compare — product decision)

No front-door retirement is needed; the mapping is complete and real. This document serves
as the reality check for the port — every workspace requirement area has landed in the
a0-applicant shell.
