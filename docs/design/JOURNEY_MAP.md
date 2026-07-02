# Applicant — User Journey Map (the trust arc)

> **Purpose.** A design-reviewer's map of the end-to-end user journey through Applicant, framed as
> a **trust arc**: a job-hunter hands an autonomous agent the keys to their livelihood, and every
> screen either earns or spends that trust. This document names the beats, the user's goal and
> emotional state at each, the surfaces that carry the beat, the Liquid-Glass / HIG considerations
> specific to it, and the **audit cut** — the ranked improvement suggestions from
> `audits/APPLE_GENIUS_IMPROVEMENTS.md` that protect that beat. It is the ranking key behind that
> audit's §H.
>
> Grounded in `APPLICANT_FEATURE_MAP.md` (surfaces), `docs/spec/master-spec.md` (the FR/NFR state
> machine), and the parallel Apple-Genius per-surface audit. **Documentation only — describes no
> code as changed.**

---

## The thesis, in one line

Applicant is not a productivity app the user drives; it is an **autonomous agent the user
supervises**. The entire product is a delegation relationship: *how much can I let it do, and how
sure am I it did the right thing?* Every design decision is therefore a **trust** decision. The
journey is the arc of that trust being **granted (OOBE), earned (daily review), tested (takeover),
sustained (steady state), and paid off (outcome)**. Liquid Glass is the right material for this
product precisely because it says *"the system is present but deferential"* — chrome recedes, the
user's own content and decisions are the only saturated thing on screen. When our chrome shouts
(a red title, a pulsing synapse, a saturated event bar), we break the one promise the material
makes.

---

## The arc at a glance

| Beat | User's question | Emotional stakes | Primary surfaces | Trust direction |
|---|---|---|---|---|
| **0. Arrival** | "What is this, and is it safe?" | Curious, guarded | Landing, Login | First impression |
| **1. Grant (OOBE)** | "What do I have to give it before it works?" | Effortful, hopeful | Onboarding wizard, Settings, Model ladder | **Trust granted** |
| **2. First light** | "Is it actually doing anything?" | Anxious, watchful | Activity strip, Portal, Debug | Trust probed |
| **3. Earn (daily review)** | "Did it get *me* right?" | Scrutinizing | Digest/Email, Documents redline, Memory/criteria | **Trust earned** |
| **4. Test (takeover)** | "It's about to act irreversibly — do I let it?" | Highest tension | Remote/takeover, Vault, final-submit gate | **Trust tested** |
| **5. Sustain (steady state)** | "Can I glance and relax?" | Calm, delegating | Portal-as-inbox, Chat, notifications | Trust sustained |
| **6. Payoff (outcome / learning)** | "Is this working — and getting smarter?" | Evaluative | Insights/Compare, Mind, run history | **Trust repaid** |

The beats are **not** strictly sequential after Beat 1 — steady state (5) interleaves review (3)
and takeover (4) every day. But trust is built in this order, and a failure early poisons every
later beat: a user who doesn't trust the OOBE never reaches the redline; a user burned once at the
final-submit gate revokes the whole delegation.

---

## Beat 0 — Arrival

**Goal.** Understand what Applicant is and decide to sign in. **State:** guarded — this is a
self-hosted app they just stood up; they're evaluating whether it looks legitimate.

**Surfaces.** `landing.html` (hero + CTA), `login.html` (username/password + TOTP 2FA).

**Liquid-Glass / HIG lens.** The first glass the user ever sees sets the material's credibility. If
the wallpaper reads as a washed color field or the type isn't the system stack, the "Apple-grade"
promise is broken before login. HIG: the login is a **focused, single-purpose** screen — one card,
one primary action, no competing chrome.

