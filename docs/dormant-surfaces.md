# Dormant Surface Wiring Backlog

Mandated by **FR-UI-2** (§3.19) and the scaffold-and-gray principle (§2): surfaces not yet wired are **grayed out, visually present but dormant** — never shipped as if live. This is the backlog of one stub spec per dormant surface. Each entry states: what it will do, the requirement ID(s) it satisfies, and what "wiring" remains. Backed by the `dormant_surface_backlog` table (§8).

The clone follows the Odysseus design system (FR-UI-1); dormant surfaces are built with the same CSS classes/components but disabled until their backend lands and the wiring is completed.

**Status (post-Phase 4).** As phases landed, surfaces whose backend now exists were switched from grayed to **live** in `src/applicant/dormant.py` (the `status` field) and in the `dormant_surface_backlog` table. The table below tracks each surface; `src/applicant/dormant.py` is the machine-readable source of truth, and `tests/unit/test_phase4_services.py` asserts registry/UI consistency (FR-UI-2).

| Surface | Status | Where it lives |
|---|---|---|
| Resume aggressiveness | **dormant** (grayed by FR-RESUME-9 for MVP-1) | `/debug` (aggressiveness-section) |
| Digest (in-app) | **live** (Phase 1) | `/digest` |
| Redline / revision | **live** (Phase 3) | `/review` |
| Debug surface | **live** (Phase 4) | `/debug` |
| Tool-toggle registry | **live** (Phase 4) | `/debug` (tools-section) |
| Chatbot | **live** (Phase 4) | `/chat` |
| Multi-campaign switcher | **dormant** (grayed for MVP-1; readiness verified) | `/debug` (campaign-switcher-section) |
| Update button | **live** (Phase 4) | `/debug` (update-section) |
| Remote-session takeover | **live** (Phase 2) | remote surface |

---

## 1. Resume aggressiveness / tuning control

- **Surface:** A slider/stepper control on the resume redline/revision surface tuning adaptation aggressiveness toward job-getting potential.
- **What it will do:** Bias generation between conservative (closest to base) and aggressive (maximal reframing) within truthfulness (FR-RESUME-2) and page-fit/template constraints (FR-RESUME-3).
- **Requirement ID(s):** FR-RESUME-9 (explicitly "built but grayed out now; ship a stub spec"); §12 open item.
- **Wiring remaining:** Define the aggressiveness scale, bind it to generation prompts/parameters, persist per campaign, and confirm it never relaxes the truthfulness guardrail. Ungrayed when generation (Phase 3) supports the parameter.

## 2. Digest surface (in-app)

- **Surface:** An in-app rendering of the daily digest table (the digest itself is delivered via email/webpage + Discord and is exempt from the Odysseus style, FR-DIG-2).
- **What it will do:** Show digest rows (summary, link, work mode, fit/viability score, why-suggested, approve/decline-with-feedback) inside the main app.
- **Requirement ID(s):** FR-DIG-1/3/4/5; FR-UI-6.
- **Wiring remaining:** Bind to the DigestReview driving port and the decisions table; reconcile in-app rendering with the style-exempt email/webpage digest. Live once Phase 1 digest lands.

## 3. Redline / revision surface

- **Surface:** The interactive document-editor surface showing additions and subtractions highlighted against the base.
- **What it will do:** Let the user add (free-text instruction), subtract (mark content), or give free-text feedback; the AI revises in the active engine's source and re-renders the redline; approve/decline/revise loop.
- **Requirement ID(s):** FR-RESUME-8; FR-ANSWER-1 (routes through it); FR-NOTIF-4; FR-UI-6.
- **Wiring remaining:** Bind to DocumentReview port, RevisionSession + generated_materials tables, the ResumeTailoring redline renderer, and the review-notification deep link. Live in Phase 3.

## 4. Debug surface

- **Surface:** A dedicated debugging/observability surface.
- **What it will do:** Inspect logs, per-page screenshots, per-application history, and durable-workflow (DBOS) state.
- **Requirement ID(s):** FR-OBS-2; FR-LOG-3; FR-UI-6.
- **Wiring remaining:** Bind to AdminQuery port, structlog/OTel output, application_screenshots, and DBOS workflow-state introspection. Live in Phase 4.

## 5. Tool-toggle registry

- **Surface:** The per-tool on/off panel (Odysseus per-tool pattern).
- **What it will do:** Toggle agent tools: Discovery, Scoring, Pre-fill, Account-Creation, Web-Research, Resume-Tailoring, Cover-Letter-Generation, Screening-Answer-Generation, Chat, Notifications.
- **Requirement ID(s):** FR-UI-4.
- **Wiring remaining:** Bind to the ToolRegistry driven port and tool_settings table; enforce toggles at tool dispatch. Live in Phase 4.

## 6. Chatbot

- **Surface:** The dynamic chat panel.
- **What it will do:** Assist input, dynamically identify gaps, and update attributes/criteria (subject to the integral-change confirmation gate, FR-FB-3).
- **Requirement ID(s):** FR-CHAT-1; FR-FB-2; FR-UI-6.
- **Wiring remaining:** Bind to the Chat driving port, the LLM port, and the attribute/criteria stores with the confirmation gate. Live in Phase 4 (see traceability GAP note for phase placement).

## 7. Multi-campaign switcher

- **Surface:** A campaign selector/switcher (MVP-1 runs a single campaign).
- **What it will do:** Switch between campaigns and clone a campaign's setup once multi-campaign is enabled.
- **Requirement ID(s):** FR-CRIT-4 (multi-ready); NFR-EXT-1; §2 "Campaign-scoped, multi-ready".
- **Wiring remaining:** The schema is already campaign-scoped; remaining work is the CampaignManagement port's multi-campaign operations and the switcher UI binding. Grayed until multi-campaign is enabled (readiness verified Phase 4).

## 8. Update button (in-settings)

- **Surface:** An Update button in settings.
- **What it will do:** Invoke the one-liner update script (DB backup, migrations, rollback support) without SSH/CLI.
- **Requirement ID(s):** FR-OOBE-4 (SHOULD); FR-INSTALL-2.
- **Wiring remaining:** Bind to the UpdateTrigger driving port and the update script. Live in Phase 4.

## 9. Remote-session takeover

- **Surface:** The one-click live remote session view and its takeover/authorize controls.
- **What it will do:** Show the browser the engine is working in; let the user submit themselves or authorize the engine to finish (and complete CAPTCHA/verification).
- **Requirement ID(s):** FR-SANDBOX-2/3; FR-PREFILL-4/5; FR-UI-6.
- **Wiring remaining:** Bind to the RemoteSessionControl driving port and the Sandbox + RemoteView sub-port (Neko default, swappable). Live in Phase 2.

---

**Process rule:** any new surface added to the clone that is not yet wired MUST be added to this backlog and to the `dormant_surface_backlog` table with its requirement IDs and remaining-wiring notes (FR-UI-2). No dead UI ships as if live.
