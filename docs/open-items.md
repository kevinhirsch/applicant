# Open Items (defaults in place — non-blocking)

Source: master spec §12. Per the engineering mandate, any new ambiguity is recorded here with a **recommended default**, never silently decided. Defaults are in place so none of these block implementation.

## From §12 (verbatim defaults)

| Item | Default / status |
|---|---|
| **Codename** | Placeholder **Applicant**; rename cascades everywhere. |
| **Resume aggressiveness tuning** | Deferred: optimize for job-getting potential now; ship the UI control **grayed out** with a stub spec (FR-RESUME-9). See [dormant-surfaces.md](dormant-surfaces.md) #1. |
| **Resume-fit "badly" threshold** and **viability threshold** | Default **≥70**, configurable (FR-RESUME-7, FR-AGENT-3). |
| **Quiet hours** | Errors always immediate; approvals/digests respect optional quiet hours unless 24/7 (FR-NOTIF-5). |
| **Resolved through v4** | Durable engine = DBOS; deployment = Proxmox VM; per-campaign attribute cloud; resume feedback/revision engine; resume fidelity via font subsystem + embedded-font PDF/docx; full zero-CLI OOBE wizard + in-UI Update button; screening-answer generation with review; pending-actions portal; EEO stored-answers policy; single-campaign MVP-1 with multi-campaign-ready architecture; both credential-banking modes; Workday-ready onboarding; master aggregator in wave one. |

## Newly-discovered ambiguity (recorded per §12)

### Odysseus UI license — RESOLVED (vendored from owner's MIT fork)

- **Original ambiguity:** The §5 stack table and §5.1 reference list state the Odysseus UI source is **MIT** and instruct vendoring its `static/` "under MIT with notice preserved" (FR-UI-1). On inspection, the **upstream** `pewdiepie-archdaemon/odysseus` repo's own LICENSE + README declared **AGPLv3**, not MIT — so the original vendoring picked up AGPL assets, contradicting the spec.
- **Resolution (2026-06):** The owner provided two **MIT-licensed forks they own** of the Odysseus design system, and `frontend/static/` was **re-vendored from those** in place of the AGPL upstream:
  - **orwell** (MIT, Copyright (c) 2026 kevinhirsch) — base of the vendored set: `style.css` (closest to canonical), `app.js`, `index.html`, `login.html`, `manifest.json`, `sw.js`, the `js/` shell + design-system modules, `lib/`, `fonts/` (incl. `fonts/custom/GohuFont.ttf`), `css/`, icons.
  - **firehouse** (MIT, Copyright (c) 2025 Firehouse Contributors) — same UI family, available for any design-system module orwell trims that the shell/our surfaces need.
  - The AGPL `pewdiepie-archdaemon/odysseus` repo is now used as a **reference only** (to confirm the canonical class/module/asset set); no file is copied from it.
- **Effect:** `frontend/static/LICENSE` is now the **MIT** text from the orwell fork; `THIRD_PARTY_LICENSES.md` records the UI as MIT with no network-copyleft obligation. The spec's §5/§5.1 "Odysseus is MIT" statements are now accurate for the vendored material.
- **Status:** **RESOLVED.** Vendored UI is MIT; no AGPL obligation remains for the UI subtree.