**Audit cut (Coverage gap #3 — unaudited).** Landing + login were never captured. **This is the
single highest-value gap to close next**, because it is Beat 0: the first pixel of trust. Action:
render both, judge hero legibility over the mesh, confirm the system font and one-CTA focus.

---

## Beat 1 — Grant (OOBE) · *make-or-break funnel*

**Goal.** Do the minimum required to unlock automated work: **Connect a model → Your profile**
(Workday-ready intake + base-resume upload with the LaTeX accept/reject gate). **State:** effortful
but hopeful — this is a chore, and every point of friction or confusion is a funnel drop. The user
has not yet seen any value; they are paying upfront on faith.

**Surfaces.** Onboarding wizard (`applicantOnboarding.js`, auto-blocking), Settings deferred steps
(channels/fonts/sandbox via `mountSettingsStep`), Model ladder (`applicantModelLadder.js`).

**Why this beat is make-or-break.** It is the *only* mandatory gate and it comes *before* any payoff.
A wizard that feels janky, dead-ends, or buries the required step is where users quit. Trust is
**granted** here — the user is literally typing their work authorization, salary floor, and EEO
answers into the machine. The intake screen's polish is a proxy for "can I trust this thing with my
identity."

**Liquid-Glass / HIG lens.**
- **Concentric, calm sheets.** Wizard steps should read as one focused sheet with generous rhythm,
  not a raw form dropped on the wallpaper. HIG: onboarding is progressive disclosure — show the step,
  not the whole mountain.
- **Clear affordance for the required step.** The two gating steps must be visually weightier than
  the optional ones; the stepper must make "where am I / what's left" obvious.
- **Hero legibility over glass.** Any welcome text sits over the mesh — it needs a legibility scrim,
  not raw text on gradient.
- **44pt targets + system-blue focus** on every field and control (this is a *form-heavy* beat).

**Audit cut (§H Beat 1).** #19 (designed welcome card, not raw wallpaper text), #9 / #41 (hero
legibility), #30 / #52 (dead-end → wizard CTA), #65–#67 (settings/field focus + 44px), #74–#76
(stepper + required-step emphasis). Systemic substrate: #3 (missing `appkitSheet` — the wizard and
every deferred step should compose one sheet kit, not hand-roll `.modal-content`).

---

## Beat 2 — First light

**Goal.** Confirm the agent is alive and working after OOBE completes. **State:** anxious, watchful —
they've delegated but seen no result; they want a heartbeat. This is the gap between "I set it up"
and "it delivered," and it's where a silent product feels broken.

**Surfaces.** Always-visible Activity status strip (`#applicant-status-strip`, "Applicant is: …"),
Portal (still empty at first), Debug/Activity for the curious admin.

**Liquid-Glass / HIG lens.** The status strip is the product's pulse — a single, glanceable,
non-alarming line. It must read live vs paused **without** color-shouting (the live/paused dot is the
signal; the text stays neutral ink). HIG: **status is ambient**, not a notification — it informs
without demanding.

**Audit cut.** §E observability legibility (#85–#95), and the Portal empty state must be a designed
"nothing needs you yet — here's what will show up here" state, not a blank card (relates §B #25–#39,
Portal-as-home). Coverage gap #2 (dynamic optics: the live spinner / streaming states were never
rendered) sits here.

---

## Beat 3 — Earn (daily review) · *trust earned daily*

**Goal.** Judge the agent's work: read the **digest**, approve/decline roles with feedback; **redline
the resume** (side-by-side additions/subtractions vs base; add / subtract / free-text; approve /
decline / send back); correct **attributes and criteria** so tomorrow is better. **State:**
scrutinizing — this is where the user decides, day after day, whether the agent *understands them*.
Submission is impossible until they approve, so this beat is the load-bearing consent gate.

**Surfaces.** Digest (Email/`emailInbox.js`, exempt from the glass style per FR-DIG), Documents
redline (`documentLibrary.js`), Memory/attributes + criteria (`memory.js`).

**Why this is the daily trust engine.** OOBE is granted once; *this* is earned every single day. The
redline is the most consequential comprehension surface in the product — the user is reading
diffed changes to a document that represents *them* and deciding if the agent's edits are honest and
good. Legibility, honest color, and a clean decision pair are non-negotiable here.

