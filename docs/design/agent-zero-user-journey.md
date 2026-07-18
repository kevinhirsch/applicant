# Applicant on Agent Zero — User Journey & Rebrand Blueprint

> **Status: the fully-formed product-experience spec** for the port defined in
> [`../agent-zero-plane-map.md`](../agent-zero-plane-map.md) and
> [`../backlog/agent-zero-port.md`](../backlog/agent-zero-port.md). Everything here is buildable
> with the mechanisms already inventoried (A0 model gate, `_onboarding` plugin precedent,
> `x-extension` breakpoints, engine `/setup/*` truth). Items needing an owner call are tagged with
> their D-number from the backlog's decision table.

## 1. The product, as the user experiences it

You open one app. It looks and speaks entirely as **Applicant** — an assistant whose specialty is
running your job search. You connect a model, tell it about yourself (or hand it your résumé and
confirm what it read), and from then on it hunts, tailors, and pre-fills around the clock — but
**nothing is ever sent without you**: every application stops at a review where you see the exact
documents and answers, line-provenance included, and you press the only submit button there is.
The same assistant is also a capable general helper (files, browsing, scheduling) — but its
job-search powers run through a guarded engine it cannot bypass (D8).

## 2. Rebrand spec — how Agent Zero becomes Applicant

All branding is a **build-time overlay** (`branding/` applied during the Docker build; the vendored
tree is never edited — plane-map discipline). The shipped artifact is scanned by the fail-closed
white-label check.

| Layer | What changes | Mechanism |
|---|---|---|
| App name | `<title>` in `webui/index.html`; `name`/`short_name` in `webui/js/manifest.json` (PWA); `webui/login.html` brand | string overlay at build |
| Marks | `webui/public/`: `favicon.svg`, `favicon_round.svg`, `icon.svg`, `icon-maskable.svg`, `a0-collapsed.svg`, `a0-fullDark.svg`, `darkSymbol.svg`, `splash.jpg` → Applicant marks | asset overlay at build |
| Welcome & sidebar copy | welcome-screen hero + sidebar labels read as Applicant | string overlay + plugin `x-extension` cards (plugin copy is Applicant-native from the start) |
| Agent identity | the assistant introduces itself as **Applicant**; role, tone, and job-search specialty defined in the `agents/applicant/` profile + prompt overlays; selected as default via `A0_SET_agent_profile` | additive files, no upstream edits |
| What stays untouched | internal code paths, upstream docs inside the subtree, license headers (MIT © Agent Zero, s.r.o. — attribution preserved in `THIRD_PARTY_LICENSES.md` / `ACKNOWLEDGMENTS`) | shipped-surface check scopes to the built artifact |
| Copy discipline | every new user-facing string passes the H5 overclaim denylist (no guarantees, no coverage overclaims); capability claims derive from the engine's health report | AZ5-3 |

**Depth of rebrand = D1 — DECIDED (owner): bespoke redesign.** The shipped UI becomes Applicant's
own look and layout, not just A0's chrome renamed. Execution keeps updateability "to the extent
possible": the Python framework subtree stays pristine (pulls stay clean), while the bespoke UI is
a **managed fork of `webui/`** maintained out-of-tree and applied over the pristine tree at build —
upstream UI changes are cherry-picked deliberately. Phasing: the daily loop lands on branded chrome
first (Phases 0–2); the redesign runs as its own workstream so product function is never blocked on
visual design.

## 3. First run — the guided setup, screen by screen

**Stage 0 — install.** The existing path: `scripts/install.sh --apply` (or `proxmox-deploy.sh`)
brings up the stack; the public port now serves the A0 shell. If a login is configured
(`AUTH_LOGIN`, single-user — D4), the user lands on the branded login page first.

**Stage 1 — first open.** The branded welcome screen greets them with one hero card (injected at
the `welcome-actions` breakpoint): **"Set up Applicant — your autonomous job-search agent. It
finds roles, tailors your materials, and fills applications — and never submits anything without
you."** Two ways in, both converge:
- click the card → Stage 3 wizard;
- just start typing → Stage 2 model gate catches it.

