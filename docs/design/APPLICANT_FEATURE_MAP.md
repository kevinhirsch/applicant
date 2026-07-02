# APPLICANT — Product Feature Map (for the design reviewer)

> **Purpose.** Product fluency for the Apple-Genius design reviewer. To judge whether a surface's
> design *serves its purpose*, the reviewer must know what each surface **does** and what engine
> capability sits behind it. This is a factual map grounded in the sources — `docs/spec/master-spec.md`
> (the FR-/NFR- catalog), `CLAUDE.md` + `workspace/CLAUDE.md` (architecture), the ~17 proxy routes
> (`workspace/routes/applicant_*_routes.py`), the surface JS (`workspace/static/js/applicant*.js`),
> and the surface registry (`workspace/src/applicant_features.py`). **Documentation only — no product
> code is described as changed.**

---

## 1. Product thesis

**Applicant is an autonomous job-application engine behind a white-labeled front-door.** A self-hosted
service runs 24/7 on a home Proxmox VM and conducts per-campaign job-search **campaigns**: it
agentically discovers postings against evolving, human-editable, self-learning criteria; delivers a
daily **digest** the user approves/declines with feedback; and for approved roles **pre-fills as much
of every application as is technically possible** (account-creation forms, in-form screening questions),
stopping only at irreducible human steps (CAPTCHA, email/SMS verification, final submit) which the user
completes via a one-click live remote session. When warranted it **adapts the resume, writes a cover
letter, and drafts screening answers** — all **reviewed and approved before any submission** — and it
**learns real conversion** (approval + submission) per campaign to bias future discovery and document
selection (Vision, spec §1).

The system is **two apps joined by a bridge** (`CLAUDE.md`): the **engine** (`src/applicant/`, hexagonal
FastAPI, internal-only `api` service) owns all logic; the **front-door** (`workspace/`, a vendored,
white-labeled no-build multi-user AI workspace, the *only* public surface — `applicant-ui` on
`${APP_PORT}` → container 7000) proxies it. Front-door `/api/applicant/*` routes are thin,
auth-protected, owner-scoped proxies over `workspace/src/applicant_engine.py` (`ENGINE_URL`); the engine
calls back through a token-gated channel (`applicant_internal_routes.py`, `APPLICANT_INTERNAL_TOKEN`).

---

## 2. The daily loop / core user journey

**First run (OOBE, gating).** The onboarding **wizard** (`applicantOnboarding.js`) blocks until the two
things that gate automated work are done: **Connect a model → Your profile** (Workday-ready intake +
base-resume upload with a LaTeX-conversion accept/reject gate). It is persistent and resumable and
**MUST complete before any automated work begins** (`FR-OOBE-1/2/3`, `FR-ONBOARD-1/2`). Notification
channels, fonts, and the automation sandbox live in **Settings** (which reuses the exact wizard
renderers via `mountSettingsStep`); the wizard is re-launchable via `window.launchApplicantSetup`.

**The 24/7 loop, per campaign.** Discovery (zero-token JobSpy aggregation + local scoring) → viability
score → **daily digest** (`FR-DIG`, exempt from the Applicant visual style) → the user **approves /
declines with feedback**. On approval the engine provisions an isolated browser sandbox and **pre-fills
maximally** (`FR-PREFILL`); when a role warrants adaptation it enters **material prep** → the
**interactive redline review** (additions + subtractions highlighted vs. base; add / subtract /
free-text revision loop — `FR-RESUME-8`, `documentLibrary.js`) → **approve / decline / send back**.
Finally the **final-submit gate**: the user either **submits themselves in the live session** or
**authorizes the engine to click final submit** (`FR-PREFILL-5`, `applicantRemote.js`). Every
`BLOCKED_*` / `AWAITING_*` / `MATERIAL_REVIEW` state emits a notification, lands in the **Portal**, and
yields capacity (pivot-around-blocker). The engine **cannot** self-authorize a final submit, solve a
CAPTCHA, create an account, or auto-fill EEO fields (spec §7 state machine).

---

## 3. Visible surfaces

