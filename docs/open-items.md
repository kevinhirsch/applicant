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

### Front door & UI vendoring — RESOLVED (owner's white-labeled workspace app)

- **Original ambiguity:** §5/§5.1 instruct cloning an **external** UI repo
  (`pewdiepie-archdaemon/applicant`) and vendoring its `static/` "served from our FastAPI
  backend" to satisfy the pixel-perfect-clone requirement (FR-UI-1). On inspection that
  upstream repo's own LICENSE declared **AGPLv3**, not MIT — and, more fundamentally, an
  engine-served clone of a third-party repo is **not** how the product is built.
- **Resolution (as built):** The operator UI is the **owner's own no-build *workspace* web
  app** (`workspace/`), white-labeled as Applicant. It runs as a **separate public service**
  (`applicant-ui` on `${APP_PORT}` → container 7000) in **front of** the engine (internal
  `api:8000`), wired across the bridge (`workspace/src/applicant_engine.py` / `ENGINE_URL`
  one way; the token-gated `workspace/routes/applicant_internal_routes.py` /
  `APPLICANT_INTERNAL_TOKEN` the other). The external repo is **not used** and **no file is
  copied from it**; the engine serves no operator UI. FR-UI-1 ("vendor its `static/`, served
  from our FastAPI, wired to our APIs, extensible") is satisfied by
  **vendoring/white-labeling the owner's workspace app** and wiring it to the engine through
  the proxies — see [architecture.md](architecture.md), [frontend.md](frontend.md), and the
  master-spec [Reconciliation note](spec/master-spec.md#reconciliation-note-front-door--ui-vendoring).
- **Effect:** there is no AGPL obligation from any external UI repo (none is vendored), and
  white-labeling is mandatory: no vendor/persona codename and no `FR-`/`NFR-` jargon in any
  user-facing string — the product is **Applicant**.
- **Status:** **RESOLVED.** The front door is the owner's white-labeled workspace app; the
  engine is internal-only behind it.