**Stage 2 — connect a model (the one hard gate).** A0's native model gate intercepts the first
message, holds it, and offers the three forks it already ships: **cloud key · provider account
(OAuth) · local model**. The plugin's hook syncs the chosen config to the engine
(`POST /setup/llm`) in the same act (D2), so the engine's gate opens without a second ask. The
held message then dispatches — the user's first chat just *works*. This mirrors Applicant's
current rule exactly: a connected model is the only thing that gates beginning.

**Stage 3 — the Applicant setup wizard** (plugin modal, following A0's own `_onboarding`
pattern; resumable — it always reopens at the first incomplete section):

1. **What happens next** — one trust screen: how the daily loop works, the review-before-submit
   promise, and an honest capability line drawn live from the engine's health report (H5: if TeX
   or the browser isn't available, it says so here, not after a failure).
2. **Your profile — fast path:** *"Upload your résumé and I'll fill most of this in."* Upload →
   engine parse-verify → the **double-check line** ("I read N details from your résumé — please
   double-check these") → the parsed values land pre-filled in the sections below, each awaiting
   confirmation, never silently accepted. Font detection prompts if the résumé needs one; the
   LaTeX conversion preview renders with **accept/reject** (rejecting keeps the docx path — both
   are first-class).
3. **Your profile — the sections** (each savable/resumable, mirror of today's intake): identity →
   work authorization → location → target roles → search criteria → compensation → work history →
   education → key attributes → EEO (all default "decline to self-identify"; voluntary, never
   AI-guessed) → references (optional).
4. **Completion — the engine's truth, verbatim.** The wizard reads `apply_ready` /
   `apply_missing[]` and says either **"You're all set — I'll start looking and check in with a
   daily digest"** or **"Almost ready — I still need: [your phone number, search criteria…]"**,
   each missing item deep-linking to its section — or the user can just tell the chat, which
   updates the profile through the confirmation gate.

**Skipping is safe and honest.** Everything except the model is skippable. Until `apply_ready`,
the agent is a fully working general assistant; job surfaces show as **locked with the reason**
("Finish your profile to start applying — 2 things missing"), a persistent *Finish setup* chip
sits in the sidebar, and the wizard relaunches any time from Settings. Asked "why aren't you
applying yet?", the agent answers from setup-status — receipts, not vibes (H1).

**Stage 4 — what unlocks when** (the four-state gating, engine-derived — no dead UI):

| Unlock | Requires |
|---|---|
| Chat + general assistant | model connected |
| Portal, digest, documents/review, tracker, results | profile complete (`apply_ready`) |
| Email digest delivery | notification channels configured (Settings, optional) |
| Live takeover / remote view | **health-derived**: the four-state gating reads the engine's sandbox/dormant registry; if the deployment lacks a takeover-capable sandbox (e.g. the optional `takeover-desktop` service is absent), the surface shows **locked with the reason**, never a dead button |
| Desktop assist, aggressiveness control | ship present-but-grayed (dormant registry) |

## 4. Daily use — the five journeys

- **J1 · Morning triage (~5 min).** A digest notification arrives (in-app center; Discord/email
  if channels are on — the engine's ladder, D5). The Portal panel lists today's matched roles:
  approve / pass-with-reason / open details. Declines feed the taste model.
- **J2 · Review & submit (the heart of the product).** A pending action says *"Ready for your
  review."* The review shows the **literal** résumé, cover letter, and every screening answer
  (H3), with per-line provenance and any unsourced line flagged (H4); redline edits round-trip
  through the engine. On approve, the live session panel opens at the **stop boundary**: the
  form sits filled, and the user picks one of exactly two affordances — **"Submit it for me"** or
  **"I submitted it myself."** Nothing else submits.
- **J3 · Chat-driven work.** "Find me staff roles at healthcare companies" (criteria via
  confirmation gate) · "Save this job: `<url>`" (intake tool) · "What did you do today?"
  (answers are projections of the run log — H1) · "Why did this application stall?" (honest
  per-item state — H2).
- **J4 · Hands-off.** The engine's 24/7 loop discovers, scores, tailors, pre-fills. When it hits
  a human-only step (2FA, CAPTCHA, account creation, a question it can't honestly answer), it
  parks a pending action and escalates politely. Nothing self-submits, ever.
- **J5 · Track & tune.** The tracker board records what happened; the results funnel shows what
  converts; the mind panel surfaces what the assistant wants to remember — additions only land
  through curation approvals.

## 5. Integrations — Google, MCP, and everything else

Two distinct planes, presented honestly in the UI (this distinction is the answer to "how do I
connect Google?"):

**Plane 1 — assistant integrations (A0-native).** Settings → **Connections** (A0's MCP tab,
rebranded): the user adds any MCP server — a Google Workspace MCP, Notion, Slack, anything — via
the existing UI (paste config → scan → tools appear). A2A connectors and A0's integration plugins
(email/Telegram/WhatsApp) live here too. These extend what the **assistant** can do in chat
(read your calendar, draft emails, look things up). The Applicant engine is pre-registered here
out of the box — visible in the same list, marked as the job-search capability.

**Plane 2 — job-search data lanes (engine-backed).** The engine's interview-detection,
inbox-scanning, and research lanes run through the companion service (IMAP/CalDAV/SearXNG), not
through Plane-1 MCP servers. The plugin ships a **Settings → "Email & Calendar for your job
search"** subsection where the user connects the mailbox and calendar these lanes read/write
(Gmail via app password/IMAP + CalDAV today). Copy says plainly what it's for: *"Applicant scans
this inbox for interview invitations, rejections, and offers, and puts detected interviews on
this calendar."* **(This re-homing is a real port gap the old Settings covered — tracked as
AZ3-6.)**

**The rule that keeps this safe:** Plane-1 integrations are general-assistant abilities. They
never become a path around the engine — a Google MCP can read your calendar, but applying,
filling, and submitting remain exclusively the engine's guarded lane (AZ5-1's negative test
covers third-party-tool bypasses too).

**Convergence — DECIDED (D9 → Phase AZ-7):** the lanes migrate from IMAP/CalDAV to MCP providers
(an engine-side adapter feeds lanes A–C from e.g. a Google MCP), the two planes' credential setup
collapses into Connections, and the companion retires after cutover. The companion path still
ships first because it exists and is tested.

## 6. Notifications — fully formed

**One authority, one center.** The **engine stays the source of truth** for every job-search
notification (D5) — its notification service, idempotency, and the approval **escalation ladder**
are untouched. The plugin renders that truth into A0's native notification center; there is never
a second job inbox.

| Piece | How it works in the A0 shell |
|---|---|
| Taxonomy | **Action-required** items (final approval, a question, 2FA, account step) persist in the **Portal** until resolved and drive the badge count; **informational** items (digest ready, application progressed, source shortfall) pop a toast and land in the center's history. Same split as today. |
| In-app delivery | the plugin bridges engine notifications into A0's `NotificationManager` (priority-mapped), over A0's Socket.IO state sync; dismiss/read syncs back to the engine (`dismiss_notification`) so the two views can't drift |
| The escalation ladder | unchanged engine behavior: an unanswered approval escalates channel-by-channel (in-app → Discord → email), idempotent per item, **quiet hours respected**. The ladder's "web" rung = the A0 center + Portal badge |
| Channel setup | Settings → "Notifications" (plugin subsection, §3.1 #6): connect Discord/email, **send-a-test**, quiet hours — configuring *fan-out of the same items*, never separate feeds |
| Phone push | the stack already ships **ntfy**; wiring it as an opt-in channel (and/or PWA push) is the distribution question tracked as **D10** |
| The agent's own voice | A0's `notify_user` tool remains for general-assistant notices, but the applicant profile instructs the agent to **never synthesize job-status claims** — job notifications come only from the engine, so every count and claim stays a projection of recorded actions (H1) |
| Honesty | degrades are loud per-item (H2): an empty digest says why, a failed channel send surfaces in the center and the health panel — never silent |

**Journey snapshot:** overnight the engine finds 6 roles and finishes 2 pre-fills → morning: one
digest notification (in-app + Discord if configured), two action-required Portal items → the user
triages J1/J2 → items clear from the Portal as they're handled; history stays in the center. If
the user ignores an approval past the ladder's window, email is the final nudge — and if quiet
hours are on, everything waits until morning.

## 7. Interactability & the desktop — how you work *with* it

Three interaction surfaces, each with a clear role and a hard line between the last two:

**1 · Chat + Portal — the command-and-decision plane.** Steer in plain language mid-run
("pause", "skip that one", "focus on remote roles" — criteria changes confirm before applying);
watch streamed reasoning and per-step progress in the chat's process groups; approve/decline/
answer from the Portal. A global pause/kill-switch stays one click away in the status strip.
Voice in/out rides A0's native speech settings.

**2 · The Canvas + the agent's desktop — the general co-work surface** *(per D12: curated by
default — job-search surfaces lead, and the desktop/canvas/plugin-hub sit behind a "power tools"
toggle the redesign bakes in)*. A0's right-canvas is
where you *work alongside* the assistant: Applicant's panels (documents & redline, gallery,
tracker, results) mount as canvas tabs, so a tailored résumé opens next to the chat that's
discussing it — edits round-trip through the engine's redline review, provenance flags inline
(H3/H4). Around it, everything A0's canvas natively offers stays available for general work: the
file browser/editor, drag-and-drop attachments, the Dockerized **XFCE desktop** where the agent
drives real GUI apps and its annotatable browser for research, and Time-Travel snapshots
(see-what-changed / roll back) for the agent's workspace files. **Job-search truth lives in the
engine's Postgres, not in these files** — snapshots never roll back applications.

**3 · The live application window — the guarded surface.** Watching and taking over a *real*
application happens in a visually distinct panel — the embed of the **engine's** sandboxed
browser (view → click-to-take-over → resume 2FA/account steps → the stop boundary's two submit
affordances). It is deliberately **not** the A0 desktop: two different browsers with different
rules. The agent's own browser/desktop **may** drive real GUI apps and ordinary websites for
general work — the prohibition is precise: it never opens **live job-application flows** (ATS
logins, application forms, uploads) and never performs an **application submission**; those exist
only in the engine's guarded lane (AZ5-1's negative test). The engine's browser is never used for
general browsing. The UI labels them differently —
*"Assistant's workspace"* vs *"Live application session — guarded"* — so the safety split reads
as a product feature, which it is. The optional `takeover-desktop` service (remote Chrome over
CDP) remains the engine-side sandbox variant; when it is absent, the takeover surface reports
itself unavailable through the same health-derived gating (§3 Stage 4) rather than pretending.
FR-CUA desktop assist ships present-but-grayed until its driver is baked in, exactly as today.

## 8. Every feature teaches itself — the instructions gate

**No feature ships without workable end-user instructions.** For every surface in this blueprint,
the user must be able to answer "how do I make this work?" without leaving the product:

- **In place:** every **user-facing surface** carries a help affordance — plugin panels, the
  Portal, settings and model setup, the embedded live-application (takeover) view, and the
  native A0 surfaces the product ships (chat, canvas/files, scheduler, Connections) alike —
  plain-language, step-by-step ("To connect Discord notifications: 1. … 2. … Send a test."),
  tooltips on every control, no spec jargon. No surface class is exempt. This is parity, not new
  doctrine: the current front-door's per-surface help is pinned by tests (the lens-12 help
  suite), and the port carries that bar.
