# Agent Zero Port — Full-Functionality Parity Map & Road-to-Closure Backlog

> **Status: strategy backlog, refined from six file-grounded inventories** (spec FR/NFR families,
> front-door surfaces + OOBE, engine API/bridge, launch gates + backlog conventions, the vendored
> agent-zero fork at `/workspace/agent-zero` @ `d1d48bc` (tracks upstream v1.3), and the general
> workspace surfaces). Companion to [`../agent-zero-plane-map.md`](../agent-zero-plane-map.md)
> (planes, updateability discipline, safety line). Story format mirrors
> [`road-to-market.md`](road-to-market.md): index table + `As/I want/so that`, Effort
> `S = hours · M = 1–2 days · L = 3+ days`, Owner `eng/you/both`, DoR/DoD checkboxes,
> Status `— → IN PROGRESS → DONE / PARTIAL`.
>
> **Owner's DoD:** an Agent Zero + Applicant **monorepo**; the product **feels like Applicant out
> of the box** (core functions present, OOBE gathers the same mandatory information); upstream
> agent-zero stays **update-able**.
>
> The fully-formed product experience (rebrand spec, guided setup screen-by-screen, daily
> journeys, notifications, integrations, interactability/desktop) is
> [`../design/agent-zero-user-journey.md`](../design/agent-zero-user-journey.md).

## 0. What it takes — the honest answer up front

The port is **one plugin bundle, one branding overlay, one companion-service decision, and a long
tail of surface parity** — the engine does not move:

1. **The "additional add-on platform" already exists: it is the engine.** All 37 engine routers,
   ~188 bridge operations, the safety gates, and the 24/7 loop stay exactly where they are. Agent
   Zero never re-implements them; it *renders* them.
2. **All Applicant product behavior lands as ONE additive plugin bundle** (+ an agent profile +
   prompt overlays + MCP registration + a branding overlay). Agent-zero's own onboarding ships as
   a plugin (`plugins/_onboarding/`, model-gate pattern), so the Applicant OOBE follows first-party
   precedent — no upstream edits.