Nav lives in `workspace/static/index.html`: a narrow **icon rail** (`#rail-*`), an expanded **sidebar /
toolbar** (`#tool-*-btn`), and **Settings-launched seams** (`#settings-open-*` / `window.*` openers).
Per-section **state** (active / locked / disabled) is computed by `workspace/src/applicant_features.py`
(the `APPLICANT_SECTIONS` registry) from the engine setup-status + dormant-surface registry; `app.js`
greys locked/disabled nav. Nearly every surface is a `.modal` overlay reusing the workspace design
system; the shared **appkit** kits (window / gadget / notice / decision / elements / glass, the
white-labeled Liquid-Glass kit — see `APPLE_GENIUS.md`) provide chrome + a11y, and the `.ow-*` element
classes are the atomic primitives.

### 3.1 Front-door + auth pages

| Surface | Route / opener | What the user does | Engine capability | Primary FR/NFR | Kit + key CSS |
|---|---|---|---|---|---|
| **Landing** | `static/landing.html` (`/`, unauthenticated) | Marketing/entry page ("Applicant — A Self-Hosted AI Workspace"); hero + CTA into the app. | — (static) | `FR-UI-1` (white-label shell) | `.hero`, `.hero-logo`, `.hero-cta` |
| **Login** | `static/login.html` | Username/password sign-in; 6-digit TOTP 2FA field. Multi-user gate. | Workspace `AuthManager` (bcrypt, TOTP, session cookie) | multi-user auth (`workspace/CLAUDE.md`) | `.login-*`, `type=password`, 2FA input |
| **App shell** | `static/index.html` (`/` authenticated) | The home base: icon rail + sidebar + always-visible Activity status strip; hosts every modal surface below. | Front-door SPA; `/api/applicant/features` drives nav state | `FR-UI-1/2`, `FR-UIKIT` | `#rail-*`, `#tool-*-btn`, `#applicant-status-strip`, appkitWindow/appkitGlass |

### 3.2 Core Applicant surfaces (engine-backed)

