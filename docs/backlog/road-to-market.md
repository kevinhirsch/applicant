# Road-to-Market Backlog

Every bulleted item from the Phase 0 → market plan, transformed into actionable user
stories with a **Definition of Ready (DoR)** and **Definition of Done (DoD)**.

**How to read this**

- **Effort:** S = hours · M = 1–2 days · L = 3+ days.
- **Owner:** `eng` = buildable by the engineering agent · `you` = a decision or
  external action only the product owner can take · `both` = shared.
- **DoR** = preconditions that must hold before the story is picked up (no starting a
  story whose inputs don't exist). **DoD** = the checklist that lets the story be
  called finished — behavioural and verifiable, never "looks done."
- **The universal DoD** below is implied by every story; per-story DoD lists only the
  *additional* acceptance criteria.
- Phases are roughly sequential; items within a phase are ordered by dependency.
  The dependency spine is drawn at the end of each phase.
- The **index** just below is the at-a-glance backlog. Maintain its Status column as
  stories move (`—` → IN PROGRESS → DONE); per-story detail lives in the phase sections.

## Current focus (Now → Next)

Two tracks. The **founder-trust track** is the spine and the launch gate; the **market
track** runs behind it. Note: **demo mode (P0-2) ≠ the founder dogfood (PAG-1)** — P0-2 is
synthetic data for screenshots/sales; PAG-1 runs on a *real* instance with the owner's real
résumé, key, and submissions. Don't conflate their ordering.

- **Founder-trust track (the priority):** stand up a real instance on the owner's data →
  get the loop working on it (P1-1 on real data) → build the honesty invariants
  (H1–H5) so the owner can *see* it's honest → **dogfood continuously** (don't wait for the
  end) → accumulate toward PAG-1's threshold N. Early dogfooding surfaces real bugs faster
  than any speculative polish, and reorders everything behind it.