3. **Three general workspace services are load-bearing** (calendar, email inbox, deep research —
   the engine's callback lanes) and must survive the shell swap; the recommended path keeps the
   existing workspace app running headless as an internal "companion services" container initially
   (zero regression), with optional later ports.
4. **Closure = the same bars the current product passes**: H1–H5 honesty invariants, the
   dormant-surface no-dead-UI gating, the playtest §10 golden-path ship gate, both white-label
   checks, and PAG-1 re-run on the new shell — plus two port-specific bars: the **bypass negative
   test** (the general agent's own browser/shell cannot complete an application around the engine)
   and the **updateability proof** (a subtree pull round-trips clean after everything lands).

Rough sequencing weight (details in §4): Phase 0 foundations ≈ 1 wk · Phase 1 OOBE ≈ 1–2 wk ·
Phase 2 daily loop ≈ 2–3 wk · Phase 3 full surface parity ≈ 3–5 wk (the long tail) · Phase 4
companion services ≈ 1 wk · Phase 5 safety proofs ≈ 1–2 wk · Phase 6 ship gate ≈ 1–2 wk.

## 1. Definition of Closed (inherited gates + port-specific gates)

Closure is **all** of the following, verified on the A0-shelled product:

- [ ] **Universal DoR (4) + Universal DoD (6)** from `road-to-market.md` apply to every story
      below (reachable-in-the-shipped-UI, green increment, white-label, regression test,
      server-side safety, focused PR).
- [ ] **H1–H5 re-proven on the new shell**: receipts-not-narration (H1), no silent underdelivery
      (H2), full-fidelity review (H3 — literal payload, byte-identical promote), visible
      provenance (H4), calibrated copy (H5, incl. the overclaim denylist over the plugin's UI
      strings).
- [ ] **Four-state feature gating** (`active/configured/locked/disabled`) driven by the engine's
      `setup-status` + dormant-surface registry — no dead UI in the A0 shell.
- [ ] **Playtest protocol adapted and green**: §6 contract sweep, §6a monkey/crawl run-until-green
      against the A0 webui, §10 golden path G1–G9 (incl. G6 "no engine self-submit").
- [ ] **Safety negative test**: a general-agent computer-use session cannot complete ATS login,
      form fill, upload, or submission around the engine (blocked and surfaced).
- [ ] **White-label**: repo greps green + the fail-closed branded-artifact check green (see
      plane map); zero agent-zero identifiers on the shipped surface.
- [ ] **Updateability proof**: `scripts/vendor-sync.sh` pulls a newer upstream agent-zero with
      zero conflicts in Applicant-owned paths; gates re-run green.
- [ ] **Instructions gate**: every feature carries workable on-surface instructions, verified by
      completing each feature's task using only them (journey blueprint §8).
- [ ] **PAG-1 re-run** (owner dogfood on the new shell) — the final bar, exactly as in Phase 1.5.

## 2. Target architecture (refines the plane map)

Compose stack: **`a0`** (public UI shell — Alpine.js webui + Flask/ASGI, Socket.IO) · **`api`**
(engine, unchanged, internal) · **`companion`** (the current workspace app, demoted to headless
internal service for lanes A–D; no public port) · `postgres` · `searxng` · `chromadb` · `ntfy`
(+ optional `takeover-desktop`). The engine's callback (`WORKSPACE_URL`,
`APPLICANT_INTERNAL_TOKEN`) now points at `companion` — **unchanged code, changed audience**.

**The Applicant product layer** (all additive, per the A0 inventory):

| Piece | Mechanism (file-grounded) |
|---|---|
| OOBE + all UI panels | one plugin (`applicant`) — `plugin.yaml`, `api/`, `webui/`, `extensions/webui/<breakpoint>/` into the ~60 `x-extension` points (sidebar, welcome cards, chat top, right-canvas panels, settings subsections via `settings_sections`) |
| Engine access | plugin `api/` handlers proxying the engine (server-side, owner/internal-token pattern) + the engine registered in A0's `mcp_servers` setting **over a real MCP transport**: the engine's SSE endpoint at `/mcp` — which mounts only with the optional `mcp` extra (`fastapi_mcp`), so **baking `uv sync --extra mcp` into the engine image becomes a deploy prerequisite of AZ0-6** — or a thin `stdio` adapter bridging A0's client to the native JSON `/mcp/tools` surface. (`/mcp/tools` alone is plain JSON, not an MCP transport; A0's client speaks `stdio`/`sse`.) Default-deny on consequential actions holds on every transport — it is enforced in the engine's tool handlers, not the transport layer |
| Agent behavior | agent profile `agents/applicant/agent.yaml` + prompt overlays (job-search role, hard "never apply directly — use the engine capability" instructions; **guidance only** — enforcement stays server-side) |
| Background cadence | A0's cron scheduler (`helpers/task_scheduler.py`) only for *shell-side* refresh; the 24/7 apply loop **stays in the engine's durable scheduler** |
| Branding | build-time overlay: swap `webui/public/*` assets + `<title>`/`manifest.json` name; fail-closed artifact check in CI |

**D6 — DECIDED: both Applicant-owned artifacts live out-of-tree.** `a0-applicant/` (the plugin
bundle) is `COPY`-ed into the image at `/a0/usr/plugins/applicant`, and `a0-webui/` (the bespoke
UI, a managed fork of `webui/` per D1) is applied over the pristine tree in the same build step.
The subtree stays 100 % byte-pristine — framework pulls stay trivially clean; upstream UI changes
are cherry-picked into `a0-webui/` with clear provenance. (Supersedes the plane map's
in-subtree-additions sketch.)

## 3. Parity matrix — every surface, its target home

Legend — **Target**: `A0-native` (exists, use as-is) · `plugin` (Applicant plugin UI/API) ·
`engine` (unchanged, called) · `companion` (workspace headless service) · `drop` (not carried).
**Phase** = the epic (§4) that lands it.