| Surface | Route / opener | What the user does | Engine capability | Primary FR/NFR | Kit + key CSS |
|---|---|---|---|---|---|
| **Portal** (home base + inbox) | `#rail-portal` / `#tool-portal-btn` → `applicantPortal.js` | The primary queue of everything awaiting input — digest approvals, document/answer reviews, soft errors (supply-missing-detail), agent questions, integral-change confirms, final-submit / take-control. Each actionable inline; badge count; polls 60s. Doubles as the **in-app notification center** (informational rows + browser toasts). | `applicant_portal_routes.py` → engine pending-actions aggregate + resolve, missing-attribute acquire, notifications inbox | `FR-UI-3`, `FR-NOTIF-2/4`, `FR-ATTR-5`, `FR-FB-3` | `.modal` + `.admin-card`/`.og-card` rows; `.applicant-portal-*`, `.cal-btn`, `.settings-select`; reuses `ui.js` `showToast` |
| **Chat / assistant** | `#rail-assistant` / `#tool-assistant-btn` → `applicantChat.js` | Conversational assistant for the job search: fill gaps, edit attributes/criteria (integral changes need confirm), see a pending summary, create/switch campaigns. | `applicant_chat_routes.py` → engine chat (message / confirm / confirm-criteria / campaigns) | `FR-CHAT-1`, `FR-FB-2/3` | `.modal` + `.msg`/`.msg-user`/`.msg-ai` bubbles; `.chat-input-bar`; **appkitChatHint** guardrail |
| **Documents / resume library** (redline review) | `#rail-documents` / `#tool-library-btn` → `documentLibrary.js` | The variant library + the **interactive redline review**: side-by-side highlighted additions/subtractions vs. base; add (free-text) / subtract (mark to remove) / free-text feedback; approve / decline / send back. Submission impossible until approved. | `applicant_documents_routes.py` → engine ResumeTailoring / revision sessions; `ensure-submittable` (`applicantReachability.js`) | `FR-RESUME-6/7/8`, `FR-ANSWER-1`, `FR-NOTIF-4` | `.doclib-applicant-redline`, `.admin-card`; engine-rendered redline HTML |
| **Memory / attributes + learning** | `#rail-memory` / `#tool-memory-btn` → `memory.js` | The per-campaign attribute cloud editor + criteria editor + learned-conversion signal, surfaced transparently and overridable. | engine attribute store + learning (`applicant_memory_routes.py`) | `FR-ATTR-1/3`, `FR-CRIT-2/3`, `FR-LEARN` | `.memory-section`/`.memory-item`, `.memory-badge`, `.cal-btn` |
| **Mind** (assistant memory / playbooks) | `window.applicantMindModule.openApplicantMind()` (button in Memory/Brain surface) | View lessons + style preferences the assistant learned; browse saved **playbooks** (skills); review/approve/deny learning **curation** proposals before they save; forget a line. | `applicant_mind_routes.py` → engine agent-memory (memory / skills / curation / forget) | `FR-LEARN-8` (`FR-MIND`) | `.admin-card` overlay; `.memory-section`/`.memory-item`, `.og-card`, `.applicant-mind-*`, `.cal-btn` |
| **Email / digests & notifications** | `#rail-email` / `#tool-email-btn` → `emailInbox.js` | In-app digest + notification fan-out view; decline-with-feedback. Email/Discord are opt-in fan-out of the same notifications. | `applicant_email_routes.py` → engine digest/notifications + feedback | `FR-DIG`, `FR-NOTIF-1`, `FR-FB-1` | native email/inbox classes; `.cal-btn` |
| **Activity** (status strip + run history) | always-visible `#applicant-status-strip` (polls 45s); `#rail-activity` opens modal | Glance the live "Applicant is: [intent sentence]" strip (live/paused dot); open to see chronological run history (verb-noun intent + stats) + a now/next snapshot + pending count. | `applicant_activity_routes.py` → engine run status / intent / runs / snapshot | `FR-AGENT-7`, `NFR-247-1` | `.applicant-status-strip`, `.is-live`/`.is-paused`; `.modal` + `.admin-card` history rows |
| **Debug / activity (admin ops)** | `#tool-debug-btn` (admin-only) → `applicantDebug.js` | Admin tabs: Activity (per-app history + per-page screenshots + workflow state), Insights (conversion funnel + top roles), Logs (redacted), Variants (library + lineage), Run (mode/target/intent controls), Sources (toggle discovery + explore budget), Tools (enable/disable the agent tool registry), Update. Campaign picker; download audit log. | `applicant_ops_routes.py` + `applicant_admin_routes.py` → engine AdminQuery, run config, discovery, tool toggles, update | `FR-OBS-2`, `FR-UI-4/6`, `FR-LOG-1/2/3`, `FR-DISC-2/5` | `.modal` + `.admin-tabs`; `.admin-card`, `.admin-toggle-sub`, `.settings-select`, `.applicant-debug-*` |
| **Compare** | `#rail-compare` / `#tool-compare-btn` → `applicantCompare.js` | Pick entity kind (applications / postings) + optional campaign scope, supply 2+ IDs, view an engine-generated cross-entity diff table (row per dimension, flagged differences). | `applicant_compare_routes.py` → engine CompareService | `NFR-EXT-1` / `FR-LOG-3` (retrieval) | `.modal`; `.ow-field`, `.ow-select`, `.ow-btn-prominent`, `.ow-field-hint` |
| **Gallery** (screenshots & materials) | `#rail-applicant-gallery` / `#tool-applicant-gallery-btn` (feature-gated) → `applicantGallery.js` | Browse per-campaign captured **screenshots** (page ref + optional live URL) and **generated materials** (resume/cover/answer with kind, approval state, snippet). Campaign picker. Distinct from the workspace's native image gallery. | `applicant_gallery_routes.py` → engine gallery collections | `FR-LOG-2/3` | `.modal` + `.admin-card`; `.settings-select`, `.admin-toggle-sub`, `.hwfit-loading` |

### 3.3 Setup / configuration surfaces

