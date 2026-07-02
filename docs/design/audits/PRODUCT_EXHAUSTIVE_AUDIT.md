# Applicant — Exhaustive Product Audit (depth-to-surface)

> **The brief.** One final, completely exhaustive pass — from the depth of the product to the
> surface — across UI, UX, product gaps, engagement, delight, trust, and the fastest high-value
> wins, to make Applicant an *invaluable, addictive, and delightful* product. Ranked; hundreds of
> suggestions.
>
> **Method.** Eight strategic lenses run in parallel by independent auditors, each grounded in the
> real tree (`src/applicant/` engine + `workspace/` front-door) and the spec/feature-map/journey-map,
> each told **not** to rehash the 157 pixel-parity items already in `APPLE_GENIUS_IMPROVEMENTS.md`.
> The seven completed lenses produced **358 concrete, file-anchored, ranked suggestions**, preserved
> verbatim in [`exhaustive/`](./exhaustive/):
>
> | Lens | File | Items |
> |---|---|---|
> | Product gaps & competitive parity | [`product-gaps.md`](./exhaustive/product-gaps.md) | 48 |
> | Engagement & habit loops | [`engagement.md`](./exhaustive/engagement.md) | 48 |
> | Delight & emotional design | [`delight.md`](./exhaustive/delight.md) | 55 |
> | Trust, transparency & agent control | [`trust-transparency-control.md`](./exhaustive/trust-transparency-control.md) | 53 |
> | UX flows & information architecture | [`ux-flows-ia.md`](./exhaustive/ux-flows-ia.md) | 47 |
> | Outcomes & the learning story | [`outcomes-learning.md`](./exhaustive/outcomes-learning.md) | 48 |
> | Quick wins & cross-cutting (+ gap-closing) | [`quick-wins-cross-cutting.md`](./exhaustive/quick-wins-cross-cutting.md) | 59 |
> | *Activation & onboarding funnel* | *(agent stalled; synthesized into §7 below)* | — |
>
> This master doc is the **overseer synthesis**: the systemic findings, the ranked cross-lens
> shortlist (quick wins first), the thematic backlog, and the concrete plan to close the coverage
> gaps. Tags: `[V]alue high·med·low`, `[E]ffort S·M·L`. Anchors point at the front-door because
> **reachability is the definition of done** (CLAUDE.md principle #2).

---

## 1. The one finding that explains most of the list

**Applicant is a superb machine wearing a barren dashboard.** The single most repeated discovery —
surfaced *independently* by six of the seven lenses — is that **the engine has already built the
capability, and the front-door never exposes it (or hides it behind the admin-only Debug modal).**
The product's biggest wins are not new features; they are **reachability**.

Built, tested, and dark today:

- **A complete post-submission lifecycle** — tracker state machine (`post_submission_service.py`:
  `submitted → rejected → ghosted → awaiting-response → following-up → archived`), timed follow-up
  drafting (`followup_service.py`), ghosting/rejection detection, and interview-event detection
  (internal calendar callback) — **no engine router, no front-door surface.** Every competitor
  (Teal, Huntr, Simplify) leads with exactly this.
- **The whole outcomes/learning corpus** — per-variant interview-conversion rate, per-source
  conversion-weighted funnels, the learned converting-role signature, feature/taste stats — reachable
  only via the **admin-gated** Debug → Insights tab, or buried in the Memory criteria editor. The
  *owner of a single-user self-host* — the person who most needs "is this working?" — cannot see it.
- **Momentum data** — the matched→approved→submitted funnel and per-run stats — computed and rendered
  **admin-only**, so the returning user sees a to-do queue, never felt progress.
- **The honesty artifacts** — the immutable submission snapshot ("exactly what was sent under your
  name"), the ordered audit-log export, the fabrication-guard attestation — admin-only or unshown,
  precisely when/where the non-admin owner is deciding whether to trust the agent.

The corollary: **the payoff beat (Journey Map Beat 6) currently fails the project's own
"reachability = done" principle.** Wiring up what already exists is the highest-ROI work in the
entire audit, and it is what turns a capable-but-opaque agent into an indispensable partner that
visibly earns and repays trust every day.

---

## 2. The systemic themes (fix once, fix dozens)

Nine cross-cutting patterns recur across the lenses. Each maps to a trust beat and, fixed once,
resolves a whole column of individual findings.

1. **Surface the engine's own data.** A non-admin **Results** surface (funnel, per-source/role/variant
   rates), promoted out of the admin Debug tab. *(outcomes, engagement, product-gaps, trust)*
2. **"While you were away."** An overnight/since-last-visit recap on the Portal is the emotional
   payoff of a 24/7 agent, and every lens asks for it. *(engagement, delight, outcomes, trust)*
3. **The missing variable reward: outcomes.** The engine tracks *submission* only; there is no
   response/interview/offer loop — no "🎉 interview at Acme." Wiring outcome capture + the email
   scanner delivers the product's emotional peak *and* the learning loop's strongest positive signal.
   *(engagement, outcomes, delight, product-gaps)*
4. **Control where the user is.** No global pause/kill-switch outside the admin Debug modal; the
   always-visible status strip is inert. A supervised autonomous agent needs a one-tap brake on the
   home base. *(trust, ux-flows)*
5. **Weight the irreversible moment.** Final-submit is a transient text-confirm — no undo/recall
   window, no "here's exactly what will be sent" snapshot preview. *(trust)*
6. **One shared state-view + component kit.** Loading rendered 5 ways; ERROR missing in ~7/16
   surfaces (incl. Remote & Vault, the highest-gravity ones); GATED in only 3/16; no shared list-row,
   spinner, or empty/error/gated primitive. Extract them into `applicantCore.js` and adopt everywhere.
   *(ux-flows, quick-wins, delight)*
7. **Make the loop continuous.** 16 transient modals, zero URL routing, one-way deep-links, a
   redline-approval dead-end — the linear daily loop (digest → redline → approve → takeover → submit)
   is broken into disjoint modal jumps. Add hash routing, "← back to Pending", and a redline →
   "continue to submit" CTA. *(ux-flows)*
8. **One calm, competent, on-your-side voice.** Copy drifts between third-person, first-person, and
   system voice. Pick a first-person, plain, quietly-confident agent voice and apply it to greetings,
   empty states, blocked states, notifications, and errors. *(delight, trust)*
9. **Stillness + safety by default.** Pause polling on hidden tabs, add a fetch timeout (a hung
   engine spins forever today), gate every `infinite` animation for reduce-motion, and give a
   low-power/calm mode. *(quick-wins, delight)*

---

## 3. The Top 25 — highest value / lowest effort first (start here)

The cross-lens shortlist. Ordered by ROI; every one is high-value and most are S/M effort because
they surface work the engine already did.

| # | Win | V·E | Anchor |
|---|---|---|---|
| 1 | **Overnight/"while you were away" recap** on Portal open (searched N, matched M, K need you) | V:high E:M | `applicantPortal.js` render; data in `applicantActivity.js:266` |
| 2 | **Promote the momentum funnel out of admin Debug** to an owner-scoped strip on Portal/digest | V:high E:M | `applicantDebug.js:379`→`/portal/momentum` |
| 3 | **Non-admin Results surface** (funnel + per-source/role/variant rates) | V:high E:M | admin `applicant_admin_routes.py`→owner `/api/applicant/results/*` |
| 4 | **Wire the post-submission tracker to the front-door** (applied→interview→offer board) | V:high E:M | `post_submission_service.py` (no router today) |
| 5 | **Response/interview/offer outcome loop** + celebratory Portal row/toast | V:high E:L | extend `OutcomeEvent`; email scanner `emailInbox.js:227` |
| 6 | **One-tap outcome capture for the owner** (got response / interview / offer / rejected) | V:high E:M | move `record_outcome` off admin Debug |
| 7 | **Global pause / kill-switch on the status strip + Portal** (all campaigns) | V:high E:M | `applicantActivity.js` strip; `applicantDebug.js:621` is per-campaign admin-only |
| 8 | **Pause all polling when the tab is hidden** (Portal 60s/Activity 45s/Update 3s) | V:high E:S | shared `visibilitychange` guard; pattern at `applicantDigest.js:887` |
| 9 | **AbortController + ~15s timeout in `_fetchJSON`** (hung engine → real error, not ∞ spinner) | V:high E:S | `applicantCore.js:27` |
| 10 | **Warm, time-aware Portal greeting** + "I'm on it" empty state | V:high E:S | `applicantPortal.js:353` `_renderEmpty` |
| 11 | **Pre-submit snapshot preview** ("review exactly what will be sent") on the final gate | V:high E:M | `applicantDebug.js:165` snapshot, admin-only + post-hoc today |
| 12 | **Undo/recall window** on authorize-to-submit ("Submitting… [Cancel]" hold) | V:high E:L | `applicantRemote.js:425` |
| 13 | **Redline "All approved" → "Continue to submit →" CTA** (kill the dead-end) | V:high E:M | `documentLibrary.js:2116` |
| 14 | **Persist the "what it never does" trust contract** in the Portal header (not only when empty) | V:high E:S | `applicantPortal.js:338` `_neverDoesHTML` |
| 15 | **Reuse the real spinner** + one shared loading/empty/error/gated kit in `applicantCore.js` | V:high E:S | 5 loading variants across surfaces |
| 16 | **Parse the uploaded resume to pre-fill the profile** (cut the OOBE typing tax) | V:high E:M | onboarding intake; `FR-ONBOARD-3` |
| 17 | **First-light payoff**: on OOBE completion, start discovery + auto-open Portal/Activity | V:high E:M | `applicantOnboarding.js:1614`; Journey Beat 2 |
| 18 | **Weekly recap** notification + card (sent/interviews/offers, best source) | V:high E:M | reuse digest fan-out; `digest_service.py` |
| 19 | **Per-variant A/B scoreboard** (uses, interview-rate, "use Variant A more") | V:high E:M | `resume_variant.py:72`; Variants tab shows fit only |
| 20 | **aria-labels on icon-only rail + close buttons; status strip = live region** | V:high E:S | `index.html:838`; `applicantActivity.js:104` |
| 21 | **Clickable notification/toasts** (open the surface) instead of "go find it" text | V:high E:S | `ui.js:364` action slot, unused by Applicant |
| 22 | **Company/employer intelligence brief** per digest row (reuse deep-research) | V:high E:M | `material_service.py` research, never surfaced |
| 23 | **Resume↔JD match-score explainer** (matched/missing keywords) in digest/redline | V:high E:M | `ats_match_rate.py` internal-only today |
| 24 | **Inline "Retry" on every error state** (+ 401-vs-engine-down messaging) | V:high E:S | Gallery/Compare/Debug/Chat/Vault; `applicantCore.js:34` |
| 25 | **Iframe/shadow-DOM field penetration** (silent Workday/Taleo pre-fill failures) | V:high E:M | skyvern-parity Gap #2; `PlaywrightPageSource` |

---

## 4. The backlog by theme (the full 358, clustered)

The complete, ranked lists live in [`exhaustive/`](./exhaustive/). Below is the thematic index —
where each cluster's items live and the headline of each — so the backlog is navigable without
re-reading seven files. Citations are `lens#item`.

### A. Reachability — surface what the engine already built *(highest ROI)*
The tracker/follow-up/ghosting/interview lifecycle (product-gaps #1–5), the outcomes funnel &
per-variant/-source analytics (outcomes #1–10), momentum promoted out of admin Debug (engagement
#1–2), owner-reachable outcome capture, audit log, and submission snapshot (trust #10,17,51;
outcomes #29–30). **~30 items, mostly V:high · E:S/M.**

### B. The daily ritual — a reason to return + a reward
Overnight recap, momentum scoreboard, streak (supportive, not punitive), empty-day reframing, a
consistent daily-time trigger, "today at a glance," milestone celebrations, inbox-zero moment
(engagement #1–16; delight #1–3,15–21). **~35 items.**

### C. The variable reward — outcomes & wins
Response/interview/offer tracking, a "Wins" feed, celebratory notifications with the *good* fact in
the copy, benchmarking ("your rate vs typical"), best-match spotlight (engagement #4,11,19,26;
outcomes #2–3,40,43; delight #5). **~20 items.**

### D. Trust, control & the irreversible moment
Global/kill-switch pause, inert status strip made actionable, weighted final-submit + undo window +
pre-submit snapshot, persistent "never does" contract, plan-preview before acting, per-decision
"why", confidence/uncertainty communication, a consolidated "how Applicant protects you" center
(trust #1–53, esp. #1–11,16,46). **~53 items.**

### E. UX flows & IA — make the loop continuous
URL/hash routing, deep-linkable notifications, redline→submit CTA, "← back to Pending", a "Today"
run-through mode, a command palette + keyboard shortcuts for the surfaces users live in, de-dup the
two chat icons + archive/library, complete the state matrix (ERROR/GATED/LOADING/EMPTY), stacking
policy, mobile Remote iframe (ux-flows #1–47). **~47 items.**

### F. Delight & emotional design — restore hope
First-application & interview celebrations (rare, tasteful, reduce-motion-gated), blocked/CAPTCHA
reframed as teamwork, reassuring "thinking" copy with real numbers, satisfying redline accept/strike
feedback, one on-your-side voice, warm empty states everywhere, the OOBE send-off, opt-in sound off
by default, one centralized `celebrate.js` (delight #1–55). **~55 items.**

### G. Product gaps & competitive parity — become invaluable
LinkedIn Easy Apply, employer intel, market-salary intel, user-facing match score, screening-answer
library, duplicate-application guard, referral/network prompt, interview-prep generation, offer
comparison + negotiation, manual-apply capture (extension/bookmarklet), self-hosted-privacy as the
marketed wedge, more ATS adapters (product-gaps #1–48). **~48 items.**

### H. The learning story — "getting smarter about *me*"
Learned converting-role signature promoted to Results, narrated insights (not stat dumps),
outcome→learning→behavior loop shown in sentences (kill raw-JSON), per-source conversion *rates*,
confidence/sample-size labels, "roles/sources to drop", Mind given a real home, decline-reasons
rolled up (outcomes #1,6–9,18–27,35,41,44,48). **~25 items.**

### I. Robustness that silently costs applications *(parity with Skyvern)*
Iframe/shadow-DOM penetration, dynamic-element waits + retry, wrong-page/redirect recovery, CAPTCHA
classification for cleaner handoff, submission-confirmation reliability (product-gaps #36–40). **5 items.**

### J. Cross-cutting quick wins
Hidden-tab polling, fetch timeout, spinner reuse, a11y (aria-labels, live regions, focus, role=alert),
inline retry, error taxonomy (401 vs down), keyboard shortcuts, bulk digest actions, Portal filters,
undo via toast slot, persist active campaign, freshness "updated Ns ago", low-power mode, plain-language
microcopy, confirm-before-discard on Vault/Onboarding (quick-wins #1–48). **~48 items.**

---

## 5. Effort-vs-value map (how to sequence)

- **Do this week (V:high · E:S)** — hidden-tab polling, fetch timeout + inline retry + error
  taxonomy, spinner/loading kit, aria-labels + live-region strip, warm greeting/empty states,
  clickable toasts, persistent "never does" contract, promote the "what converts" signature.
- **Next (V:high · E:M)** — the Results surface + momentum strip, overnight & weekly recaps, the
  tracker surface, outcome capture + celebratory loop, global pause, pre-submit snapshot preview,
  redline→submit CTA, hash routing, resume-parse-to-profile, first-light payoff, employer intel,
  match-score explainer.
- **Bigger bets (V:high · E:L)** — the full response/interview/offer outcome loop, the undo/recall
  window on submit, LinkedIn Easy Apply, plan-preview before acting, a "Today" run-through mode.
- **Foundational (do alongside)** — the shared state-view/component kit and the one list-row
  primitive; every surface-level fix compounds off them.

---

## 6. Closing the coverage gaps

The prior audit's §I gaps (the trust-core flows never rendered/audited) are all blocked by **one
missing thing: there is no seed/demo data path** — the crawl opens every surface empty and there is
no engine seed route. The plan (quick-wins #49–59, verbatim in
[`quick-wins-cross-cutting.md`](./exhaustive/quick-wins-cross-cutting.md)):

1. **Build an env-gated seed fixture** (`APPLICANT_ALLOW_SEED=1`) reusing `onboarding_seed.py` —
   inserts a campaign, postings, a pending digest, a redline session, and heterogeneous Portal rows.
   **This single item unblocks every render below.**
2. **`--seed` flag on `scripts/playtest_crawl.py`** → crawl a *populated* product.
3. **Render + audit Beat 3** (digest → redline → approve), **Beat 4** (live takeover / final-submit),
   **Beat 5** (populated Portal + live chat bubbles + streaming), and **Beat 0** (landing + login).
4. **Emulated passes** for a11y (reduce-transparency/motion/forced-colors), responsive breadth
   (320/768/1920), and full-glass performance (CDP tracing on the heaviest surfaces).
5. **Fold the seed→crawl→audit loop into `docs/playtest-protocol.md` §6a** so the gaps stay closed.

Until #1 exists, the highest-gravity beats of the whole product remain **unjudged**.

---

## 7. Activation & onboarding (synthesized)

The dedicated activation lens stalled; its scope is well-covered by adjacent lenses, consolidated
here because the OOBE funnel is make-or-break (the user pays *all* setup cost upfront, before any
value — Journey Beat 1).

1. **Parse the uploaded resume to pre-fill the profile** [V:high·E:M] — the intake is long; deriving
   identity/history/education from the base resume (`FR-ONBOARD-3`) collapses the biggest funnel
   drop into a review-and-confirm. *(also Top-25 #16)*
2. **Auto-detect a local model** [V:high·E:M] — probe common local endpoints (Ollama :11434, etc.) so
   "Connect a model" can be one click, not a form. Reuse the endpoint manager (`admin.js`
   `initEndpointForm`).
3. **A sample/demo campaign or immediate first discovery run on completion** [V:high·E:M] — kill
   Beat 2's dead air; the user should see the agent *working* the moment setup ends. *(engagement #35,
   delight #19, product-gaps #46)*
4. **Progress + reward during setup** [V:med·E:S] — "3 of 5 done" with a completed-count, not just
   "steps remaining"; a warm send-off. *(engagement #36, delight #19–20)*
5. **Resume-health / ATS-parseability score at upload** [V:med·E:S] — surface `ats_parseability.py`
   as an instant value hit before any application runs. *(product-gaps #48)*
6. **Import in-flight applications / LinkedIn export** [V:med·E:M] — bootstrap the tracker + attribute
   cloud so the product isn't empty on day one. *(product-gaps #47)*
7. **Skipped-step breadcrumbs + resume-safe wizard** [V:med·E:S] — surface skipped optional steps in
   Settings; resist accidental dismissal of the blocking overlay. *(ux-flows #31–32)*
8. **Explain residential-egress + EEO policy inline at intake** [V:med·E:S] — consent at the exact
   moment the user types identity/demographic data builds durable trust. *(trust #42,44)*
9. **Sensible campaign defaults** [V:low·E:S] — pre-seed "5/day, continuous" with a one-line rationale
   so the first campaign works before it's tuned. *(quick-wins #36)*
10. **Auto-route to the home base on completion** [V:med·E:S] — open Portal/Activity with a "here's
    your home base" cue rather than dropping the user on the empty shell. *(ux-flows #46)*

*(If the activation agent's file lands, it will be added under `exhaustive/activation.md` and this
section reconciled.)*

---

## 8. The through-line

Applicant already does the hard, tireless work — it discovers, scores, pre-fills, adapts, and learns
around the clock. The gap between "capable" and "invaluable, addictive, delightful" is almost entirely
**surfacing that labor back to the user as felt progress, honest control, and earned trust.** Three
moves would move the product more than all the rest combined: **(1)** a non-admin Results home with the
outcome funnel, **(2)** the overnight/weekly recap that pays off delegation every morning, and **(3)**
the response/interview/offer loop that finally delivers the emotional reward the whole product exists
for. Do those, wire the tracker the engine already built, put a brake where the user's thumb is, and
give the irreversible moment the weight it deserves — and the daily digest stops being a chore queue
and becomes the thing a job-seeker opens first with their coffee, because it reliably tells them they
are moving forward, even when the market is silent.