### 3.1 OOBE & setup (the "same mandatory information out of the box" bar)

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Connect-a-model (hard gate, `llm_configured`) | A0-native + plugin | A0's model gate + `_onboarding` already collect provider/key/local; a plugin hook syncs the chosen config into the engine (`POST /setup/llm`) so the engine gate opens from the same act. Decision **D2** picks the source of truth | 1 |
| 2 | Model-escalation tier ladder (1–5 tiers) | plugin | settings subsection → engine `/setup/llm/tiers`; A0's LiteLLM layer is NOT the ladder — the engine keeps escalation | 3 |
| 3 | Profile intake — 12 resumable sections (base_resume → identity → work_auth → location → target_roles → criteria → compensation → work_history → education → key_attributes → eeo → references) | plugin | Applicant OOBE panel following `_onboarding` precedent, driving `/setup/onboarding/{campaign}/section` per section, resumable via `sections_complete[]` | 1 |
| 4 | Base-résumé upload + parse-verify "double-check" line + font detect + LaTeX preview accept/reject | plugin | `/base-resume` upload → engine parse-verify metadata rendered honestly (H-series); conversion preview/accept/reject via `/api/conversion` | 1 |
| 5 | `apply_ready` gating (server-computed `apply_missing[]`: name/email/phone/title + criteria) | engine + plugin | plugin renders the engine's truth ("You're all set" / "Almost ready: …"); agent profile defers automated work until ready; enforcement stays engine-side | 1 |
| 6 | Notification channels + quiet hours (Settings, not gate) | plugin | settings subsection → `/setup/channels`, test-send; outbound fan-out stays the **engine's** Apprise ladder (D5) | 3 |
| 7 | Fonts manager (Settings) | plugin + engine | engine `/api/fonts` (detect/install); UI as settings subsection | 3 |
| 8 | Sandbox connection + automation prefs (~20 knobs) | plugin | settings subsection → `/setup/sandbox`, `/setup/automation` | 3 |
| 9 | Setup-status single source of truth | engine | unchanged; the plugin's gating layer reads it (see 3.7 #1) | 1 |

### 3.2 Home base & notification center

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Pending-Actions **Portal** (post-login home + notification center; answer/review/fix/open-live/digest-decision affordances) | plugin | primary panel — sidebar entry + welcome-screen card via `x-extension`; feeds from `/portal/pending`; pairs with A0's notification center for toasts/badges | 2 |
| 2 | "Today" one-decision-at-a-time lens | plugin | same `/portal/pending` data, alternate lens — port after Portal | 3 |
| 3 | Notification bell + count badge | A0-native + plugin | map onto A0's notification center + toast stack (`components/notifications/`); plugin posts via `NotificationManager` | 2 |
| 4 | Gadget rail (Waiting-on-you / Pipeline / Recent activity) | plugin | right-canvas or sidebar-bottom breakpoint injections; defer if noisy | 3 |
| 5 | Job-search nav (single-source array → rail + sidebar) | plugin | one sidebar section injection listing Applicant destinations; A0 chats/tasks lists stay native | 2 |
| 6 | Realtime updates (front-door WS multiplexed channels) | A0-native | A0's Socket.IO state sync + poll fallback replaces `applicantRealtime.js`; plugin pushes over `webui_ws_*` extension hooks | 2 |
| 7 | Global shortcuts overlay, campaign switcher, demo banner | plugin | small injections; switcher embeds in plugin panel headers | 3 |

### 3.3 The daily loop

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Daily digest (matched roles; open/approve/pass-with-reason/feedback) | plugin | digest panel from `/api/digest`; approve/decline through engine; email delivery stays engine-side | 2 |
| 2 | Feedback loop (freetext/survey; decline-with-reason) | plugin | inline in digest/portal panels → `/api/feedback` | 2 |
| 3 | Job Assistant chat (job-action chips, guardrail hints) | A0-native + plugin | **the deepest UX decision (D8)**: A0's chat IS the product's chat. The applicant agent profile + engine-backed tools (`usr` tools calling `/api/chat` or MCP) give job context; chips/hints via chat-input breakpoints | 2 |
| 4 | Save-a-job from any page (intake URL) | plugin + A0-native | a `usr` tool + a chat affordance → engine `/api/intake` | 3 |