| Surface | Route / opener | What the user does | Engine capability | Primary FR/NFR | Kit + key CSS |
|---|---|---|---|---|---|
| **Onboarding wizard (OOBE)** | auto-blocking overlay when setup incomplete; `window.launchApplicantSetup()` | Gating flow: **Connect a model** (reuses the Local/Remote endpoint manager over `/api/model-endpoints`) → **Your profile** (Workday-ready intake: identity, work auth, history w/ dates, education, references, EEO answers, salary floor, base-resume upload + **LaTeX-conversion accept/reject** gate). Resumable; re-opens at first incomplete step. | `applicant_setup_routes.py` → engine OOBE + onboarding intake + base-resume parse | `FR-OOBE-1/2`, `FR-ONBOARD-1/2/3`, `FR-RESUME-3a`, `FR-UI-5` | `.ow-window` on the dialog; `.admin-tabs`/`.admin-tab`, `.admin-card`, `.ao-*` (step title/desc/nav), `.attach-strip` |
| **Settings (channels / fonts / sandbox)** | Settings → "Set up Applicant" (lazy `mountSettingsStep`) | Configure notification channels (Discord/email/ntfy + quiet hours), font upload/detect/install, and the automation sandbox — reusing the exact wizard renderers, saved independently. | `applicant_setup_routes.py` (channels / fonts / sandbox-connection) | `FR-OOBE-2/3`, `FR-NOTIF-1`, `FR-FONT-1/2`, `FR-SANDBOX` | inherits wizard CSS; `.settings-row`/`.settings-label`, `.settings-select` |
| **Model ladder / endpoints** | Settings → "Set up Applicant" → `mountModelLadder(host)` (`applicantModelLadder.js`) | Edit the ordered, capability-ranked **tier ladder** (L1→N, 1–5): reorder, add/remove; per tier set provider, endpoint URL, model, API key (masked when saved), context window. Escalation climbs the ladder. | engine model-escalation ladder (`setup/llm/tiers`) | `FR-LLM-2/3/4` | `.admin-card`, `.og-card`, `.settings-select`, `.ml-*` (provider/base/model/key/ctx/up/down/del) |
| **Campaign settings / switcher** | Settings → "Campaign" (`mountApplicantCampaignSettings`); `#rail-campaigns`/`#tool-campaigns-btn` (switcher) | Create/rename/archive campaigns; set run mode (continuous / fixed duration / until N viable), daily throughput (1–30, capped), exploration budget; toggle per-campaign discovery sources with learned yield stats. | `applicant_campaigns_routes.py` → engine campaign config + discovery sources | `FR-AGENT-1/2`, `FR-CRIT-4`, `FR-DISC-2/5`, `NFR-EXT-1` | `.admin-card`, `.memory-badge`, `.settings-row`/`.settings-label`, `.cs-*` |
| **Update** | `#rail-update` → `applicantUpdate.js` / `applicantUpdateView.js` | One-click in-UI Update: shows status (offline/no-updater/running/success/failed), streams the live log tail (3s poll), triggers the guarded update. Zero-CLI. | `applicant_ops_routes.py` (update status / trigger) → engine UpdateTrigger + update script | `FR-OOBE-4`, `FR-INSTALL-2`, `NFR-ZEROCLI-1` | `.modal` + `.admin-card`; `.applicant-update-log`, `.cal-btn-primary`, `.odec-confirm` (decision confirm) |

### 3.4 Live-session / credential surfaces (Settings seams)

| Surface | Route / opener | What the user does | Engine capability | Primary FR/NFR | Kit + key CSS |
|---|---|---|---|---|---|
| **Remote view / takeover** | `#settings-open-remote` → `window.openApplicantRemoteSession()` (`applicantRemote.js`) | Watch the live browser pre-fill in an embedded view; **take control** for human-only steps (account creation, verification, CAPTCHA); at final submit choose "I submitted it myself" or "authorize the assistant to finish"; resume after account/detection steps; per-session **desktop-assist** opt-in (dormant/grayed). Egress caveat shown. | `applicant_remote_routes.py` → engine RemoteSessionControl + Sandbox/RemoteView; submit-self / authorize-finish / resume | `FR-SANDBOX-2/3/5`, `FR-PREFILL-4/5`, `FR-CUA` (dormant), `FR-STEALTH-5` | `.modal` + `.ow-window` (large overlay); `.admin-card` control cards, `.cal-btn`, `.memory-toolbar-btn` |
| **Credential vault** | `#settings-open-vault` → `window.openApplicantVault()` (`applicantVault.js`) | Save per-site/per-tenant and global account credentials (sealed, never read back); list saved tenants; auto-capture credentials entered during a live account-creation. | `applicant_vault_routes.py` → engine CredentialStore (encrypted Postgres, libsodium) | `FR-VAULT-1/2/3`, `NFR-PRIV-1` | `.modal` + `.admin-card`; `.ow-field`, `.settings-select` (`type=password`), `.cal-btn` |