**Liquid-Glass / HIG lens.**
- **Color the content, never the chrome.** Additions/subtractions carry meaning and may use hue —
  but the surrounding tiles, tags, and criteria rows must be neutral. Today Memory rows are framed
  glass tiles with a perpetual synapse sweep and red-tinted pins — chrome shouting over content.
- **One list-row primitive.** Digest items, criteria, memory attributes, and library variants are
  all lists; they should share one flat hairline row (≥44px, hover fill, blue focus), not five
  hand-rolled framings.
- **The decision pair is sacred.** Approve / decline / send-back must be an unmistakable, consistent,
  reachable control trio — the same everywhere the user consents.
- **Redline = a sheet, not a modal-in-a-modal.** The review deserves `appkitSheet`, calm rhythm, and
  the type scale — not a busy stacked overlay.

**Audit cut (§H Beat 2 — substrate; the flow itself is unjudged, Coverage gap #1).** #143 (extract
one `.ow-list-row` and adopt across Memory/Tasks/Library/Email), #122–#124 (kill the perpetual
memory synapse motion + the modal pulse), #125 (pinned = neutral glyph, not red), #85–#95
(observability/legibility), #3 (`appkitSheet` for the redline). **Highest-leverage next action:**
connect a model + seed data and render the digest → redline → approve loop, which is currently
**unaudited** because it was empty.

---

## Beat 4 — Test (takeover / final-submit) · *highest gravity, irreversible*

**Goal.** Get the user through the human-only steps of a live application (account creation,
verification, CAPTCHA) and across the **final-submit gate**: either "I submitted it myself" or
"authorize the assistant to finish." **State:** peak tension — this is the single irreversible
action in the entire product. The engine *cannot* self-authorize; the user is the circuit breaker,
and the UI must make that gravity legible without inducing panic.

**Surfaces.** Remote view / takeover (`applicantRemote.js`), Credential vault (`applicantVault.js`),
the final-submit decision.

**Why this is the highest-gravity beat.** Every other action is recoverable. This one sends a real
application to a real employer under the user's name. The design must (a) make the irreducibly-human
nature obvious, (b) present the decision as a clear, deliberate **pair**, (c) mark the irreversible
option as **destructive** (system red — the *one* legitimate saturated use in the product), and (d)
never let dormant/optional cards push the actual decision below the fold.

**Liquid-Glass / HIG lens.**
- **Destructive = system red, and *only* here.** If red is spent on chrome elsewhere (pins, event
  tags, task badges), it can't carry weight when it finally matters. Reserving red for this gate is
  itself a journey-level argument for the whole neutral-chrome cleanup.
- **One CTA, one live frame.** The live-view frame is content — neutral inset, no custom blue border
  competing with the decision. The "connect a model first" block must be an in-flow notice, not a
  bare tooltip colliding with the header.
- **The decision, above the fold.** Collapse dormant desktop-assist / resume cards to disabled rows
  so the irreversible action is never buried.
- **Vault = calm and sealed.** Credentials are the most sensitive input; the vault should read as a
  single calm sheet ("sealed, never read back"), not a busy triple-form.

**Audit cut (§H Beat 3).** #110–#113 (remote: kill the blue custom border, one CTA, final-submit =
destructive red, explicit decision pair), #104–#109 (vault trustworthiness / calm single-CTA sheet),
#114–#116 (neutral live frame, in-flow notice, decision above the fold). Coverage gap #1 (the live
takeover was empty/unrendered) — **render it next.**

---

## Beat 5 — Sustain (steady state) · *glance & trust*

**Goal.** Live with the agent day-to-day: glance the Portal, clear pending actions, ask the assistant
a question, absorb notifications — all without friction. **State:** calm delegation, *if* the product
earns it. This is where a trusted agent becomes invisible infrastructure and an untrusted one becomes
a source of low-grade dread.

**Surfaces.** Portal-as-inbox (`applicantPortal.js` — the post-login home base *and* notification
center), Chat (`applicantChat.js`), toasts (`ui.js showToast`).