### 3.4 Documents, review & truth surfaces (H3/H4 live here)

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Documents library (résumé/cover-letter variants, per-application) | plugin | right-canvas panel (A0's cowork/document surface) over `/api/documents` | 2 |
| 2 | **Redline review** (add/subtract/free-text change-and-review loop) | plugin | the core review surface; render_redline/turn/approve/decline; deep-linked from Portal/digest | 2 |
| 3 | **H3 full-fidelity pre-submit snapshot** (literal payload, byte-identical promote) | plugin + engine | ONE exported renderer used by every submit surface in the plugin — same rule as today | 2 |
| 4 | **H4 provenance** ("Where this came from" per line; unsourced = flagged) | plugin | `/documents/{id}/provenance` panel; failed check renders "couldn't check", never fake-clean | 2 |
| 5 | Screening answers + library + reuse; deferred essays; interview prep | plugin | panels/actions over the documents domain | 3 |
| 6 | Aggressiveness control (ships grayed) | plugin | preserve as present-but-disabled (dormant registry) | 3 |

### 3.5 Live sessions, stop boundary & credentials

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Live remote view / takeover (iframe embed of engine sandbox view-url) | plugin | panel embedding `remote_session_view_url`; A0's own browser canvas is NOT used for this (it must never touch real applications — §1 negative test) | 2 |
| 2 | **Final-submit stop boundary** ("Submit it for me" / "I submitted it myself" — the only client authorize paths) | plugin + engine | exact port of the two-affordance boundary; engine `ensure_submittable` + review gate unchanged | 2 |
| 3 | Account-step / 2FA push-poll / detection-step resume; emergency handoff | plugin | portal-item affordances → `/api/remote/*` resume endpoints | 2 |
| 4 | Credential vault (per-tenant sign-ins; capture offer; never shows secrets) | plugin | modal/panel over `/api/credentials`; libsodium storage stays engine-side | 3 |
| 5 | Desktop assist (ships dormant/grayed) | plugin | preserve dormant state via registry | 3 |
| 6 | Easy Apply assisted mode (consent-gated) | plugin | consent + brief over `/api/easy-apply` | 3 |

### 3.6 Insight & learning surfaces

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Tracker board (applied → response → interview/offer → rejected/ghosted; record-what-happened) | plugin | panel over `/api/post-submission` + outcomes | 3 |
| 2 | Results funnel + per-source conversion + learned signature | plugin | panel over `/api/outcomes` read-model | 3 |
| 3 | Agent activity (status pill + run history) + run controls (run-now/pause/resume, intent) | plugin | status chip via chat-top breakpoint; runs panel over `/api/agent-runs` | 3 |
| 4 | Mind — what the assistant remembers / playbooks / curation approvals | plugin (+ A0-native memory kept separate) | panel over `/api/agent-memory` + mind routes; **A0's own `_memory` plugin stays for general-agent memory — the two stores must not merge** (plane-map plane 7) | 3 |
| 5 | Gallery (screenshots + materials) | plugin | grid panel over `/api/gallery` | 3 |
| 6 | Compare (engine-backed cross-entity diff) | plugin | modal over `/api/compare` | 3 |
| 7 | Capabilities disclosure ("what the assistant can do" = MCP list) | plugin | renders engine `/mcp/tools` honestly (gated 409 until LLM) | 3 |
| 8 | Trust Center (content-only safety consolidation) | plugin | static content panel; H5-audited copy | 3 |
| 9 | Learning playbook apply / learned-criteria apply | plugin | actions in mind/results panels | 3 |

### 3.7 Settings, ops & admin

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | **Feature-state layer** (4-state gating, 14 sections, fail-open nav, never-raise) | plugin | port `applicant_features.py` logic into the plugin backend; drives every plugin panel's locked/active render — **the no-dead-UI keystone** | 2 |
| 2 | Honest health panel (postgres/renderer/browser/orchestrator real-vs-stub) | plugin | settings subsection + Portal banner over `/api/health/capabilities` (H2/H5 anchor) | 2 |
| 3 | Campaign settings (run mode, throughput, exploration, source toggles + yields) | plugin | settings subsection over `/api/campaigns` + discovery-sources | 3 |
| 4 | Debug / Run log (history, screenshots, redacted logs, workflow state, stuck/blocked ops) | plugin | admin panel over the 24 `admin_*` operations; keeps operator override paths reachable | 3 |
| 5 | One-click Update + status | plugin | settings subsection + rail entry over `/api/update` | 3 |
| 6 | Telemetry opt-in (default OFF) | plugin | settings subsection | 3 |
| 7 | Owner data export ("Download my data") | plugin | port of export route against engine + companion data | 3 |
| 8 | Audit-log export | plugin | actions in debug panel | 3 |
| 9 | Global pause / kill-switch | plugin | status-strip control → engine control route | 2 |
| 10 | Auth posture | A0-native | A0 single-user login (`AUTH_LOGIN`) + engine single-tenancy replaces workspace multi-user + `require_engine_owner` (**D4** — accepts losing multi-user; the engine never had it) | 0 |

### 3.8 Engine-load-bearing general surfaces (lanes A–D)

| # | Surface today | Target | Mechanism / notes | Phase |
|---|---|---|---|---|
| 1 | Calendar (lane A: interview read + write-back) | companion | keep workspace calendar + CalDAV headless; engine callback unchanged. Optional later: A0-native calendar does not exist — porting means a plugin calendar or an external CalDAV service | 4 |
| 2 | Email inbox (lane C recent-emails scan; lane D digest UI host) | companion → plugin | IMAP pool + idle watcher stay in companion for the scan lane; the digest UI itself moves to the plugin (3.3 #1) — the *lane* and the *panel* decouple. A0's `_email_integration` plugin is a candidate replacement later (D3) | 4 |
| 3 | Deep research (lane B) | companion | research handler + SearXNG stay; A0's own browser/knowledge is NOT wired into engine research initially (scope discipline) | 4 |
| 4 | Fonts service, model-discovery plumbing, toast host, DOM anchors | plugin / A0-native | engine `/api/fonts` covers fonts (3.1 #7); A0 model config covers discovery (D2); A0 toasts/notification center replace `ui.js showToast`; DOM anchors die with the old shell | 1–3 |
| 5 | Companion lane **configuration UI** (the mailbox/calendar credentials the lanes read — today configured in the retiring workspace Settings) | plugin | Settings → "Email & Calendar for your job search" subsection writes companion config; honest copy about what the lanes do with it (journey blueprint §5) | 3 |

### 3.9 General surfaces NOT carried (and why that's safe)

| Surface | Disposition |
|---|---|
| Cookbook local-model serving + hwfit | already descoped (local-models lane removed end-to-end); A0's local-model path covers the need |
| Compare (general model A/B) | ships present-but-disabled today; **drop** |
| Notes, group chat, gallery/image-editor (~45 files), shell, contacts/CardDAV, general Bitwarden vault, presets, signatures, STT/TTS, personal-docs RAG, webhooks, API tokens | **drop or A0-native** — A0 has its own files/browser/projects/scheduler/skills/memory; none of these back an engine lane. The workspace *documents/memory/chat* shells that lanes render into are replaced by the plugin panels above |
| Workspace multi-user admin (users/privileges/2FA/wipe) | **drop** (D4) — single-operator product; engine was always single-tenant |
| Engine's own built-in static shell (`frontend/static/applicant/`) | keep as-is (internal-only, useful for engine-direct debugging); not part of the public surface |

## 4. Phases & stories (index)

| ID | Story | Effort | Owner | Status |
|---|---|---|---|---|
| **Phase AZ-0 — Foundations** | | | | |
| AZ0-1 | Vendor agent-zero subtree + vendor-sync script + round-trip proof | M | eng | — |
| AZ0-2 | Compose integration: `a0` service joins the stack; `companion` demotion wiring | M | eng | — |
| AZ0-3 | License/attribution ledger (Agent Zero s.r.o. MIT) + THIRD_PARTY/ACKNOWLEDGMENTS rows | S | eng | — |
| AZ0-4 | Branding overlay (assets + name strings) + fail-closed branded-artifact CI check + denylist carve-out | M | eng | — |
| AZ0-5 | Plugin skeleton (`a0-applicant/`) + build-time mount + hello-world panel via `x-extension` | M | eng | — |
| AZ0-6 | **Seam proof**: engine MCP (SSE `/mcp`, `mcp` extra baked into the image — or `stdio` adapter) registered in A0; agent lists campaigns/pending; submit attempt refused server-side | M | eng | — |
| **Phase AZ-1 — OOBE parity** | | | | |
| AZ1-1 | Model-connect bridge: A0 model gate/onboarding → engine `POST /setup/llm` (D2) | M | both | — |
| AZ1-2 | Applicant OOBE plugin: welcome + 12-section resumable intake, `apply_missing[]` honest completion | L | eng | — |
| AZ1-3 | Base-résumé upload + parse-verify surface + font detect + LaTeX accept/reject | M | eng | — |
| AZ1-4 | Feature-state gating layer in the plugin (4-state, engine-derived) + agent-profile deferral until `apply_ready` | M | eng | — |
| **Phase AZ-2 — Daily loop** | | | | |
| AZ2-1 | Portal panel (pending actions + affordances) + A0 notification-center integration | L | eng | — |
| AZ2-2 | Digest panel + approve/decline + feedback | M | eng | — |
| AZ2-3 | Documents + redline review + H3 snapshot renderer + H4 provenance | L | eng | — |
| AZ2-4 | Remote takeover embed + final-submit stop boundary + 2FA/account-step resume | L | eng | — |
| AZ2-5 | Job Assistant integration into A0 chat (profile + engine-backed tools + chips) (D8) | L | both | — |
| AZ2-6 | Health panel + global pause + honest degrade states (H2 anchors) | M | eng | — |
| **Phase AZ-3 — Full surface parity (long tail)** | | | | |
| AZ3-1 | Settings suite: tiers ladder, channels+quiet-hours, fonts, sandbox+automation, telemetry, campaign settings | L | eng | — |
| AZ3-2 | Insight suite: tracker, results, activity+run-controls, gallery, compare, capabilities, trust | L | eng | — |
| AZ3-3 | Mind panel + curation approvals (kept separate from A0 `_memory`) | M | eng | — |
| AZ3-4 | Vault, Easy Apply, screening-answer library, interview prep, save-a-job, Today lens, switcher/shortcuts/demo/export/audit/update/debug | L | eng | — |
| AZ3-5 | Dormant-surface preservation (desktop assist, aggressiveness) as present-but-grayed | S | eng | — |
| AZ3-6 | Integrations settings: lane credentials re-home (email/calendar → companion) + Connections guidance (MCP plane vs lane plane, journey §5) | M | eng | — |
| AZ3-7 | Per-surface help system: help affordance + plain-language instructions on every plugin panel, chat "how do I…?" answering from the same content, lens-12-style tests pinning it | L | eng | — |
| **Phase AZ-R — Bespoke UI redesign (D1; parallel workstream, starts after AZ-2)** | | | | |
| AZR-1 | Fork `webui/` into `a0-webui/` + build-step application + documented cherry-pick workflow | M | eng | — |
| AZR-2 | Applicant visual design system + redesign execution across shipped surfaces (incl. the D12 power-tools curation) | L | both | — |
| AZR-3 | Upstream-UI cherry-pick drill: pull newer upstream, port one UI change into the fork, gates green | S | eng | — |
| **Phase AZ-4 — Companion services** | | | | |
| AZ4-1 | Companion headless hardening: strip public UI exposure, keep lanes A–D + internal token | M | eng | — |
| AZ4-2 | Lane regression tests against companion (calendar write-back, email scan, research run) | M | eng | — |
| AZ4-3 | (Optional, later) replace email lane with A0 `_email_integration` (D3) | L | both | — |
| **Phase AZ-5 — Safety & honesty proofs** | | | | |
| AZ5-1 | Bypass negative test: A0 browser/shell cannot complete ATS login/fill/upload/submit around the engine | L | eng | — |
| AZ5-2 | Prompt-overlay hardening + prompt-injection review of agent-visible surfaces | M | eng | — |
| AZ5-3 | H1–H5 re-audit on the plugin surfaces (incl. H5 copy denylist over plugin strings) | M | eng | — |
| **Phase AZ-6 — Ship gate** | | | | |
| AZ6-1 | Playtest protocol adaptation: contract sweep + §6a monkey/crawl against A0 webui, run-until-green | L | eng | — |
| AZ6-2 | Golden path G1–G9 on the new shell + two-window concurrency checks | L | eng | — |
| AZ6-3 | Traceability + delivery-status update: reachability column re-pointed at A0 surfaces | M | eng | — |
| AZ6-4 | Front-door retirement decision + execution (D7) | M | both | — |
| AZ6-5 | **PAG-1 re-run on the new shell** (owner dogfood; **starts living in the shell from AZ-2** per D20) | L | you | — |
| AZ6-6 | Full workspace-data migration (D15): chats→A0 history, notes/docs→canvas files, memory/skills→A0 memory — **runs before AZ6-4 retirement**; per-slice fidelity checks | L | eng | — |
| AZ6-7 | Applicant 2.0 release engineering (D21): VERSION → 2.0.0, changelog, docs relaunch, P4 GTM refresh | M | both | — |
| **Phase AZ-7 — Lane convergence onto MCP (committed follow-on, post-closure)** | | | | |
| AZ7-1 | Engine-side MCP-provider adapter: lanes A–C consume MCP servers (calendar/email/research) behind the existing callback contract | L | eng | — |
| AZ7-2 | Email lane cutover (MCP provider or A0 `_email_integration`) + parity tests vs AZ4-2 baseline | L | eng | — |
| AZ7-3 | Calendar lane cutover (interview read + write-back over an MCP calendar provider) | M | eng | — |
| AZ7-4 | Credentials collapse into Connections (one place to connect Google/mail); companion retirement once all lanes are cut over | M | both | — |

Spine: `AZ0-* → AZ1-* → AZ2-* → {AZ3-*, AZ4-*} → AZ5-* → AZ6-*` (AZ0-6 is the go/no-go proof;
nothing past Phase 1 starts until it passes).

Per-story DoR/DoD follow the universal lists; stories above L-size get split at pickup. Three
port-wide DoD additions on every story: **(a)** no upstream agent-zero file edited (CI-checkable:
`git diff` of the subtree vs upstream tag is empty), **(b)** any new user-visible claim passes the
H5 overclaim denylist, **(c)** the feature ships **workable end-user instructions** — an
on-surface help affordance with plain-language steps, verified by completing the task using only
those instructions (journey blueprint §8; lens-12 help parity).

## 5. Decisions — **all DECIDED by the owner, 2026-07-18** (the spec is unambiguous)

| ID | Decision | Recommendation |
|---|---|---|
| D1 | UI bespoke-ness: branding-only (cheap updates) vs redesign (edits upstream UI = forfeits clean pulls) | **DECIDED (owner, 2026-07-18): bespoke redesign.** Mitigation: the Python framework subtree stays pristine (pulls stay clean); the bespoke UI is a **managed fork of `webui/`** maintained out-of-tree and applied over the pristine tree at build — upstream UI changes become deliberate cherry-picks. UI-layer updateability: managed, not free. Phasing: land Phases 0–2 on branding-only chrome first, then execute the redesign as its own workstream so the daily loop isn't blocked on visual design |
| D2 | Model-config source of truth: A0's settings feed the engine, or the plugin drives both | **DECIDED (owner, 2026-07-18): A0 collects, plugin syncs to engine** (`POST /setup/llm` mirrored from A0's model config); the tier *ladder* stays engine-side, edited via a plugin settings panel |
| D3 | Lanes A–D long-term: keep companion forever vs port (A0 `_email_integration`, plugin calendar) | **DECIDED (owner, 2026-07-18): companion now + committed MCP migration** — lanes ship on the companion (zero regression), and Phase **AZ-7** commits the follow-on migration to MCP providers |
| D4 | Auth: accept single-user A0 login (drop workspace multi-user) | **DECIDED (owner, 2026-07-18): single-user + login** (installer enables `AUTH_LOGIN`; engine single-tenancy unchanged; multi-user workspace auth not carried) |
| D5 | Outbound notifications: engine's Apprise ladder stays authoritative | **DECIDED (owner, 2026-07-18): yes** — engine is the single notification authority; only the in-app center moves to A0 |
| D6 | Code layout: where Applicant-owned A0 code lives | **DECIDED (owner, 2026-07-18): both out-of-tree** — `a0-applicant/` (plugin bundle) and `a0-webui/` (bespoke UI fork) at repo root, COPY'd over the byte-pristine subtree at build (supersedes the plane-map sketch) |
| D7 | Front-door retirement: retire at AZ6-4 vs keep dual-shell for a transition window | **DECIDED (owner, 2026-07-18): retire at the ship gate** — the A0 shell becomes the only public UI once AZ-6 passes (golden path + PAG-1); no dual-UI window; companion stays headless for lanes until AZ-7 |
| D8 | Chat: A0 chat as THE product chat vs a separate embedded job-chat panel | **DECIDED (owner, 2026-07-18): one unified chat** — A0's chat with the applicant profile: job-action chips, criteria edits via the confirmation gate, receipts-based answers, general assistance in the same thread |
| D9 | Integrations posture: lanes stay on companion IMAP/CalDAV vs converge onto MCP providers (e.g. Google MCP feeding lanes via an adapter) | **DECIDED (owner, 2026-07-18): converge — committed as Phase AZ-7** (engine-side MCP-provider adapter; credentials collapse into Connections; companion retires when lanes cut over) |
| D10 | Phone push / PWA distribution: wire the stack's `ntfy` (and/or PWA push) as an opt-in channel | **DECIDED (owner, 2026-07-18): ntfy ships as an opt-in phone-push channel in the ladder** (setup instructions in the Notifications panel); PWA push deferred |
| D11 | Model-connect forks: keep/hide/curate A0's OAuth provider accounts for the Applicant audience | **DECIDED (owner, 2026-07-18): keep all three forks** (cloud key / provider account / local), copy curated for job-seekers; zero upstream edits |
| D12 | Desktop/canvas exposure: full A0 general-agent surface vs curated subset for job seekers | **DECIDED (owner, 2026-07-18): curated default + power toggle** — job-search surfaces front and center; desktop/canvas/plugin-hub behind a "power tools" toggle (additive config, baked into the D1 redesign); the two-browser labeling from journey §7 applies whenever the desktop is visible |
| D13 | Visual identity source for the bespoke redesign | **DECIDED (owner, 2026-07-18): new identity, designed in AZ-R and proposed for owner approval** (mockups first; placeholder marks until blessed) |
| D14 | Assistant persona & voice | **DECIDED (owner, 2026-07-18): "Applicant", warm-professional** — one name everywhere; H5-calibrated claims baked into the voice |
| D15 | Workspace-data continuity at cutover | **DECIDED (owner, 2026-07-18): full migration** — everything portable moves into the new shell before retirement (chats→A0 history, notes/docs→canvas files, memory/skills→A0 memory; calendar/email stay live via companion until AZ-7). New story AZ6-6, sequenced before AZ6-4 |
| D16 | Deployment resource posture (A0 desktop weight) | **DECIDED (owner, 2026-07-18): VM grows as needed** — Proxmox provisioning defaults bumped; requirements docs updated honestly (H5) |
| D17 | General-agent autonomy defaults (outside the job lane) | **DECIDED (owner, 2026-07-18): A0 stock defaults**, incl. subordinate-agent spawning — the job lane's server-side gates and the AZ5-1 bypass test are unaffected |
| D18 | Discord channel status | **DECIDED (owner, 2026-07-18): first-class** — ladder is in-app → Discord/ntfy → email, all opt-in |
| D19 | Memory routing for user-stated "remember this" | **DECIDED (owner, 2026-07-18): route by content** — job-search facts → engine mind via curation approval; general preferences → A0 memory instantly; the assistant names where each item landed (H1) |
| D20 | PAG-1 dogfood timing | **DECIDED (owner, 2026-07-18): owner dogfoods from AZ-2** (daily loop) — feedback steers AZ-3/AZ-R; PAG-1 formally passes at AZ-6 |
| D21 | Release identity | **DECIDED (owner, 2026-07-18): Applicant 2.0** — VERSION → 2.0.0 at the ship gate; changelog/docs relaunch; P4 GTM items refresh in AZ-6. New story AZ6-7 |
| D22 | Process for PR #822 + build | **DECIDED (owner, 2026-07-18): hold #822 open through AZ-0** — the spec PR absorbs the foundations (vendor, skeleton, seam proof); learnings fold into the docs; spec + foundations merge together once AZ0-6 validates the architecture |

## 6. Top risks

| Risk | Mitigation |
|---|---|
| Long-tail underestimation (AZ3 is ~35 surfaces) | phase-gated; Portal/daily-loop first so the product *feels like Applicant* before the tail lands |
| Safety regression via the general agent (the one existential risk) | AZ0-6 seam proof first; AZ5-1 negative test in CI; enforcement never leaves the engine; A0 browser is never wired to real applications |
| Two notification systems drift (A0 center vs engine ladder) | engine stays authoritative for fan-out (D5); plugin renders engine notifications into A0's center — one source |
| Two memory systems blur (A0 `_memory` vs engine mind/attributes) | hard separation (plane 7); no cross-writes; AZ3-3 keeps stores distinct |
| Subtree pull breaks a breakpoint the plugin depends on | vendor-sync runs the full gate set incl. plugin smoke; breakpoints are upstream's public extension API — low churn expected |
| H3 fidelity drift across multiple submit surfaces | one exported snapshot renderer, same as today; contract test pins it |
| Companion bit-rot (headless app nobody looks at) | AZ4-2 lane regression tests in CI; companion is code we already own and test |

## 7. Suggested next increment

**AZ0-1 + AZ0-5 + AZ0-6, landed on the spec PR itself** (per D22: #822 stays open through AZ-0 and
merges spec + foundations together once the seam proof passes). AZ0-6 is the cheapest possible
falsification of the whole strategy: if the agent can list campaigns over MCP and a submit attempt
is refused server-side, every later phase builds on proven ground. From AZ-1 on, each increment is
its own focused PR.