### 3.5 Workspace-native surfaces present in the front-door

These are the vendored workspace app's own surfaces, kept in the shell (calendar/tasks/notes/research/
cookbook are workspace-native; the engine reaches some via the internal callback). They are part of the
"~19 surfaces the crawl found" and share the same design system, but are **not** Applicant-engine
proxies (except via `applicant_internal_routes.py` callbacks for calendar interviews / deep-research /
Cookbook local models).

| Surface | Opener | What it is | Notes |
|---|---|---|---|
| **Calendar** | `#rail-calendar` / `#tool-calendar-btn` (`calendar.js`) | Workspace calendar; engine writes interview events via the internal callback. | `.cal-*` classes (the shared button vocabulary) |
| **Tasks** | `#rail-tasks` / `#tool-tasks-btn` (`tasks.js`) | Workspace task list. | native |
| **Notes** | `#rail-notes` / `#tool-notes-btn` (`notes.js`) | Workspace notes. | native |
| **Research** | `#rail-research` / `#tool-research-btn` | Deep-research; engine can trigger `/api/applicant/research` (multi-minute). | `FR-DISC` adjacency |
| **Cookbook** | `#rail-cookbook` / `#tool-cookbook-btn` | Hardware-aware local model serving; feeds the model ladder's local tiers. | `FR-LLM-1` (local) |

---

## 4. Cross-cutting features

- **Portal as inbox + notification ladder.** The Portal is both the pending-actions home base and the
  in-app notification center: action-required items persist and clear when handled; informational
  notifications appear as rows and pop browser toasts (reusing `ui.js` `showToast`, not a rebuilt
  toaster). Discord/email are opt-in **fan-out of the same notifications**. The escalation ladder is
  Discord-with-30s-hold unless pre-empted on web, in-app if the user is verifiably present, email after
  the configurable timeout, idempotent across channels (`FR-NOTIF-2/3`, `applicantPortal.js`).
- **Reachability = feature-state (active / locked / disabled).** `applicant_features.py` computes each
  section's state from the engine setup-status + dormant-surface registry so sections light up as
  configured and **there is no dead UI** (`FR-UI-2`). `active` (engine reachable + backing live),
  `locked` (backing not yet configured — greyed but present, e.g. onboarding incomplete or a dormant
  surface like `desktop_assist`), `disabled` (present-but-disabled by product decision). A requirement is
  "done" only when reachable through the whole chain spec → engine → proxy → JS → nav.