- **Now (eng):** P1-13 DONE (flagged-facts review surface + one-tap add-to-profile landed
  on the merged core fact-gate) · P1-0 DONE (CI secret-scan step, PR #735) · H1
  (receipts-not-narration) + H3 (full-fidelity review). *(P1-1a is DONE: engine PR #644 + wizard double-check
  surfacing — the parse-verify layer runs on every base-résumé ingest.)*
- **Studies:** `docs/studies/` — parse-verify tier study **done & green** (free local
  floor suffices; reasoning must be off). Next study: tailoring/rewrite quality (P2-6).
- **Now (you):** provision a fresh model key + drop your real résumé so the real instance
  can stand up · P1-2 employer trial signups (longest external lead) · P4-7 name check.
- **Market track (behind the gate):** P0-2 demo mode → P0-4/P0-5 → P0-6 (bless last) →
  competitive track (P1-8 → P1-9 → P1-10). Nothing here launches until PAG-1 passes.

## Index — all stories at a glance

| ID | Story | Effort | Owner | Status |
|----|-------|--------|-------|--------|
| P0-1 | Window-chrome baseline merged | S | eng | DONE |
| P0-2 | Seeded demo mode | M | eng | — |
| P0-3 | The 3-pane shell (chat center, gadget rail) | L | eng | PARTIAL — gadget rail + top-bar bell + wordmark-home shipped; window-manager retirement + #640 watcher in the concurrent retirement lane (see note) |
| P0-4 | De-workspace the surface | M | eng | DONE — speaker "Applicant", padlocks → absence, window titles fixed, no-model-name pin tests |
| P0-5 | Empty states that sell | S–M | eng | — |
| P0-6 | Visual regression harness | M | eng | — |
| P1-0 | Secrets: revoke + CI scanning | S | both | DONE — keys revoked (owner) + CI secret-scan step (PR #735) |
| P1-1 | Onboarding TTFV < 10 min | M | eng | PARTIAL — critical path trimmed + instrumented (verify reasons, get-a-key links, achievements prefill, single-year edu fix, Today essentials checklist, what-happens-next card, scripted 3-action walkthrough test); live 10-min stopwatch run on a deployed stack pending |
| P1-1a | LLM parse-verify layer (tier-laddered) | M | eng | DONE — engine PR #644 + wizard double-check surfacing |
| P1-2 | Real-board proof runs | L | both | — |
| P1-3 | Honest health panel | M | eng | DONE — engine health endpoint + Settings panel (PR #733) |
| P1-4 | Notifications out of the box | M | eng | DONE — per-channel Send test (single-channel engine lane + honest failure), branded digest email, Today checklist "Set up" jump, failed-push in-app error notes; digest send-now already reachable via the rail |
| P1-5 | Rescue stranded hardening waves | M | eng | SUPERSEDED — audit found both waves already on `main` via separate PRs; branch archival pending owner |
| P1-6 | Cost & pace guardrails | M | eng | DONE — engine PR (issue #658) |
| P1-7 | Backup / restore / export | M | eng | PARTIAL — backup.sh/restore.sh/export shipped; drill script written, needs live-deploy verification (PR #659) |
| P1-8 | Keyword / ATS match score | S | eng | DONE |
| P1-9 | Save-a-job-from-any-page | S (+S) | eng | — |
| P1-10 | Multi-campaign base profiles | M | eng | DONE |
| P1-11 | Easy Apply: detect & tag | S | eng | DONE — server-side detection at discovery + digest channel + tracker chip |
| P1-12 | Narrative FE homes for engine capabilities | M | eng | — |
| P1-13 | Truth policy: free rewrite over a fact-gate | M | eng | DONE — core+guard (PR #643) + FE flagged-facts surfacing |
| H1 | Honesty: receipts, not narration | M | eng | DONE — claim-path audit (docs/design/audits/h1-receipts-audit.md) machine-checked by no-narration pin tests; per-run receipts on Activity rows; Today's count links to its run trail |
| H2 | Honesty: no silent underdelivery | M | eng | — |
| H3 | Honesty: full-fidelity review | S | eng | DONE — reviewed-stage snapshot at the stop-boundary, promoted byte-identical on submit; literal-payload panel on every submit surface |
| H4 | Honesty: visible provenance | M | eng | DONE — per-line provenance trace in the review panel (engine `/provenance` read + "Where this came from") |
| H5 | Honesty: calibrated copy | S | eng | DONE — full copy sweep + overclaim-denylist pin tests (engine + front-door lanes); recap verbs & wizard render-promise calibrated |
| PAG-1 | Personal Acceptance Gate (founder dogfood) | L | both | — |
| P2-1 | Terms of Use / ToS posture | M | you+eng | — |
| P2-2 | Privacy policy + rights | M | eng/you | — |
| P2-3 | Security pass | M | eng | — |
| P2-4 | License compliance | S | eng+you | — |
| P2-5 | Fabrication-guard evidence | S | eng | — |
| P2-6 | LLM output eval harness | M | eng | — |
| P2-7 | Sensitive-question policy | M | eng | — |
| P2-8 | Final-say invariant test | S | eng | — |
| P2-9 | App-door hardening | M | eng | — |
| P2-10 | ATS-parseability proof | M | eng | — |
| P2-11 | Local-only private mode | M | eng | — |
| P2-12 | Durability drills | M | eng | — |
| P2-13 | Source reliability matrix | M | eng | — |
| P2-14 | Easy Apply: assisted mode | M | both | — |
| P3-1 | Install on tested targets | M–L | eng | — |
| P3-2 | Requirements & model matrix | S–M | eng | — |
| P3-3 | Business model + licensing | M | you+eng | — |
| P3-4 | Docs site | M | eng | — |
| P3-5 | Release engineering | M | eng | — |
| P3-6 | Workspace DB migrations | M | eng | — |
| P3-7 | Platform matrix | S–M | eng+you | — |
| P3-8 | Digest deliverability | S–M | eng | — |
| P4-1 | Positioning statement | S | you+eng | — |
| P4-2 | Landing page | M | eng | — |
| P4-3 | Proof assets | M | eng+you | — |
| P4-4 | Competitive teardown | M | eng | — |
| P4-5 | Early-access cohort | M | you+eng | — |
| P4-6 | Pricing validation | S | you | — |
| P4-DEC-1 | Source-available decision | — | you | — |
| P4-DEC-2 | Takeover scope decision | — | you | — |
| P4-7 | Name check | S | you | — |
| P5-1 | Support machinery | M | eng | — |
| P5-2 | Pre-written FAQs | M | eng | — |
| P5-3 | Opt-in telemetry | S–M | eng | — |
| P5-4 | Launch sequence | M | you+eng | — |
| P5-5 | Post-launch flywheel | ongoing | both | — |
| P5-6 | Easy Apply autopilot | L | eng | — |
| X-1 | Mobile golden-path audit | M | eng | — |
| X-2 | Cross-browser smoke | S–M | eng | — |
| X-3 | Performance budget | M | eng | — |
| X-4 | Accessibility pass | M | eng | — |

## Universal Definition of Done (applies to every story)

A story is not done until ALL of these hold, in addition to its own DoD:

1. The change is reachable and operable in the **white-labeled front-door** (not just
   the engine) where it has any user surface — verified by driving the actual UI.
2. Green increment: hermetic engine suite, front-door `test_applicant_*`, `npm test`,
   `ruff`, `lint-imports` (2 kept / 0 broken), both white-label greps, boot smoke,
   single Alembic head, `docker compose config` — all pass locally before merge.
3. No upstream-fork codenames or `FR-`/`NFR-` jargon in any user-facing string.
4. New user-facing behaviour has at least one automated test pinning it against
   regression (visual, unit, or contract as appropriate).
5. Any new setting/guard that protects safety or money is enforced **server-side**,
   never trusting a caller-supplied value.
6. Committed on a focused branch, PR opened as ready-for-review, CI green.

## Universal Definition of Ready (applies to every story)

1. The story's acceptance criteria (its DoD) are written and unambiguous.
2. Its listed dependencies are merged to `main` (or explicitly stubbed with agreement).
3. Any `you`-owned decision or credential the story needs is resolved and recorded.
4. Test fixtures/data the story needs exist (often: demo seed from P0-2).

---

# Phase 0

### P0-1 — Merge the window-chrome / nav / Settings baseline
**As** the team, **I want** the light-glass chrome, Home wordmark, Themes-on-sidebar,
Trust-removal, and Settings regroup on `main` **so that** all later work builds on a
stable visual floor.
**Effort:** S · **Owner:** eng · **Depends on:** — · **Status: DONE** (PR #640, merged as `a2b96af`).
**DoR:** PR #640 CI green; no unmerged conflicts.
**DoD:**
- [x] Squash-merged to `main`; local `main` realigned.
- [x] A fresh boot from `main` shows white frosted glass + clean windows + lands on Today.
- [x] Working branch reconciled to the squashed `main`.

### P0-2 — Seeded demo mode
**As** a demoer/developer, **I want** one env-gated command to load a believable
mid-flight state **so that** every screenshot, video, test fixture, and sales demo
comes from consistent, non-empty data.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:**
- Confirmed list of surfaces that must be non-empty (Today, Tracker, Results, Activity,
  Documents, Gallery, Profile, Daily updates, Calendar, Run log, chat).
- Agreement that seed runs against both in-memory and Postgres.
**DoD:**
- [ ] `DEMO_MODE=1` seed loads: 5 applications, one per stage (discovered → prefilled →
      waiting-on-you → submitted → interview); a digest of ~6
      scored roles each with a visible match rationale; 1 tailored résumé with a real
      redline diff (add + subtract + free-text edit); 1 interview event; ~15
      activity-feed entries; momentum + streak numbers; 2–3 Portal "waiting on you" items.
- [ ] The stale `:wave:` demo chat is replaced by a scripted Applicant conversation;
      2 documents seeded into the library.
- [ ] A visible "Demo data" banner is shown while seeded; a one-click **Clear demo data**
      removes all of it with no residue.
- [ ] Re-running the seed is idempotent (no duplicate rows).
- [ ] The seed path is unreachable when `DEMO_MODE` is unset (guarded + tested).
- [ ] No secret/API key is ever written into seed data (ties to P1-0).

### P0-3 — The 3-pane shell (chat center, gadget rail)
**As** a user, **I want** the app to be one 3-pane shell — nav sidebar, the Applicant
chat as the permanent center, and a right-hand gadget rail for at-a-glance state —
**so that** the product reads as a job-autopilot I talk to, not windows floating over
a chat.

*(Owner respec 2026-07-08 — supersedes "Today becomes a page (not a modal)". Floating
windows are removed as a primitive: every former window becomes a rail gadget, a full
page, or both — a gadget expands to its page in one click. "Today" is the shell itself,
not a separate view; there is no `#portal`/`#chat` center toggle.)*

**Effort:** L · **Owner:** eng · **Depends on:** P0-1 (P0-2 recommended for review)
**DoR:**
- Gadget set v1 confirmed (owner, 2026-07-08): waiting-on-you queue, pipeline counts by
  stage, activity feed tail, cost & pace meter (pairs with P1-6), next-interview /
  calendar peek, digest countdown + send-now, momentum/streak, system health chip
  (pairs with P1-3).
- Notification surfaces confirmed — exactly three: top-bar bell + dropdown, the rail's
  notification area, transient toasts (reuse `ui.js` `showToast`).
- Mobile behaviour agreed (keep bottom-sheet for now; the rail collapses away on small
  viewports).
**DoD:**
- [x] On desktop, login lands in the 3-pane shell: sidebar | chat (permanent center) |
      gadget rail — the rail (`#applicant-gadget-rail`) is a static flex sibling of the
      chat `<main>`, so the third pane reserves its own column on first paint with no
      scrim/dim/close/focus-trap of its own. *(The chat center + sidebar were already the
      shell; this adds the rail as the third pane.)*
- [x] On small viewports the rail collapses away (CSS `@media (max-width:768px)`); the
      mobile bottom-sheet fallback remains acceptable.
- [x] Rail top is the notification area: the waiting-on-you queue auto-expands (gets a
      card frame) when action-required items arrive and shrinks to an "all clear" line
      when empty; gadgets reflow below it; each gadget is pinnable (pins float to the top,
      persisted in localStorage) and the whole rail collapses to a slim badge strip.
- [x] Notifications reachable from THREE surfaces: **top-bar bell + dropdown** (new, P0-3b —
      `static/js/applicantBell.js` + `#applicant-bell-wrap` in the chat top bar), the **rail
      waiting-on-you area**, and **transient toasts** (reused `ui.js` `showToast` via `_toast`).
      The bell is a NEW LENS over the SAME owner-scoped backing the rail/Portal read
      (`GET /api/applicant/portal/pending`) — no new engine endpoint. It shows the pending count
      and a dropdown of the same items; each opens Today via the existing `window.openApplicantToday`
      launcher. Acting on an item clears it from bell, rail, AND portal at once: the Portal's
      `_setBadge` dispatches `applicant:pending-changed`, which both the bell and the rail listen for
      and re-read. (The old sidebar count badge remains as a bonus signal.)
- [x] Each v1 gadget (8: waiting-on-you, pipeline, activity, cost & pace, next-interview,
      digest, momentum, health) renders live data from an existing owner-scoped proxy and
      expands to its full page in one click via the SAME `window` launcher that page
      already exports (`openApplicantTracker/Today/Results`, `applicantActivityModule`,
      the `#rail-email` seam) — no new engine endpoints, no floating window.
- [ ] The window manager is retired from the default product surface; modal-stack tests
      replaced by the shell/page view contract. **In the concurrent window-retirement lane**
      (owns the applicantPortal/Today window-stack plumbing, app.js modal-stack code, and the
      #640 watcher). P0-3b deliberately did NOT touch that plumbing to avoid colliding with it.
- [ ] The auto-land watcher added in PR #640 is removed. **In the concurrent
      window-retirement lane** (same owner as the item above).
- [x] The brand wordmark routes home to the shell (P0-1's Home behaviour): clicking the
      "Applicant" wordmark (`sidebar-brand-btn`) is intercepted in `applicantChat.js`
      (`_interceptNewChatClick`) to open Today (the Portal home base), never a new chat.
      Pinned by `test_applicant_chat_unification.py`.

**Status note (updated 2026-07-08, P0-3b):** The gadget rail (P0-3) plus the **top-bar
notification bell** (P0-3b — `static/js/applicantBell.js` + `#applicant-bell-wrap`) and the
**wordmark→home** behaviour are shipped and reachable, closing the "notifications from three
surfaces" and "wordmark routes home" DoD items. The bell is covered by
`tests/js/applicantBell.test.js` (pure helpers) and `tests/test_applicant_topbar_bell.py`
(composition/reuse/owner-only/cross-surface-signal). It reuses the SAME
`GET /api/applicant/portal/pending` backing the rail + Portal read (no new endpoint), routes to
Today via the existing launcher (no rebuilt resolve logic), and shares the
`applicant:pending-changed` signal so a resolution clears all three surfaces at once.
**Still open (row stays PARTIAL):** fully retiring the floating-window manager and removing the
PR #640 auto-land watcher — these are owned by the **concurrent window-retirement lane**, which
holds the window/modal-stack plumbing across applicantPortal/Today/app.js; P0-3b stayed out of
that plumbing by design and opened pages only through the existing `window.openApplicant*`
launchers. Once that lane lands, this row can flip to DONE.

### P0-4 — De-workspace the surface
**As** a non-technical user, **I want** to never see model names, token counters, or
developer-tool furniture **so that** the product feels purpose-built, not a repurposed
AI playground.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:**
- Enumerated list of affordances to hide (sidebar, rail, slash commands, hint pills).
- Confirmed which workspace modules are out of the default product (Notes, Tasks, image
  editor, Cookbook, workspace gallery, research) vs. kept.
**DoD:**
- [x] In the engine-backed Applicant chat: speaker reads "Applicant"; no model-name
      header, tok/s, %-context chip, per-message edit/delete controls, or composer model
      picker. (Raw-LLM path stays reachable via Compare/model list, unchanged.)
- [x] Non-product workspace modules are hidden from default nav/rail/commands.
- [x] **Padlocks → absence:** engine-gated sections (Results, Documents, Gallery, Profile,
      Daily updates, Chat, etc.) no longer render a lock icon when unavailable — they
      *appear* once they become real (setup complete / data exists). A padlock reads as
      "broken/paywalled"; appearing reads as "the product grows as I use it."
      (A configured-but-engine-offline section stays visible, dimmed — vanishing on a
      transient outage would read as data loss.)
- [x] Known mislabeled window titles fixed (Documents window no longer titled "Library";
      Daily updates window no longer titled "Email").
- [x] A test asserts the Applicant chat surface renders **no** model-name literals
      (`workspace/tests/test_applicant_p04_deworkspace.py`).
- [x] White-label greps still clean.

### P0-5 — Empty states that sell
**As** a first-run user, **I want** every empty section to tell me what the agent will
put there and when **so that** the product feels alive before it has data.
**Effort:** S–M · **Owner:** eng · **Depends on:** P0-1 (content benefits from P0-4 voice)
**DoR:**
- Approved one-line copy per section, in Applicant's first-person voice.
- Shared empty-state component design agreed (icon + sentence + one real CTA).
**DoD:**
- [ ] With `DEMO_MODE` **off** and a fresh account, every nav section shows a designed
      empty state — no blank panes anywhere.
- [ ] Each empty state's CTA routes somewhere real (no dead buttons).
- [ ] Empty states render correctly in both light and dark themes.

### P0-6 — Visual regression harness
**As** the team, **I want** every surface screenshot-diffed on each PR **so that**
visual quality ratchets forward instead of oscillating.
**Effort:** M · **Owner:** eng · **Depends on:** P0-2 (stable content), and blessing
must wait until P0-3/P0-4/P0-5 land (or baselines get blessed twice).
**DoR:**
- Determinism hooks identified: freeze aurora/canvas animation, pin the clock, seed
  demo content, mask any residual dynamic regions.
- Surface + viewport + theme matrix agreed.
**DoD:**
- [ ] `workspace/tests/visual/` walks login → Today → each nav section → Settings (each
      group) → theme picker → wizard steps, at 1440×900 and 1024×768, in white-glass and
      one dark theme.
- [ ] Runs are deterministic (animation frozen, clock pinned) — two consecutive runs
      produce a zero diff.
- [ ] A PR that visually regresses any covered surface fails CI with an uploaded diff
      image; `--bless` is the only way to accept a visual change.
- [ ] Baselines blessed **after** P0-3/4/5 are merged.
- [ ] Service-worker staleness addressed (versioned asset URLs or SW cache-bust on
      release) so updated assets aren't served stale.

**Phase 0 spine:** P0-1 → P0-2 → {P0-3, P0-4} → P0-5 → P0-6 (bless last).

---

# Phase 1

### P1-0 — Revoke & rotate exposed secrets *(do first)*
**As** the owner, **I want** all previously-exposed API keys revoked and secret
scanning in CI **so that** no leaked credential survives into demo/seed artifacts.
**Effort:** S · **Owner:** both · **Depends on:** — · **Status: IN PROGRESS**
**DoR:** List of keys/locations to check (project history + the live demo DB's
configured key).
**DoD:**
- [x] All previously-exposed OpenRouter (and any other) keys revoked at the provider.
      *(owner-confirmed revoked.)*
- [ ] The demo/dev DB carries no real key; seed (P0-2) never emits one.
- [ ] CI runs a secret-scanning step that fails on committed credentials.

### P1-1 — Time-to-first-value under 10 minutes
**As** a new user, **I want** onboarding to reliably get me from install to a scheduled
first digest in under 10 minutes **so that** I reach value before I give up.
**Effort:** M · **Owner:** eng · **Depends on:** P0-2, P0-4
**DoR:**
- Provider preset list agreed (OpenRouter + "get a key" link, generic OpenAI-compatible
  URL, local auto-scan).
- Résumé-parse fixtures gathered (including the failing "UC Berkeley — 2013" single-year
  case and an achievements-bearing résumé).
**DoD:**
- [x] Model-connect step offers presets + a **Verify** button that does a live
      round-trip and reports the failure *reason* (bad key / unreachable / no models)
      with recovery copy. *(Presets + Test + local auto-scan already existed via the
      shared endpoint manager; the Test round-trip now classifies the failure reason
      server-side — 401/403 ⇒ bad key, reachable-but-empty ⇒ no models, else
      unreachable — and `admin.js` renders a distinct recovery action per class, plus
      per-provider "get a key" links incl. OpenRouter.)*
- [x] Résumé import accepts PDF/docx/txt and shows a parsed preview **including
      achievements** (the onboarding review previously omitted parsed achievements).
      *(The parser already extracted per-role achievement bullets; the onboarding
      prefill now carries them into the work-history form's highlights field.)*
- [x] The single-year education parse renders correctly; a bad parse has an explicit
      "edit" path so it never silently poisons applications. *(Deterministic layer
      hardened against the owner's real résumé — modern multi-column/sidebar PDF, split
      title|company lines, location/noise filtering, certifications section — PR #642.
      The "UC Berkeley — 2013" lone-graduation-year case now lands the year in the
      year field instead of polluting the institution; every prefetched education
      entry stays editable in the review form. The LLM verify layer on top is P1-1a.)*
- [x] Today shows an essentials checklist (model / profile / notifications) until the
      apply-readiness gate opens, with one-tap wizard resume. *(Portal proxy derives
      the checklist from the engine's setup status — omission-honest — and Today
      renders it on both the gated state and the onboarding-incomplete card.)*
- [x] A "what happens next" card explains the first digest + approval flow. *(On the
      wizard finish screen: continuous search → first digest in Pending/channels →
      approve, review, final OK before anything is sent.)*
- [ ] A stopwatch test from fresh install to "digest scheduled + profile parsed + channel
      set" completes under 10 minutes; every failure state on that path has a recovery action.
      *(Partially done: the scripted engine walkthrough — `tests/unit/
      test_p1_1_ttfv_walkthrough.py` — pins the golden path at THREE user actions
      (connect model → upload résumé → confirm criteria) and asserts every not-ready
      stage reports an actionable missing list; the front-door failure states (verify
      reasons, gated Today, wizard jump-backs) each carry a recovery action. The live
      human stopwatch on a deployed stack with a real model remains to be run.)*

### P1-1a — LLM parse-verify layer over the deterministic résumé parse
**As** a new user, **I want** an LLM to check and correct the parsed résumé — slotting
every value from my real-world résumé into the right field — **so that** onboarding
survives the infinite variety of real résumés instead of only the formats the
deterministic parser anticipates.
*(Owner direction: the LLM oversees quality on everything; slotting source strings into
the right fields is not generation — it runs autonomously, no confirmation ceremony.
Study: `docs/studies/2026-07-07-parse-verify-tier-study.md` — all four tier models
produced a **perfect** corrected parse of the owner's real résumé with **zero** invented
strings; the free local floor (reasoning off) was the fastest.)*
**Effort:** M · **Owner:** eng · **Depends on:** PR #642 (deterministic layer), an LLM
endpoint (local floor or router key); P1-13 for the shared truth policy.
**DoR:**
- [x] Tier study complete and green (see study doc).
- [x] Escalation signal chosen: per-area confidence (< ~0.8) or malformed/schema-violating
      output → escalate one tier (floor → GLM 5.2 / DeepSeek class).
**DoD:** *(engine merged as PR #644 after six adversarial review rounds — grounding is
window-scoped, restoration is entry-scoped + heading-gated, grounding holes refill from
the draft twin, confidence must score every area; wizard surfacing landed right after)*
- [x] Onboarding ingest runs: deterministic parse → verify call on the configured floor
      model with **reasoning disabled/capped** (the study's one deployment trap) →
      corrected parse replaces the draft.
- [x] Escalates one tier on low confidence or malformed output; logs which tier answered.
- [x] Offline/no-model fallback = deterministic parse only, with a visible "not verified"
      notice (honesty invariant H2 — no silent degrade): the wizard's post-upload message
      says "Not double-checked (why)" from the response's `verify` block.
- [x] The review UI shows the corrected fields (the prefilled steps), per-area confidence,
      and the model's `corrections` + `restored_from_draft` lists, each capped at 5 with an
      "and N more" indicator (pairs with the achievements-preview item in P1-1).
- [x] Tests: unit + contract on recorded fixtures (no live LLM in CI); one live smoke
      behind an env flag.

### P1-2 — Prove the loop on real boards *(start account setup immediately — longest lead)*
**As** the owner, **I want** recorded end-to-end proof runs on real ATS platforms
**so that** the product's central claim has evidence, not vibes.
**Effort:** L · **Owner:** both (you: employer trial accounts; eng: everything else)
**Depends on:** the stop-boundary + prefill code already on `main`; benefits from P1-1.
**DoR:**
- Greenhouse and Lever employer trial accounts created with self-owned test postings.
- Decision recorded on Workday scope (see P4-DEC-2 / prove via takeover vs. defer).
**DoD:**
- [ ] Full loop runs against ≥2 targets: discovery (URL injection OK) → prefill → stop at
      review → human approve → final submit → confirmation detected → tracker updates.
- [ ] Screen recording + engine run log + DOM snapshots saved to `docs/proof/` per target;
      snapshots re-used as form-fill regression fixtures.
- [ ] Every failure found is fixed or filed with a severity.
- [ ] Stealth stack (camoufox headful in-container) exercised under real network; findings logged.

### P1-3 — Honest health panel
**As** a self-hoster, **I want** every silent capability degrade surfaced with a fix-it
link **so that** I'm never confused by silent stubs.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:** Confirmed the engine's boot-time capability report contents (postgres, resume
renderer, browser, orchestrator) and where each fix lives.
**DoD:**
- [ ] Engine exposes the capability report via an endpoint; front-door proxies it
      (owner-gated) and renders it in Settings → System + a Today banner when anything
      load-bearing is degraded.
- [ ] Each degraded item shows actionable fix copy (not just a red dot).
- [ ] Engine-unreachable produces one designed banner in the front-door, not blank sections.

### P1-4 — Notifications out of the box
**As** a user, **I want** to set a notification channel during onboarding and get a test
digest immediately **so that** the product's heartbeat reaches me.
**Effort:** M · **Owner:** eng · **Depends on:** P1-1 (onboarding), P0-2 (on-demand digest)
**DoR:** Channels in scope confirmed (in-app always; email SMTP, ntfy, Discord webhook opt-in).
**DoD:**
- [x] Channel setup appears as a Today checklist item (not buried in Settings).
      *(Today's setup-essentials checklist (P1-1) includes the notifications item;
      P1-4 gives its unchecked state a one-tap "Set up" jump straight into
      Settings → Notifications — the wizard's "Finish setup" button can't reach
      it since channels are deliberately not a gating wizard step.)*
- [x] Each channel has a **Send test** button that delivers a real message.
      *(Every channel row — Discord / email / phone-push — has its own Send test
      over the new single-channel lane of `POST /api/setup/channels/test`; a
      live delivery failure PROPAGATES to the button (502, plain-language)
      instead of hiding behind the escalation ladder's log-and-retry isolation,
      and the dry-run lane keeps saying "nothing sent yet" honestly. The in-app
      inbox works with zero config and is testable the same way.)*
- [x] The digest email template is polished (doubles as marketing asset for P4).
      *(Branded shell: preheader-first body, "Applicant" text masthead, lead
      summary line, inline-styled card list, and a footer explaining where the
      matches came from — sources × criteria, nothing submitted without
      approval — plus the Settings → Notifications pointer. Still table-based
      + inline styles for mail-client compatibility.)*
- [x] A "send my digest now" control exists so demos/first-runs don't wait for
      the tick. *(Already reachable before this story: the Today rail's
      Daily-digest gadget "Send it now" (P0-3) and the digest page's manual
      delivery, both over `POST /campaigns/{id}/digest/deliver` — verified, not
      rebuilt.)*

**Status note (P1-4).** "Nothing silently drops" also gained a server-side seam:
when a LIVE push delivery fails (dead webhook, broken SMTP, bad ntfy topic), the
notifier now leaves an error entry in the zero-config in-app inbox — deduped per
channel while undismissed — telling the user which channel failed and to check
it with Send test in Settings → Notifications, instead of only logging
server-side while the ladder retries. Engine tests:
`tests/unit/test_p1_4_notifications_oob.py`; front-door pins:
`workspace/tests/test_applicant_p1_4_notifications.py`.

### P1-5 — Rescue the stranded hardening commits
**As** the team, **I want** the two unmerged 1.0-hardening waves rebased onto `main`
**so that** observability, PII purge/retention, key rotation, and universal-ATS support
are available for Phase 2.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:**
- Confirmed the two work commits (`43670ab` wave 1, `cead689` wave 2) and that the old
  merge commit is to be skipped.
- Agreement to land as two PRs.
- **Decision:** OK to archive/delete `claude/applicant-production-ready-7iep6h` after landing.
**DoD:**
- [x] Wave 1 (observability alerting, learning biasing, truthfulness fail-closed) and
      Wave 2 (universal-ATS, PII purge/retention, key rotation, chat-onboarding default)
      cherry-picked onto a main-based branch; conflicts resolved (re-implement where a
      pick fights too hard, using the commit as spec).
      *(Superseded: an audit found both waves' content already on `main`, landed via
      separate PRs between the commit date and now — a cherry-pick conflicts because
      `main` already carries equivalent, sometimes-more-evolved implementations. See the
      status note below.)*
- [x] Both waves' tests green on `main`. *(The wave test surfaces ship on `main` and pass
      — e.g. the wave-1 metrics / scheduler-alerting / truth-fail-closed / learning-bias
      suites, 60 tests, green. They arrived via the superseding PRs, not two fresh rescue
      PRs, because the code was already present.)*
- [x] PII-purge + key-rotation capabilities exist for Phase 2 to build on. *(Verified on
      `main`: `erasure_service`, `retention_service`, `data_lifecycle_service`, the
      `0007_pii_retention_timestamps` migration, and `pg_credential_store` key rotation.)*
- [ ] Old stranded branch archived/deleted (after owner confirmation). *(Skipped —
      requires owner confirmation per DoR; branch retained.)*

**Status note (audit, P1-5).** Two distinct facts. (1) The stranded commit SHAs remain
reachable only on `origin/claude/applicant-production-ready-7iep6h` — `43670ab` (wave 1:
observability alerting #362, learning biasing #237/#238/#239, truthfulness fail-closed)
and `cead689` (wave 2: universal-ATS #173/#177, PII purge/retention #363, key
rotation #361, chat-onboarding default #406); those SHAs themselves never landed on
`main`.
(2) The *features* those commits carry are already on `main`, landed via separate PRs
between the commit date and now — so a cherry-pick is unnecessary and conflicts with the
equivalent, sometimes more-evolved, implementations: e.g. #238 is wired in
`learning_advanced.py` by delegating to the Phase-1 `record_converting_role` rather than
the commit's `_fold_centroid_vector` helper, and the truth-fail-closed steps on `main`
are a superset (they pin the `strict` policy for the P1-13 balanced default).
File-by-file and symbol-by-symbol checks confirm both waves' functionality is present on
`main`; the rescue is therefore complete by supersession. The stranded branch is
retained pending owner confirmation to archive/delete.

### P1-6 — Cost & pace guardrails
**As** a user paying for LLM calls, **I want** to see and cap my spend and application
pace **so that** I never fear a runaway bill.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:** Confirmed which providers report token usage (OpenRouter does); agreed
cost-estimate display locations.
**DoD:**
- [x] Daily target (15) + hard cap (30) surfaced on Today.
- [x] Per-run token usage captured where the provider reports it; per-application cost
      estimate + "today: N applications · ~$X" on Today; monthly projection in Settings.
- [x] Caps enforced server-side; hitting a cap emits a notification (silence never
      means "stopped").

**Status note.** Daily target/hard cap were already enforced server-side
(`core/entities/campaign.py` `clamp_throughput`/`THROUGHPUT_HARD_CAP`, `AgentLoop`'s
`_process_approvals`/throughput-cap gate) — this story added the surfacing + cost half.
Token usage: `ProviderProfile.usage_extractor` (declarative per-provider, mirroring the
existing `extract_text` pattern) pulls `{tokens_in, tokens_out}` from the OpenAI-shape
`usage` block (OpenRouter/OpenAI-compatible) or Ollama's `prompt_eval_count`/`eval_count`;
`OpenAICompatibleLLM`'s optional `usage_recorder` callback feeds a process-lived
`UsageLedger` (`application/services/usage_ledger.py`) from every completion (any code
path). `AgentLoop` drains it each tick into the existing `agent_runs.stats` JSON blob —
no schema change, mirroring the `skip_reason` precedent — so `CostService`
(`application/services/cost_service.py`) can sum it per day/month via a new
`AgentRunRepository.sum_stats_between`. Every dollar figure is an explicit ESTIMATE
(`core/rules/cost_estimate.py`, configurable `LLM_COST_PER_1K_INPUT_USD`/
`LLM_COST_PER_1K_OUTPUT_USD`), never exact billing. New engine endpoint
`GET /api/campaigns/{id}/guardrails`, proxied at
`GET /api/applicant/campaigns/{id}/guardrails` (owner-scoped), surfaced in the Today
modal's header line and a new "Estimated spend" line on each Settings campaign card.
Hitting the cap fires `NotificationService.notify_budget_reached` (deduped per
campaign/UTC-day, same in-app/Discord/email fan-out as the daily digest).

### P1-7 — Backup, restore, export
**As** a self-hoster, **I want** operator backup/restore and a user data export **so
that** an irreplaceable job search is never lost.
**Effort:** M · **Owner:** eng · **Depends on:** P0-1
**DoR:** Confirmed data locations (Postgres, workspace `data/`, config) and that
`update.sh` already has a pre-migration backup step to share code with.
**DoD:**
- [x] `scripts/backup.sh` produces one tarball (Postgres dump + workspace data + config);
      `restore.sh` documented; wired into `update.sh`'s pre-migration step.
- [x] Settings → Account "Download my data" exports a zip (applications CSV+JSON,
      documents, profile, activity) that opens in Excel and a text editor.
- [ ] A scripted backup → destroy volumes → restore drill on the compose stack passes
      clean (app returns whole). **NEEDS DEPLOY VERIFICATION** — `scripts/backup-restore-drill.sh`
      is written and its control flow is covered hermetically
      (`tests/unit/test_backup_restore_drill_script.py`, fake `docker` on `PATH`), but
      actually running `--confirm-destroy` against a live compose stack (real
      Postgres + volumes) has not been done — see PR for issue #659.

### P1-8 — Résumé↔JD keyword / ATS match score *(competitive: match transparency)*
**As** a user, **I want** to see how well each tailored résumé covers the job's
keywords **so that** I trust the tailoring and can approve gap-fixes.
**Effort:** S · **Owner:** eng · **Depends on:** P0-2 (digest/review fixtures)
**DoR:** Confirmed `ResumeVariant.fit_scores` is the storage home; rubric for keyword
coverage agreed.
**DoD:**
- [x] A deterministic keyword-coverage metric (JD terms vs tailored variant text) is
      computed alongside the LLM fit score and stored in `fit_scores`.
      (`MaterialService.select_or_generate` persists `coverage`/`missing_terms`/
      `posting_id` into the variant's `fit_scores` on both the reuse and generated
      paths; the variant library / review surface reads it via the existing
      `GET /api/documents/variants/{campaign_id}` read-model.)
- [x] Coverage chip shown on digest cards; a "missing terms" panel in redline review.
      (Digest rows carry `keyword_coverage`/`keyword_matched`/`keyword_missing`
      computed via the pure `core.rules.jd_match` scorer against the base résumé +
      attribute cloud — honestly omitted when no résumé is on file; `buildDigestRow`
      renders the "Keywords N%" chip on Email-tab + Portal cards; the redline
      review's match line now includes the missing-terms suggestion panel.)
- [x] Missing keywords surface as **suggested redline additions the user approves** —
      never auto-inserted (honours the fabrication guard); a suggested term flows through
      the existing redline approve path. (Each missing term is a chip that only
      prefills the "Ask for a change" box; the user still sends the turn and
      approves the redline, and the engine's truthfulness guard vets the draft.)

### P1-9 — Save-a-job-from-any-page capture *(competitive: capture)*
**As** a user, **I want** to drop any job URL into Applicant **so that** roles I find
myself enter the same reviewed pipeline.
**Effort:** S (+S) · **Owner:** eng · **Depends on:** P0-2; discovery parse/score path on `main`
**DoR:** Confirmed the discovery service can accept a single URL and run it through
parse/score (intake endpoint to be added — currently no direct-URL intake exists).
**DoD:**
- [ ] "Add job by URL" input on Today/Tracker → new owner-gated engine intake endpoint →
      existing discovery parse/score → appears in the digest tagged "added by you".
- [ ] A bookmarklet opens `‹host›/capture?url=…` in a popup that reuses the session
      cookie (no browser-extension packaging/store review for v1).
- [ ] A pasted or bookmarked posting appears scored in Pending within ~1 minute.

### P1-10 — Multiple base profiles = light up multi-campaign *(competitive: parallel tracks)*
**As** a user targeting different tracks, **I want** separate campaigns each with its
own base résumé **so that** e.g. "PM-track" and "Eng-track" run independently.
**Effort:** M · **Owner:** eng · **Depends on:** P0-2, P0-3 (Today filters by campaign)
**Status: DONE** *(no schema change was needed — campaign scoping has been in the data
model since Phase 4a, so no Alembic migration; single head unchanged).*
**DoR:**
- Confirmed `Campaign` is designed multi-ready and `ResumeVariant` is campaign-scoped
  with a root (base) variant — **verified: yes** (`campaign.py`, `resume_variant.py`).
- The dormant `multi_campaign_switcher` nav slot identified.
**DoD:**
- [x] Create a second campaign (name + criteria + its own base résumé); each campaign's
      root variant is its base. *(Settings > Campaign "Start a search" now posts to the
      new owner-gated `POST /api/applicant/campaigns` — the card previously posted to a
      route that didn't exist — the engine seeds criteria from the name, and each
      campaign card gained a "Base résumé" upload row over the existing per-campaign
      onboarding-intake endpoint, so a second search gets its own base without
      re-running the wizard.)*
- [x] The dormant campaign switcher is un-locked and functional; Today/digest/Tracker
      filter by campaign. *(`multi_campaign_switcher` registry entry flipped LIVE; the
      shared switcher — `applicantCampaignSwitcher.js`, lifted from the daily-updates
      panel's own picker — embeds in the Today/Tracker headers with 2+ searches and
      filters client-side; the daily-updates panel keeps its per-campaign picker and
      follows the shared selection. Items with no campaign id are never hidden by the
      filter — a search filter must not vanish action-required work.)*
- [x] Services that assume "the single active campaign" (scheduler tick, digest assembly)
      audited and made campaign-aware. *(Audit result: the scheduler already ticks every
      active campaign and the digest/pacing ledgers were already keyed per (campaign,
      UTC day) — both pinned by test. Fixed: the setup-status suggested-attributes
      reporter read only the FIRST campaign's proposals — it now fans out over all
      campaigns; the apply-readiness reporter already scans all campaigns (any-ready
      wins). Deliberately owner-level and documented as such: the P1-6 LLM spend ledger
      (`usage_ledger.py`) — the guardrail is the OWNER's total spend and the shared LLM
      singleton has no campaign context; per-campaign pacing lives in the loop's own
      per-(campaign, day) ledgers.)*
- [x] The fabrication guard's ground truth scopes to the campaign's own base profile
      (via existing variant lineage), verified by test. *(`tests/unit/
      test_multi_campaign_profiles.py`: a fact true in campaign A's attribute cloud +
      base-résumé text is flagged/blocked under campaign B's ground truth, both at the
      guard seam and through the stored-document review surface; root variants and
      lineage stay campaign-scoped.)*
- [x] Two campaigns run side by side with different base résumés and separate
      digests/pacing. *(Same test file: two active campaigns with distinct base
      résumés each get their own once-per-(campaign, day) digest delivery and spend
      their own daily throughput budget — one exhausting its budget never throttles
      the other.)*

### P1-11 — LinkedIn Easy Apply: detect & tag *(competitive: Easy Apply, step A)*
**As** a user, **I want** Easy Apply-able roles flagged in my digest **so that** I know
the channel exists even before automation.
**Effort:** S · **Owner:** eng · **Depends on:** P0-2
**Status: DONE — server-side detection at discovery, `easy_apply` on the posting,
digest channel per role + Tracker chip.**
**DoR:** Confirmed JobSpy exposes the Easy Apply attribute in discovery results.
*(Verified against the vendored python-jobspy: `easy_apply` is a scrape-input
attribute, and LinkedIn rows expose the channel via `job_url_direct` — a fetched
detail page with no external apply URL means the apply flow is hosted on
LinkedIn itself. Detection reads both signals, conservatively: a row whose
detail was never fetched stays untagged, never guessed.)*
**DoD:**
- [x] Discovery marks Easy Apply-able postings; the digest shows the channel per
      role. *(`detect_easy_apply` in `adapters/discovery/jobspy_searxng.py` →
      `JobPosting.easy_apply` (+ column, migration `0012`); digest rows/email
      carry the channel; Tracker board rows chip it —
      `emailLibrary/applicantDigest.js` + `applicantTracker.js`.)*
- [x] Zero automation/login risk introduced by this step (detection only). *(The
      tag is computed purely from the scraped row discovery already had — no new
      requests, no login, no automation; the chip is render-only.)*

### P1-12 — Give each engine capability a narrative FE home
**As** a user, **I want** the engine's deeper capabilities to appear intuitively inside
the sections I already use **so that** the powerful backend maps onto the front-end
instead of hiding behind jargon or dead windows.
*(This is the owner's central concern: "the BE is conceptually great… it just doesn't map
into FE intuitively." It's the connective tissue P0-3/P0-4/P0-5 set up — made explicit so
no built capability stays FE-invisible.)*
**Effort:** M · **Owner:** eng · **Depends on:** P0-2, P0-3, P0-5
**DoR:** Confirmed capability→section mapping: screening-answer library, follow-up
drafting, ghosting detection, weekly recap, and the learning/outcomes loop.
**DoD:**
- [ ] Each named capability is surfaced in its narrative home — Today (what needs you /
      what I did overnight), Tracker (per-application status incl. ghosting + drafted
      follow-ups), Activity (the live feed incl. learning adjustments), Daily updates
      (the weekly recap) — **not** as a new standalone window.
- [ ] Each is discoverable by following the loop, without documentation.
- [ ] The reachability audit (traceability docs) is re-checked so no built capability
      remains FE-invisible.

### P1-13 — Truth policy: free rewriting over a fact-gate *(owner directive)*
**As** the owner, **I want** the fabrication guard loosened so the LLM can freely
rewrite résumé and career prose while invented *facts* are surfaced as suggestions
**so that** materials read their strongest without ever inventing career history from
scratch.
*(Owner's policy, verbatim intent: the LLM oversees quality on EVERYTHING; it may
rewrite parts of the résumé and career history; it can ask questions to learn more and
speak more effectively about real experiences; it does not fabricate career history
from scratch. Closest comparable product rewrites freely — we match that freedom and
keep the no-invented-facts line, which is also the P2-5 marketing claim.)*
**Effort:** M · **Owner:** eng · **Depends on:** the existing truthfulness rules
(`core/rules/truthfulness.py`), attribute cloud / provenance plumbing.
**Status: DONE — core + guard seam (PR #643); FE flagged-facts surfacing landed.**
**DoR:**
- [x] Policy defined (above). Fact-class = employers, titles, credentials/certs,
      technologies/skills, dates, numbers. Prose-class = everything else.
**DoD:**
- [x] Guard behaviour is policy-driven (server-side `TRUTH_POLICY`, default **balanced**):
      rephrasing/restructuring passes untouched; only fact-class tokens absent from the
      truth cloud are flagged; **strict** remains available. *(PR #643 —
      `TruthPolicy`/`policy_blocks` in core; `assert_no_fabrication` policy-aware across
      all three guard seams; wired via config → container.)*
- [x] Flagged facts are **surfaced, not silently blocked** — the engine returns them
      (BALANCED never raises) and logs them; the review surface now recomputes them for a
      stored draft (`MaterialService.flagged_facts_for_document` → `GET
      /api/documents/{id}/flagged-facts` → thin proxy → `documentLibrary.js`
      "A few facts to double-check" panel) with one-tap "yes, that's true — add to my
      profile" / "Remove" (pairs with H4 visible-provenance).
- [x] The "asks questions to learn" behaviour is reachable: the profile Q&A-conflicts
      flow surfaces gaps the LLM wants clarified — the base-résumé conflict picker in
      onboarding AND the review panel's "add to my profile" both commit through the
      existing confirm-conflict endpoint (`POST
      /api/applicant/setup/onboarding/{campaign}/confirm-conflict`), so a confirmed
      fact enters the attribute cloud and stops being flagged.
- [x] Review-before-submit and the final-say invariant (P2-8) are unchanged — the human
      still approves every send. *(Untouched; the loosening is safe precisely because of it.)*
- [x] Tests: balanced surfaces vs. strict raises covered; the injection / persists-nothing
      / never-bypasses scenarios now run under **strict** so that path stays covered.
      Full hermetic engine suite green (3769 passed). *(P2-5 claim re-worded in the backlog;
      the citable-evidence artifact itself is P2-5's own story.)*

**Phase 1 spine:** P1-0 (first) → P1-1 → P1-1a (verify layer, after PR #642) ·
{P1-3, P1-4, P1-6, P1-7} in parallel · P1-5 parallel · P1-13 (truth policy — unblocks
tailoring/rewrite work) · P1-8 → P1-9 → P1-10 (competitive track) · P1-11 seeds the
Easy Apply track · P1-12 after P0-3/P0-5 · P1-2 spans the whole phase (external lead
time).

---

# Phase 1.5

The **final move before market is the owner using Applicant on their own real job
search until they trust it.** This is not demo mode (P0-2, which is *synthetic* data for
screenshots/sales) — it runs on a **real** instance: real Postgres, the owner's real
résumé, a real model key, real criteria, real reviewed submissions.

The gate proves three things at once that nothing else in the plan does: **efficacy**
(did it help the owner get responses?), **demand** (would the owner pay for what it did?),
and **trust** (is it honest and legible enough to rely on?). Its purpose is to replace
*anxiety* with *calibrated confidence* — so the honesty invariants below matter as much as
raw quality. You can trust a tool that is honest about being imperfect; you cannot trust
one that might be lying, however good it is.

## Honesty invariants (build/prove during Phase 1; each kills one specific fear)

The engine already leans honest — the weekly recap **omits** outcomes it lacks rather than
fabricating zeros (`digest_service.py`), the **fabrication guard** is a core rule
(`truthfulness.py`), and generated docs carry **provenance** (`LearnedProvenance`). These
stories *prove it holds everywhere* and *make it visible* — the P1-12 FE-mapping idea aimed
at trust instead of features.

### H1 — Receipts, not narration *(kills: overpromise)*
**Effort:** M · **Owner:** eng · **Depends on:** —
**DoD:** Every number/claim the owner reads (Today "what I did", Activity feed, Tracker
counts, digest/recap) is a projection of **recorded actions**, never an LLM describing what
it thinks it did. An audit confirms no claim-path narrates; a test pins it.
**Status: DONE.** The audit record is `docs/design/audits/h1-receipts-audit.md` (every
claim surface → its recorded source), kept honest by
`tests/unit/test_h1_receipts_not_narration.py`: behavioral pins (intent sentence, daily
status push, weekly recap = projections of persisted rows) plus a source scan proving no
audited claim path can invoke a model (with a canary so the scan can't go vacuous). The
claims now *link* to their receipts in the front-door: each Activity row exposes its
recorded run record inline, and Today's "N applications" line opens the run trail it was
counted from (`workspace/tests/test_applicant_h1_receipts.py`).

### H2 — No silent underdelivery *(kills: underdeliver)*
**Effort:** M · **Owner:** eng · **Depends on:** P1-3 (health panel)
**DoD:** Every degrade is loud, per-action: a tailoring stub-fallback, an empty source, an
incomplete prefill, a skipped step all say so at the item level — never ship a quiet
generic result that reads as success. Extends P1-3 from boot-state to per-action.

### H3 — Full-fidelity review *(kills: the embarrassing send)* — **DONE**
**Effort:** S · **Owner:** eng · **Depends on:** —
**DoD:** Before every submit the owner sees the **literal** payload — exact résumé, exact
cover letter, every screening answer verbatim — not a summary. Tested against the
review-before-submit boundary (ties to P2-8).
- [x] The engine records a provisional ``stage: "reviewed"`` submission snapshot AT
      the stop-boundary (pre-fill landing `AWAITING_FINAL_APPROVAL`, refreshed with
      the live document/variant set when final approval is requested): every filled
      value verbatim (keyed by the human label when known), the drafted screening
      answers, the uploaded résumé file, the exact generated documents, the posting
      URL. The old pre-submit 404 gap in `GET /api/outcomes/applications/{id}/snapshot`
      is closed; the route reports the capture `stage`.
- [x] Reviewed **is** sent: the terminal submit promotes the reviewed snapshot
      **byte-identical** (same id/answers/materials/capture time — only the stage
      marker flips to `submitted`); a submitted snapshot is immutable thereafter.
- [x] Reachable at every submit surface: the live-remote "Review exactly what will
      be sent" panel, the Portal final-approval card, and the Today final-approval
      card all render the SAME exported renderer
      (`applicantRemote.js` `fetchSubmissionSnapshot`/`renderSubmissionSnapshot`) —
      one implementation, no summarized sibling; the panel states honestly whether
      it shows what *will* be or *was* sent, and the no-snapshot state stays the
      honest "nothing recorded yet", never a fabrication.
- [x] Owner-gated: the snapshot proxy now uses `require_engine_owner` (the literal
      filled application is the owner's data; a second workspace account is denied).
- [x] Tested against the review-before-submit boundary (ties to P2-8): unapproved
      material still raises `ReviewRequired` and leaves the reviewed snapshot
      untouched; engine pins in `tests/unit/test_h3_full_fidelity_review.py` (7),
      front-door pins in `workspace/tests/test_applicant_h3_full_fidelity.py` (7) +
      `test_applicant_snapshot_routes.py` (13, incl. stage + owner gate) + the
      executable renderer harness `workspace/tests/js/applicantSnapshotFidelity.test.js` (6).

### H4 — Visible provenance *(kills: "it made something up in my name")*
**Effort:** M · **Owner:** eng · **Depends on:** H3
**Status: DONE — per-line provenance traced end to end (engine read → owner-gated proxy →
"Where this came from" in the review panel).**
**DoD:** The review screen traces each generated line to the owner's real history (the
fabrication guard + `LearnedProvenance` made legible); anything unsourced is flagged, not
hidden.
- [x] Engine: `trace_line_provenance` (`core/rules/truthfulness.py`) reuses the fabrication
      guard's own tokenizers/matchers to trace every fact-class token on every line to the
      NAMED ground-truth component — each profile attribute by name, the base résumé, the
      posting being addressed — so the provenance view can never disagree with the guard;
      `MaterialService.line_provenance_for_document` → `GET /api/documents/{id}/provenance`
      (a doc with no reviewable text returns `checked: false` + reason, never a fake clean
      check).
- [x] Front door: owner-gated proxy (`require_engine_owner` — provenance names the owner's
      attributes/résumé) → `documentLibrary.js` "Where this came from" panel in the open
      review, extending the existing provenance surfaces ("What I drew on" =
      `LearnedProvenance`, the company-research panel, the P1-13 flagged-facts
      double-check): per line, each specific is chipped with the source that supports it;
      unsourced specifics are marked "not in your profile yet" (same caution tone,
      actionable in the double-check panel above) — flagged, not hidden.
- [x] Honesty: a failed/unavailable check renders an explicit "couldn't check" note (proxy
      degrades to `checked: false` + reason), never nothing and never a clean check.
- [x] Tests pin the chain: core-rule unit tests (incl. unsourced-set ≡ guard-flag-set
      equality, strict + prose), MaterialService + router tests, proxy pass-through /
      auth / honest-degrade tests, and source-composition tests on the review panel.

### H5 — Calibrated copy *(kills: overpromise at the words layer)*
**Effort:** S · **Owner:** eng · **Depends on:** P1-3
**Status: DONE — sweep run, findings fixed, denylist pinned in both test lanes.**
**DoD:** Every promise in the UI is audited against actual capability state — if TeX isn't
in the running image it does not claim "beautifully typeset PDFs"; if a source is down it
doesn't imply full coverage. Trust breaks at the words layer, so this is load-bearing.
- [x] Sweep run over every user-facing surface (front-door `applicant*.js` +
      `entities.js` + `landing.html` + proxy-route strings; engine shell
      `frontend/static/applicant`; every `src/applicant` string literal). The copy
      base was already largely calibrated (disclaimers carry their negations; the
      empty digest names what was searched; the missing-tools preview says the tools
      are missing). Two live overclaims found and fixed: the Portal recap rendered
      the `discovered` stat as "reviewed N postings" (discovery finds; review is the
      human's step) and `pipelines_started` as "pre-filled N" (started ≠ finished) —
      now "found N postings" / "started pre-filling N"; the wizard résumé tooltip
      promised "I build a polished version" unconditionally — now conditioned on the
      install's document tools, with the honest fallback named (the DoD's TeX example).
- [x] Pinned so it can't regress: an overclaim-phrase denylist (guarantees, 100%-
      certainty, absolute reliability, hiring-outcome promises, coverage/stealth/
      beauty/automation overclaims) with a negation window that keeps honest
      disclaimers passing, run as `tests/unit/test_h5_calibrated_copy.py` (engine
      lane) + `workspace/tests/test_applicant_calibrated_copy.py` (front-door lane);
      the absent-document-tools copy in both render paths is pinned to keep saying so.

### PAG-1 — Run the gate on the owner's real search
**As** the owner, **I want** to run Applicant on my own real job search until I'd
recommend its output unprompted **so that** I launch on evidence, not hope — and without
the anxiety that it overpromises or underdelivers.
**Effort:** L (elapsed, mostly owner-time) · **Owner:** both · **Depends on:** H1–H5,
P1-1, P1-2, real model key + the owner's real résumé.
**DoR:**
- A real (non-demo) instance stood up: real Postgres, owner résumé imported, fresh model
  key, real criteria.
- A **launch threshold N** agreed (e.g. "≥20 real applications where every claim held true
  and I'd have sent each unprompted").
**DoD:**
- [ ] **Practice:** run on roles the owner does *not* care about; for each, the receipt
      matches reality (H1) and the output is genuinely send-worthy.
- [ ] **Live:** graduate to roles the owner *does* care about, approving every send via
      full-fidelity review (H3).
- [ ] **Outcome tracking:** the owner's own funnel (applied → response → interview → offer)
      is instrumented — this number is the efficacy proof, the go/no-go, and testimonial #1.
- [ ] **Go/no-go:** market only after the threshold N is met with every claim holding true.
      A failed claim resets the count and files a bug.

**Launch gate rule:** no public launch (Phase 4/5) until PAG-1 passes. Trust & honesty
(H1–H5 green) is a non-negotiable launch criterion alongside the legal blockers (P2-1, P2-4).

---

# Phase 2

*(Detailed at story level here because several items are launch-blocking and were the
"gaps people hit at the end.")*

### P2-1 — ToS posture + Terms of Use *(launch-blocking)*
**Effort:** M · **Owner:** you (decision) + eng (drafts) · **Depends on:** —
**DoR:** Owner decision on positioning ("assistive automation, human approves every
send"); legal entity identified for the terms to bind to.
**DoD:**
- [ ] Terms of Use + Acceptable Use published, stating the human-final-say posture.
- [ ] The claim is consistent with P2-8 (final-say invariant test).

### P2-2 — Privacy story + policy
**Effort:** M · **Owner:** eng drafts / you approve · **Depends on:** P1-5 (purge/retention)
**DoR:** Confirmed what data leaves the box (only to the chosen LLM provider) and the
GDPR/CCPA export+delete mechanism (builds on P1-7 export + P1-5 purge).
**DoD:**
- [ ] Privacy policy published (local-first; data egress only to chosen provider).
- [ ] Export + delete both work end to end and are documented.

### P2-3 — Security pass
**Effort:** M · **Owner:** eng · **Depends on:** P1-5
**DoR:** `security-review` skill available; scope agreed (secrets-at-rest, deps,
authenticated-endpoint sweep).
**DoD:**
- [ ] Security review run; findings triaged and high/critical fixed.
- [ ] Secrets-at-rest audit + dependency audit + authenticated-endpoint sweep complete.

### P2-4 — License compliance *(launch-blocking, cheap now)*
**Effort:** S · **Owner:** eng + you confirm · **Depends on:** —
**DoR:** Upstream fork license identified.
**DoD:**
- [ ] Verified the upstream license permits commercial white-label.
- [ ] NOTICE / third-party attributions complete (camoufox, patchright, JobSpy,
      moderncv, and all bundled deps).

### P2-5 — Fabrication-guard evidence
**Effort:** S · **Owner:** eng · **Depends on:** P1-13 (aligns the claim to the loosened policy)
**DoD:** The guard's tests are turned into a citable **"rewrites freely, never invents
facts"** claim (employers, titles, credentials, dates, numbers) with a reproducible
artifact — the honest, defensible line under the P1-13 truth policy, not an
over-broad "never rewrites" promise the product does not make.

### P2-6 — LLM output eval harness *(product-value protection — was the biggest gap)*
**Effort:** M · **Owner:** eng · **Depends on:** P0-2 (fixtures)
**DoR:** Golden set assembled (3–4 profiles × ~20 real postings); rubric agreed
(relevance, tone, honesty/zero-fabrication, diff quality).
**DoD:**
- [ ] Harness runs the golden set through tailoring/scoring/digest on every meaningful
      prompt or model change and scores against the rubric.
- [ ] A regression in any rubric dimension fails the check; results are reviewable.

### P2-7 — Sensitive-question policy *(ethical + marketing line)*
**Effort:** M · **Owner:** eng · **Depends on:** the screening-answer library (migration 0011)
**DoR:** Confirmed the sensitive categories (EEO/demographic: race, gender, disability,
veteran; plus work-authorization handling).
**DoD:**
- [ ] The engine **never** auto-answers sensitive/demographic questions — they are
      flagged for the human at review, enforced server-side and tested.
- [ ] Work-authorization questions get explicit, user-confirmed handling.

### P2-8 — "Human final say" invariant test
**Effort:** S · **Owner:** eng · **Depends on:** —
**DoD:** A test proves no code path reaches final submit without an approval record
(citable invariant, like the fabrication guard).

### P2-9 — App-door hardening
**Effort:** M · **Owner:** eng · **Depends on:** —
**DoD:**
- [ ] Strong-password enforced at first login; existing TOTP 2FA surfaced; login attempts
      rate-limited.
- [ ] A reverse-proxy/HTTPS guide (Caddy/Traefik snippet) shipped.

### P2-10 — ATS-parseability proof
**Effort:** M · **Owner:** eng · **Depends on:** P1-2 (generated PDFs)
**DoD:** Generated PDFs run through an open-source ATS parser; fields extract cleanly;
result is a citable "ATS-safe" claim.

### P2-11 — Verified local-only private mode
**Effort:** M · **Owner:** eng · **Depends on:** local model path
**DoD:** A tested configuration where no profile/job data leaves the box (local model
only); documented + asserted.

### P2-12 — Durability drills
**Effort:** M · **Owner:** eng · **Depends on:** P1-2
**DoD:** Kill engine mid-prefill, kill browser mid-run, hit a CAPTCHA wall, take a source
offline — each drill passes (restart-survival) or files a bug.

### P2-13 — Source reliability matrix
**Effort:** M · **Owner:** eng · **Depends on:** —
**DoD:** Discovery quality tested across 2–3 regions/categories; per-source health
surfaced in UI (ties to P1-3); expectations documented.

### P2-14 — LinkedIn Easy Apply: assisted mode *(launch feature; parallel track)*
**Effort:** M · **Owner:** both (you: real aged LinkedIn account; eng: build)
**Depends on:** P1-11, screening-answer library, stealth persistent profile
**DoR:**
- A real, owner-controlled aged LinkedIn account for proof runs.
- Owner-approved consent-screen stance ("automates your LinkedIn account against their
  ToS; you accept the account risk").
**DoD:**
- [ ] Logged-in session in the persistent stealth profile; agent walks the Easy Apply
      modal (screening-answer library handles Q&A) and **stops at Submit** → review/
      takeover surface → human sends.
- [ ] Consent screen shown and recorded before first use.
- [ ] A recorded proof run on the real account exists.

---

# Phase 3

### P3-1 — One-command install, tested targets
**Effort:** M–L · **Owner:** eng · **Depends on:** Phase 1 complete
**DoD:** `docker compose up` verified on Ubuntu/Debian + the Proxmox script + one
NAS-class box; clean upgrade (`update.sh`) and uninstall paths tested.

### P3-2 — Requirements & model matrix
**Effort:** S–M · **Owner:** eng · **DoD:** Published table — models good-enough per
tier, supported APIs, RAM/VRAM minimums, cost-per-application.

### P3-3 — Business model + licensing *(owner decision)*
**Effort:** M · **Owner:** you decide / eng builds · **Depends on:** P2-4, P4-DEC-1
**DoR:** Pricing model chosen (recommendation: paid license via Paddle/Lemon Squeezy,
$49–99/yr or one-time+update-year, free trial mode).
**DoD:** Privacy-respecting license check implemented; trial mode works; purchase flow
tested end to end.

### P3-4 — Docs site
**Effort:** M · **Owner:** eng · **DoD:** Quickstart, FAQ, troubleshooting,
security/privacy pages; generated from the repo so it can't drift.

### P3-5 — Release engineering
**Effort:** M · **Owner:** eng · **DoD:** Versioned releases, changelog, signed images on
GHCR, stable/beta channels.

### P3-6 — Workspace DB migration strategy *(operational gap — decide before first schema change)*
**Effort:** M · **Owner:** eng · **DoD:** A mechanism exists for evolving the workspace
SQLite schema across releases (the engine has Alembic; the workspace does not); the first
post-launch schema change upgrades cleanly in a test.

### P3-7 — Platform matrix *(operational)*
**Effort:** S–M · **Owner:** eng + you decide · **DoD:** amd64-only constraint documented
OR multi-arch built; Docker-on-WSL2 path tested.

### P3-8 — Digest deliverability *(operational)*
**Effort:** S–M · **Owner:** eng · **DoD:** ntfy/Discord defaulted as the recommended
channel; SPF/DKIM guidance shipped for the SMTP path.

---

# Phase 4

### P4-1 — Positioning: name the enemy
**Effort:** S · **Owner:** you + eng · **DoD:** A one-sentence positioning statement
("autopilot with a human final say — self-hosted, private, honest") that every asset flows from.

### P4-2 — Landing page
**Effort:** M · **Owner:** eng · **Depends on:** P0-2 (hero data), P4-1
**DoD:** `landing.html` rebuilt around the demo hero video, privacy stance, pricing, FAQ.

### P4-3 — Proof assets
**Effort:** M · **Owner:** eng (+ you voiceover) · **Depends on:** P0-2, P1-2, P1-4
**DoD:** 2-minute demo video from seeded data; the digest email as a shareable sample;
a before/after tailoring diff.

### P4-4 — Competitive teardown
**Effort:** M · **Owner:** eng · **DoD:** Feature grid + failure modes + pricing for
AIHawk, LazyApply, Simplify, and the tracker/AIApply classes; verifies the current
comp set (confirm Sonara status) and sharpens P4-1.

### P4-5 — Early-access cohort
**Effort:** M · **Owner:** you recruit / eng instrument · **DoD:** 10–20 users with a
feedback channel and a weekly fix cadence; quotes captured for testimonials.

### P4-6 — Pricing validation *(owner)*
**Effort:** S · **Owner:** you · **Depends on:** P4-5, P3-3
**DoD:** Price tested with the cohort before public launch; decision recorded.

### P4-DEC-1 — Source-available vs. closed *(owner decision, needed by P3-3/P4-2)*
**Owner:** you · **DoD:** Decision recorded; interacts with P2-4 fork license; shapes
pricing, distribution, trust.

### P4-DEC-2 — Takeover-desktop scope for v1 *(owner decision, affects P1-2)*
**Owner:** you · **DoD:** In/out decision recorded; adjusts the P1-2 proof matrix and
marketing claims.

### P4-7 — Name check *(cheap now, painful later)*
**Effort:** S · **Owner:** you · **DoD:** Trademark search, domain, social handles, and
self-hosted-store collision check for "Applicant" complete; go/no-go on the name.

---

# Phase 5

### P5-1 — Support machinery
**Effort:** M · **Owner:** eng · **DoD:** Issue templates + a redacted diagnostic-bundle
command + a small Discord/forum.

### P5-2 — Pre-written support surface *(operational)*
**Effort:** M · **Owner:** eng · **Depends on:** P5-1 · **DoD:** Top-20 predictable FAQs
written before launch (no jobs found, empty digest, invalid key, CAPTCHA hit, weak model, …).

### P5-3 — Opt-in error telemetry
**Effort:** S–M · **Owner:** eng · **DoD:** Crash reporting that respects the privacy
story; opt-in; actionable.

### P5-4 — Launch sequence
**Effort:** M · **Owner:** you + eng · **Depends on:** cohort fixes · **DoD:** Soft launch
→ fix top 10 → Show HN + r/selfhosted + Product Hunt staggered a week apart; comparison
content vs. LazyApply-class tools for SEO.

### P5-5 — Post-launch flywheel
**Effort:** ongoing · **Owner:** both · **DoD:** Weekly releases, public roadmap,
testimonial collection; then the expansion decisions — self-hosted app-store listings
(Unraid CA, Umbrel, CasaOS) and an eventual hosted tier.

### P5-6 — Full LinkedIn Easy Apply autopilot *(post-launch, flagged)*
**Effort:** L · **Owner:** eng · **Depends on:** P2-14
**DoD:** Autopilot behind a flag; hard caps well under LinkedIn tolerance (existing pacing
ledger); takeover fallback on checkpoint/2FA; explicit consent; recorded safe run.

---

# Deferred with intent (recorded, not scheduled for v1)

These were discussed and **deliberately cut or postponed** — recorded here so the
decision and its rationale aren't lost, and don't resurface as "did we consider X?".
Each is a fast-follow or later-version candidate, not an oversight.

- **Interview prep pack** *(fast-follow · M)* — we detect interviews and calendar them,
  then stop. A per-interview prep pack (likely questions derived from the JD + your
  profile, answer drafts via the existing chat) closes that loop. I recommended it as a
  pre-launch feature, but it was **not** among the four the owner prioritized for v1 —
  strong v1.1 candidate.
- **Networking / recruiter outreach / referrals** *(defer)* — a different product muscle
  (a CRM); off-strategy for a review-first apply engine. State the deferral on the public
  roadmap so it reads as a choice.
- **Salary data / negotiation content** *(defer)* — data-licensing/scraping burden, low
  differentiation vs. the core loop.
- **H1B / visa-sponsorship filter** *(fast-follow · M)* — niche but *decisive* for that
  audience; feasible later as a discovery criterion from public H-1B datasets.
- **From-scratch résumé builder** *(v1.1)* — the flow assumes an uploaded résumé, so
  first-time job seekers bounce. Acceptable v1 cut **if** the landing page (P4-1) targets
  experienced switchers; revisit for v1.1.
- **Full LinkedIn Easy Apply autopilot** — not cut, but intentionally post-launch and
  flagged; tracked as **P5-6** (depends on the assisted mode P2-14).

# Cross-phase experience & quality (schedule alongside their phase)

### X-1 — Mobile golden-path audit
**Effort:** M · **Owner:** eng · **Schedule with:** P0-6 (add mobile to the harness)
**DoD:** The "digest → review on phone → approve" path walked at 390×844; issues fixed;
mobile added to the visual matrix.

### X-2 — Cross-browser smoke
**Effort:** S–M · **Owner:** eng · **Schedule with:** P0-6
**DoD:** Golden path passes in Firefox + WebKit; the `@supports` solid-panel fallback
looks intentional where glass is unsupported.

### X-3 — Performance budget
**Effort:** M · **Owner:** eng · **Schedule with:** Phase 1
**DoD:** Login→interactive and window-open latency measured; budgets set; cheap wins taken
(boot warm-up, blur/aurora GPU cost on modest hardware).

### X-4 — Accessibility pass
**Effort:** M · **Owner:** eng · **Schedule with:** Phase 1
**DoD:** Keyboard-only completes the golden path; a WCAG-AA contrast sweep across the
theme system passes.

---

# Owner-only decisions, gathered (unblock these early)

| ID | Decision | Blocks |
|----|----------|--------|
| P1-0 | Which keys to revoke; enable secret scanning | first, always |
| P1-2 / P4-DEC-2 | Employer trial accounts; Workday/takeover scope | P1-2 proof runs |
| P1-5 | OK to archive the old designated branch | branch cleanup |
| P2-1 | Terms posture + legal entity | launch |
| P2-4 | Fork license permits commercial white-label | launch |
| P2-14 | Real LinkedIn account + consent-screen stance | Easy Apply |
| P3-3 / P4-6 | Business model + price | packaging, launch |
| P4-DEC-1 | Source-available vs. closed | pricing, landing page |
| P4-7 | Name check on "Applicant" | branding, stores |