**Liquid-Glass / HIG lens.**
- **The Portal is the home.** It must read as a real inbox/home base — a calm queue of "these need
  you," informational rows, and a badge — not a stack of `.admin-card` chrome. Rows are content.
- **Chat is inline, not modal.** A conversation is a primary surface; system font, iMessage-style
  bubbles, in-flow — not trapped in a modal overlay.
- **Stillness is the tell of a trustworthy agent.** Perpetual motion (synapse sweeps, breathing
  pulses, rail pulses) reads as anxiety. A calm surface says "nothing is wrong; I'll ping you when
  it matters." Every `infinite` animation must be gated for reduce-motion and, mostly, removed.

**Audit cut (§H Beat 4).** #25–#39 (Portal as a real home/inbox), #46–#47 (chat inline, system font),
#122–#124 (kill perpetual memory motion), #144 (gate every infinite keyframe for reduce-motion).

---

## Beat 6 — Payoff (outcome / learning) · *trust repaid*

**Goal.** See that it's working and getting smarter: conversion insights, cross-entity comparisons,
the assistant's learned lessons/playbooks, and the curation proposals the user approves before they
save. **State:** evaluative — is my faith paying off? Is it learning *me* specifically?

**Surfaces.** Insights/Debug funnel, Compare (`applicantCompare.js`), Mind (learned memory +
playbooks + curation, `applicantMind.js`), Activity run history.

**Liquid-Glass / HIG lens.** Data surfaces should be legible and honest: structured logs, a navigable
compare table, and a Mind panel where the user stays in control of what the agent remembers (approve
/ deny curation, forget a line). HIG: **the user is always the authority over the agent's memory** —
learning is transparent and reversible, never a black box.

**Audit cut (§H Beat 5).** #48–#50 / #62 (mind panel), #95 (structured logs), #98 (navigable compare).

---

## The through-line (why the systemic themes *are* the journey)

The five systemic themes from the audit (§A / the improvements doc header) are not incidental
cleanups — each one maps directly onto a trust beat:

1. **Compose the vendored kit, don't hand-roll chrome** → every beat reads as one coherent system,
   not a patchwork; incoherence reads as "unfinished," which reads as "untrustworthy."
2. **One list-row primitive** → Beat 3/5: the surfaces the user *lives in* (queues, reviews) feel
   like one product.
3. **Fix the tier-gate split** (house-theme CSS vs theme-frosted/glass-full JS) → the glass either
   works or it doesn't, on every beat; a half-applied material is worse than none.
4. **Kill perpetual motion** → Beat 5: stillness is the visible signature of a calm, trustworthy
   agent.
5. **Tokenize 44px / radius / motion / type-scale** → every beat's targets, rhythm, and legibility
   become consistent by construction, not by per-surface luck.

**Color the background, not the label** is the single rule that ties the whole arc together: the only
thing that should ever be saturated is the user's own content and the *one* destructive action at
Beat 4. Reserve red for the moment it matters, keep the chrome deferential everywhere else, and the
material tells the true story of the product — *the system is present, capable, and waiting for your
call.*

---

## What to render next (closing the journey's blind spots)

The audit's Coverage-gap §I is, in journey terms, **"we have not yet seen the trust-core beats with
real content."** Ranked by trust leverage:

1. **Beat 3 + 4 with seeded data** — connect a model, seed a campaign, and render: a populated
   Portal, a live chat with bubbles, the digest → redline → approve loop, and the live takeover /
   final-submit. These are the highest-gravity beats and are currently **unjudged**.
2. **Beat 0** — capture + audit landing and login (the first pixel of trust).
3. **Dynamic optics** (Beat 2/5) — streaming/thinking spinners, toasts, adaptive-ink flip, lensing —
   none visible in stills.
4. **A11y states rendered** — confirm the glass truly degrades under reduce-transparency/contrast/
   motion (a trust promise to a whole class of users).