- **White-labeling.** The product is **Applicant**; zero upstream vendor/persona codenames and zero
  `FR-`/`NFR-` jargon in user-facing strings; plain language + tooltips. CI holds a codename denylist
  (`FR-UI-1`, principle #3).
- **Multi-user + owner-scoping.** Every `/api/applicant/*` proxy is auth-protected and owner-scoped;
  the engine owns logic and its gates (e.g. `require_automated_work`) are reused, not re-implemented
  (principle #4).
- **The safety gates (enforced server-side in the engine core, not by the UI):**
  - **Review-before-submit** — generated material cannot be submitted until the user approves
    (`FR-RESUME-8`, redline loop).
  - **Pre-fill stop-boundary** — the engine pre-fills but never clicks the account-creating submit,
    never solves a CAPTCHA, never clicks final submit without explicit authorization (`FR-PREFILL-4`).
  - **Fabrication guard** — adaptation reframes real experience and never fabricates; the guard derives
    its own ground truth from the candidate's true attributes (`NFR-TRUTH-1`, `FR-RESUME-2`).
  - **Sensitive-field policy** — EEO/demographic fields filled only from explicit stored answers,
    defaulting to "decline to self-identify" (`FR-ATTR-6`).
  The UI surfaces these gates; it must never appear to let a caller opt past them.

---

## 5. Design-relevant implications (function → design constraint)

- **Portal (home base + inbox).** It is the single most-used surface and a *dense, heterogeneous action
  queue* (approvals, reviews, questions, errors, live-session handoffs) plus a notification feed. Rows
  must read as one scannable list; the primary action per row is the one tinted CTA (system-blue
  background, neutral label) — resist tinting every row type by category. Toasts are transient, must not
  compete with the persistent rows, and the badge count is a state cue, not decoration.
- **Chat composer.** The composer is a **small element** (a bar). Under the adaptive-legibility rule it
  must **flip light↔dark as a unit** by backdrop luminance (linear-Y ≈ 0.36), not carry its own glass
  slab. The `appkitChatHint` guardrail is a notice, not chrome color.
- **Documents / redline review.** The redline is **content**, not chrome — additions/subtractions
  highlights are semantic color that belongs in the content layer; the surrounding review controls stay
  neutral. Never put glass in this content plane; the highlight legibility must survive Reduce
  Transparency (it is engine-rendered HTML, so contrast is load-bearing, not the optics).
- **Vault (credential sheet).** A credential sheet must be **opaque and a single plane** — secrets
  demand focus; a half-transparent glass sheet that samples content behind it is wrong here. Going
  full-height ⇒ transition more opaque (protect focus). Password fields keep neutral chrome.
- **Remote / takeover.** Hosts a **large live iframe** (media-rich, unpredictable). This is the one place
  Clear-over-media reasoning could apply, but the surrounding controls carry text ⇒ Regular material with
  a stronger veil over the bright video; the large window **does not flip** (too big). The two terminal
  choices ("I submitted" vs "authorize the assistant") are a **decision** — one destructive-weighted, one
  primary — and must be unmistakably distinct (system red vs one tinted CTA), never both tinted.
- **Debug / ops (status-dense).** Tabs of logs, funnels, toggles, screenshots — highly information-dense.
  **Resist accent-hue-on-text**; status must read from neutral ink + system state fills (blue toggle /
  green track / red destructive), not colored labels, or the density becomes noise. Toolbar groups ≤3.
- **Activity status strip.** A **small, always-on bar** ⇒ flips as a unit; the live/paused dot is a state
  fill (system color), the intent sentence stays neutral ink. It is glanceable chrome, so motion is
  restraint (no gratuitous pulse).
- **Onboarding wizard.** A **full-height blocking overlay** ⇒ transitions more opaque to protect focus
  (it is the gate); the `.ow-window` chrome must stay concentric with its controls. It is long and
  sequential — hierarchy comes from typography/padding, not tint.
- **Model ladder.** A reorderable ranked stack (drag/up-down). The order *is* the meaning; the design
  must make rank legible without hueing each tier — position and neutral cards, state fills only for the
  active/selected tier.
- **Digest.** Explicitly **exempt from the Applicant visual style** (`FR-DIG-2`) — it renders as
  email/webpage. The reviewer should not hold it to the glass conventions; it is a separate deliverable.

---

## 6. Source index

- Requirement catalog: `docs/spec/master-spec.md` (§3 FR-, §4 NFR-, §7 lifecycle).
- Architecture: `CLAUDE.md`, `workspace/CLAUDE.md`.
- Surface registry + feature-state: `workspace/src/applicant_features.py` (`APPLICANT_SECTIONS`).
- Proxy routes: `workspace/routes/applicant_*_routes.py`. Bridge: `workspace/src/applicant_engine.py`,
  `workspace/routes/applicant_internal_routes.py`.
- Surface JS: `workspace/static/js/applicant*.js`, `documentLibrary.js`, `memory.js`, `emailInbox.js`,
  and the `appkit*.js` kits. Shell/nav: `workspace/static/index.html`, `landing.html`, `login.html`.
- Design persona + glass reference: `docs/design/APPLE_GENIUS.md`, `docs/design/liquid-glass/`.