- **Workable means verified by following them:** a story's instructions are done when someone
  (the playtest agent, then the owner) completes the feature's task using *only* the on-surface
  instructions — a first-run walkthrough check in the adapted playtest protocol, not a copy
  review.
- **Honest instructions:** help copy obeys H5 — it describes what the feature actually does in
  this deployment (if TeX isn't installed, the résumé help says the docx path is active), and
  setup steps name their real prerequisites (app passwords for Gmail, invite scopes for Discord).
- **The assistant is the fallback manual:** "how do I …?" in chat answers from the same help
  content and can deep-link the surface — one source of truth, two doors.

## 9. Decisions raised by this blueprint — **all resolved** (full table: backlog §5)

| # | Decision | Outcome |
|---|---|---|
| 1 | Integrations posture (D9) | **Converge onto MCP providers — committed as Phase AZ-7**; companion ships first |
| 2 | Depth of rebrand (D1) | **Bespoke redesign** — managed `a0-webui/` fork, framework subtree pristine |
| 3 | Phone push / PWA (D10) | **ntfy ships as an opt-in ladder channel**; PWA push deferred |
| 4 | Model-connect forks (D11) | **Keep all three** (cloud key / provider account / local), job-seeker copy |
| 5 | Desktop/canvas exposure (D12) | **Curated default + "power tools" toggle**; two-browser labeling applies when visible |
