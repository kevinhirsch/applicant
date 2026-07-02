# Applicant — Engagement & Habit-Loop Audit

**Lens:** habit formation / the Hooked model (trigger → action → variable reward → investment), applied to a 24/7 autonomous job-application engine whose whole promise is "it works for you while you sleep." The core hook is the **daily digest**, and the pending-actions **Portal** is the home base + notification center.

**One-line thesis.** Applicant has built a *superb machine and a barren dashboard*. The engine already computes real momentum data — a matched→approved→submitted funnel (`applicantDebug.js:379-428`), per-run stats (`applicantActivity.js:266-284`), source yield, learned conversion — but nearly all of it is **locked behind the admin-only Debug tab or shown as neutral ink**, so the returning user sees a to-do queue and a digest of raw rows, never a reason to feel *progress*. The reward is all "work" and no "win." A job search is an emotional marathon where momentum fights despair; the product currently gives triggers and actions but almost **no variable reward, no streak, no overnight recap, no milestone, and no benchmarking** — the four ingredients that turn a chore into a ritual. Below, best-ROI first.

Ethical stance throughout: this is a high-stakes life tool. "Addictive" here means *reliable daily value and honest momentum*, never manufactured urgency or fake wins. Every reward suggestion is grounded in true engine data; where a number could depress (0 responses), the copy reframes toward the controllable (effort shipped), never fabricates.

---

## Tier 1 — The daily ritual: give the digest a reason-to-return and a reward (highest ROI)

1. **Overnight recap header on the digest / Portal ("While you were away")** — [VALUE: high · EFFORT: M] — The product's entire identity is "an agent working for you while you sleep," yet the morning surface opens on a bare pending list. Lead the Portal + digest with a warm first-person recap of what happened since last visit: "Overnight I searched 6 sources, reviewed 47 postings, shortlisted 4, and pre-filled 2 — 3 things need you." The data already exists in `_statSummary` (`applicantActivity.js:266`) and the snapshot endpoint. This is the single highest-leverage change: it converts a silent queue into a visible payoff for delegating. Anchor: new section at top of `applicantPortal.js` `_renderList` + `openApplicantPortal` (currently loads digest then pending with no recap).

2. **A running momentum stat line the user actually sees ("12 applications this week · 3 in review · 1 response")** — [VALUE: high · EFFORT: M] — The matched/approved/submitted funnel is computed and rendered, but **only in the admin-only Debug → Insights tab** (`applicantDebug.js:379-428`, gated `#tool-debug-btn` admin-only). A non-admin owner never sees their own progress. Surface a compact weekly momentum strip on the Portal home base and digest header. This is the "scoreboard" that makes returning worthwhile even on a zero-new-roles day. Anchor: promote `applicant_ops_routes.py` insights out of admin gate into an owner-scoped `/portal/momentum`; render in `applicantPortal.js`.

3. **Streak / consistency mechanic ("You've reviewed your digest 5 days running")** — [VALUE: high · EFFORT: M] — There is zero streak or consistency signal anywhere (grep confirms). The daily review IS the habit to reinforce; a gentle streak on the digest ("5-day review streak — nice") gives the trigger→action loop its self-perpetuating reward. Keep it *supportive not punitive* (job search is stressful): never shame a broken streak, celebrate resumption ("welcome back — 3 new roles waiting"). Anchor: track last-review dates engine-side (Decision timestamps already exist), render badge in digest panel header `applicantDigest.js:160` + Portal.

4. **Variable reward: the "you got a response!" delight moment** — [VALUE: high · EFFORT: L] — The peak dopamine of any job search is "an employer replied." The engine tracks **submission** outcomes only (`outcomes.py`, `OutcomeEvent`) — there is no interview/response/rejection outcome loop surfaced. This is the missing variable reward at the heart of the Hooked model: unpredictable, high-value, emotionally huge. Add an outcome kind for responses/interview-requests (the email urgency scanner in `emailInbox.js:227` already classifies inbound mail) and make it a celebratory Portal row + toast + push: "🎉 Interview request from Acme — 4 days after you applied." Anchor: extend `OutcomeSource`/`OutcomeEvent`, wire the email scanner → engine, new celebratory affordance in `applicantPortal.js` KINDS.

5. **Milestone celebrations (first application, 10th, first interview, resume approved)** — [VALUE: high · EFFORT: S] — No milestone events exist. Milestones are cheap, one-time variable rewards that punctuate the grind. Fire a celebratory toast + persistent Portal card at: first pre-filled application, 10/25/50 submitted, first material approved, first response, first interview. Reuse `_toast` + `_maybeDesktopNotify` already in `applicantPortal.js:113-129`. Anchor: emit milestone notifications from the engine's submission/decision paths; render distinctly (not as a "needs-action" row) in the notification center.

6. **Digest "today at a glance" summary line before the rows** — [VALUE: high · EFFORT: S] — The digest jumps straight into role rows (`applicantDigest.js:_renderDigest`); on an empty day it shows only the "nothing cleared the bar" note. Add a one-line human framing: "4 new roles today, best match 88% · you have 12 in flight." It costs nothing (data is in the payload) and reframes the digest from "a list I must process" to "a briefing worth reading." Anchor: `applicantDigest.js:203` `_renderDigest` top; also the Portal's embedded digest `applicantPortal.js:_renderDigestRows`.

7. **Empty-digest days must still reward the visit** — [VALUE: high · EFFORT: S] — On a no-new-roles day the digest currently shows a dry "No new roles cleared the bar today. Searched: …" (`digest_service.py:34`, `applicantDigest.js:213`). This is the despair-risk moment: the user opened it and got nothing. Reframe toward effort + reassurance: "No new matches today — I reviewed 38 postings against your bar and kept looking. 3 applications from earlier this week are still progressing." Turns a dead end into evidence the agent is tireless. Anchor: `digest_service.py` `EMPTY_DAY_NOTE` + empty branches in both digest renderers.

8. **Push/notification strategy: a scheduled morning "digest ready" ritual trigger** — [VALUE: high · EFFORT: M] — The notifier fires a digest-ready ping (`digest_service.py:274` `notify_digest_ready`) but there is no evidence of a *consistent daily time* the user learns to expect — the trigger is event-driven (whenever the run finishes), not ritual-anchored. A habit needs a predictable external trigger: deliver the digest ping at a user-chosen time ("every morning at 8am"). Same-time-daily is the backbone of the Fogg/Hooked external trigger. Anchor: digest delivery scheduling in the engine loop + a time picker in Settings channels (`applicant_setup_routes.py` channels; quiet-hours plumbing already exists per `notifications.py:67`).

---

## Tier 2 — Progress made visible: momentum fights despair

9. **Portal "inbox zero" celebration on clearing the last item** — [VALUE: high · EFFORT: S] — When the last pending row resolves, `_removeRow` (`applicantPortal.js:671`) silently calls `_renderEmpty` — a muted "You're all caught up." An inbox-zero moment is a *satisfying, earned* reward; make it feel like a win (brief celebratory state, "All clear — I'll ping you when something needs you," maybe a subtle confetti gated by reduce-motion). Anchor: `_renderEmpty` (`applicantPortal.js:353`), only when transitioning from non-empty→empty via user action (not on cold offline load).

10. **A pipeline / status board so "in flight" work is visible momentum** — [VALUE: high · EFFORT: L] — The user approves a role and it vanishes (fade-out, `applicantDigest.js:_fadeOutRow`); they then have no view of "what's happening to the 12 things I approved." That invisible in-flight pipeline is momentum going to waste — and a source of anxiety ("did anything happen?"). A simple Kanban-ish "In progress" view (Approved → Pre-filling → Awaiting you → Submitted → Response) turns the state machine into a visible sense of forward motion. The states exist (spec §7). Anchor: new lightweight surface or a Portal tab reading application states; distinct from admin Debug's Activity.

11. **Surface response/interview outcomes as a first-class "Wins" feed** — [VALUE: high · EFFORT: M] — Complementary to #4: give wins a home. A short "Recent wins" section (responses, interviews scheduled, offers) on the Portal/digest is the emotional counterweight to the rejection-heavy reality of job hunting. Even sparse, it says "this is working." Anchor: once response outcomes exist (#4), render a wins strip above the pending queue.

12. **Weekly recap / "your week in review" digest** — [VALUE: med · EFFORT: M] — Beyond daily, a Sunday/Monday weekly summary ("This week: 14 applied, 2 responses, 1 interview, best-performing source: LinkedIn") gives a lower-frequency, higher-altitude reward and a re-engagement hook for anyone who drifted mid-week. The funnel + source-yield data already exists (`applicantDebug.js:423`). Anchor: new weekly notification composed from the same conversion aggregates; deliver as its own digest email variant.

13. **Progress bars / rings for goals ("target: 5 apps/day — 3 done")** — [VALUE: med · EFFORT: M] — Campaign settings already have a daily throughput target (1–30, `applicant_campaigns_routes.py`) but the user never sees progress against it. A daily/weekly ring or bar ("3 of 5 today") is a classic completion-drive reward and makes the throughput number meaningful. HIG activity-rings guidance is already in the repo (`docs/design/hig/activity-rings.md`). Anchor: read the campaign target + today's counts; render a small ring on the Portal/Activity snapshot (`applicantActivity.js:198`).

14. **"Now/Next" snapshot should quantify the overnight haul, not just intent** — [VALUE: med · EFFORT: S] — The Activity snapshot renders "Right now I'm…/Next I'll…" (`applicantActivity.js:198-226`) but omits the cumulative-since-you-left tally that would make it feel like the agent has been *productive*. Add a "Since your last visit" line to the snapshot card using the run stats already fetched. Anchor: `_renderSnapshot` (`applicantActivity.js:198`).

15. **Make the digest match-score a source of delight, not just data** — [VALUE: med · EFFORT: S] — Each row shows "88% match" as muted 10px text (`applicantDigest.js:260`). A high match is a mini-reward — lean into it: visually celebrate a great match ("Strong match — 92%"), so scanning the digest has peaks, not a flat gray list. Keep honest color in content per the design system. Anchor: `buildDigestRow` score chip (`applicantDigest.js:260`).

16. **Show applications' downstream fate on the row after approval** — [VALUE: med · EFFORT: M] — After approve, the row just fades. Instead, briefly transition it to "Pre-filling now…" then let it move into the in-flight view (#10). Investment (the approve) should visibly produce something — the core "action → reward" link. Anchor: `_onApprove` (`applicantDigest.js:352`) success path.

---

## Tier 3 — Notification strategy & re-engagement (bring them back)

17. **Re-engagement when the user goes quiet** — [VALUE: high · EFFORT: M] — There is no lapsed-user path. If someone stops reviewing digests for 3+ days, approved work stalls (nothing submits without review) and the whole engine idles — the worst outcome. A gentle, escalating re-engagement nudge ("You have 8 roles waiting for a quick yes/no — 2 close soon") via the existing channels recovers the habit. Must be caring, capped, and easy to snooze/mute. Anchor: engine detects review-gap; reuse the notification escalation ladder (`applicantPortal.js` header comment; `FR-NOTIF-2/3`).

18. **Deadline/aging urgency that creates honest, non-manufactured pull** — [VALUE: high · EFFORT: S] — The Portal already computes urgency badges (Overdue/Due soon, `applicantPortal.js:246`) but only inside the modal. Roll a real "2 items close soon" into the *push/badge* so the external trigger carries honest stakes (postings expire, this is genuine). This is ethical urgency: the deadline is real. Anchor: fold urgency into `refreshBadge`/notification titles (`applicantPortal.js:1012`).

19. **Notification content should carry the reward, not just "you have items"** — [VALUE: high · EFFORT: S] — Notifications toast generic labels (`_toastNew`, `applicantPortal.js:98`). A push that says "Applicant found a 91% match at Stripe" pulls far harder than "1 new notification." Put the best/most-rewarding fact in the trigger copy. Anchor: notification title composition engine-side (`digest_service.notify_digest_ready`) + `_NOTIF_KIND_LABEL` (`applicantPortal.js:579`).

20. **Badge should reflect *good* news too, not only obligations** — [VALUE: med · EFFORT: S] — The rail badge counts pending actions + info notifs (`_setBadge`, `applicantPortal.js:981`) — i.e. it's a debt counter. A badge that only ever means "chores await" trains avoidance. Differentiate a "win waiting" (response/interview) so the badge can occasionally mean "open me, something good happened." Anchor: `_setBadge` + notification kinds.

21. **Quiet-hours + "deliver now" is good — add a daily-summary-only mode** — [VALUE: med · EFFORT: S] — Quiet hours and force-flush exist (`notifications.py:67-77`). Offer a "batch me once a day" preference so power-anxious users aren't pinged per-event but still get the ritual digest — reduces notification fatigue that otherwise kills the channel. Anchor: Settings channels + notifier batching.

22. **Desktop/browser notification opt-in is passive — prompt it at a rewarding moment** — [VALUE: med · EFFORT: S] — `_maybeDesktopNotify` only fires if permission is *already* granted and never prompts (`applicantPortal.js:123`). Ask for permission right after the user's first genuinely-good moment (first match approved, first response) when motivation to stay notified is highest — not on cold load. The email reminder path already does a contextual `Notification.requestPermission()` (`emailInbox.js:1081`); mirror that. Anchor: post-first-win hook in `applicantPortal.js`.

23. **Snooze is a good pressure-valve — add "review later today" that re-triggers** — [VALUE: med · EFFORT: S] — Snooze defers to tomorrow morning (`applicantPortal.js:706`). Offer "later today (6pm)" too, so deferral doesn't push a same-day-urgent item a full day. Mirrors the email reminder presets (`emailInbox.js:997`). Keeps momentum within the day. Anchor: snooze options `applicantPortal.js` `_rowShell`/`_wireRows`.

24. **Approve-all is momentum gold — extend beyond digest to a "clear the batch" pattern** — [VALUE: med · EFFORT: S] — "Approve all N" already exists for digest rows (`applicantPortal.js:614`) and is a great low-friction completion reward. Consider a "handle all quick confirms" for stacked integral-change/confirm items so a backlog clears in one satisfying sweep. Anchor: `_wireRows` bulk section.

25. **Snoozed/passed items shouldn't feel like they vanish into a void** — [VALUE: low · EFFORT: S] — Passed roles fade out; snoozed items disappear till tomorrow. A tiny "3 snoozed · 12 passed this week" affordance gives closure and a sense of a managed system (investment made visible). Anchor: Portal footer.

---

## Tier 4 — Variable reward depth & social proof

26. **Benchmarking / social proof ("your response rate: 8% — typical for this market is 4-6%")** — [VALUE: high · EFFORT: L] — Nothing benchmarks the user against reality, so a low absolute number reads as personal failure rather than "you're actually doing well." Honest, anonymized/aggregate benchmarking (or even static market baselines) reframes stats as *relative wins* — the single most powerful antidote to job-search despair. Ethical caveat: only if honest and non-manipulative; static public baselines are safest for a self-hosted single-user app. Anchor: momentum surface (#2) copy layer.

27. **"Best match of the week" spotlight** — [VALUE: med · EFFORT: S] — Elevate the single highest-scoring role of the day/week into a spotlight card at the top of the digest. Variable-reward peaks (some days a 95% dream role appears) are what keep people opening the box. Anchor: digest header, using `viability_score` already on rows.

28. **Reveal *why today's roles are better* when learning improves them** — [VALUE: med · EFFORT: M] — The learning flywheel adjusts criteria from feedback (`digest_service._learn_from_decline`), but the user never sees the payoff of their teaching. When a decline reason visibly shapes tomorrow ("Fewer recruiter agencies today — as you asked"), the *investment* (giving feedback) earns a *reward* (visibly smarter agent) — closing the Hooked investment→trigger loop that creates long-term retention. Anchor: surface criteria-delta application as a digest note; data in `apply_learned_adjustment`.

29. **Streak-adjacent: "agent is getting to know you" progress** — [VALUE: med · EFFORT: M] — The Mind/learning surfaces (`applicantMind.js`, `memory.js`) hold learned attributes/lessons but read as admin data. A light "I've learned 14 things about what you want" progress signal turns accumulated investment into visible relationship-building — a reason to keep teaching it. Anchor: count learned lessons/attributes, show on Memory/Portal.

30. **Celebrate the resume-approved / material-approved moment** — [VALUE: med · EFFORT: S] — Approving a redline (`documentLibrary.js`) is a meaningful act of trust with no reward beat. A brief "Looks great — sending it in for you" confirmation with the role name closes the action satisfyingly. Anchor: redline approve success path.

31. **Post-submit confirmation should feel like a completed rep** — [VALUE: med · EFFORT: S] — Authorizing final submit ends on a plain toast "Authorized — the assistant submitted" (`applicantPortal.js:901`). This is the product's highest-gravity success — mark it: "Application #23 sent to Acme. That's 4 this week." Ties the individual win to cumulative momentum (#2). Anchor: `_renderFinal` authorize handler.

32. **Occasional encouragement copy tuned to the emotional arc** — [VALUE: med · EFFORT: S] — Copy is functional throughout. A light, honest layer of encouragement at low points ("Quiet week for responses — that's normal; you've shipped 11 solid applications") sustains morale. Never toxic-positivity; grounded in their real numbers. Anchor: momentum surface + empty-state copy.

33. **"Anniversary"/tenure nudges ("2 weeks with Applicant — here's the cumulative picture")** — [VALUE: low · EFFORT: S] — A periodic zoom-out reward that shows total impact ("47 applications you didn't have to fill out by hand — ~19 hours saved"). Time-saved framing is the deepest value prop and it's never quantified. Anchor: new periodic summary; estimate from submitted count × avg form time.

34. **Quantify the "it did this so you didn't have to" value continuously** — [VALUE: med · EFFORT: S] — Every pre-fill is unpaid labor the user avoided. A persistent "~14 hours of form-filling saved this month" stat is a uniquely strong, honest retention lever for *this* product specifically. Anchor: momentum surface; derive from pre-fill/submit counts.

---

## Tier 5 — Loop hygiene, friction, and trust-preserving mechanics

35. **First-week onboarding-to-value momentum ("first light")** — [VALUE: high · EFFORT: M] — Journey Beat 2 ("Is it actually doing anything?") is the make-or-break gap between setup and first payoff. After OOBE, proactively show "I'm searching now — first roles usually arrive within a few hours" and fire the first digest/first-match notification as a deliberate activation moment. A silent first day loses the user before the habit forms. Anchor: post-onboarding state in `applicantPortal.js` gated/first-run branches (`_renderGated`, `applicantPortal.js:327`).

36. **The onboarding-gap Portal row should show progress, not just remaining steps** — [VALUE: med · EFFORT: S] — `_renderComplete` lists "still to do: N steps" (`applicantPortal.js:542`). Add the completed count too ("3 of 5 done") — a progress bar reframes the remaining chore as an almost-finished win, improving OOBE funnel completion. Anchor: `_renderComplete`.

37. **Reduce digest decision friction: default the pass-reason, don't hard-gate** — [VALUE: med · EFFORT: S] — Passing a role *requires* a typed reason (`applicantDigest.js:373`, engine-enforced `FR-FB-1`). Mandatory free-text on every decline is friction that discourages triaging — and triaging is the habit. Offer quick-tap reasons ("too junior / wrong location / wrong stack") that satisfy the learning loop with one click (the survey already uses fixed choices, `applicantDigest.js:609`). Lowers action cost → more daily engagement. Anchor: `_onPass` prompt → chip picker.

38. **Toast bursts are capped at 3 but could aggregate into one "3 updates" tap** — [VALUE: low · EFFORT: S] — `_toastNew` fires up to 3 separate toasts (`applicantPortal.js:113`). A single "3 new updates — open" is less noisy and pulls into the Portal (deepening the loop) rather than flashing and gone. Anchor: `_toastNew`.

39. **Presence heartbeat is smart — use it to time rewards, not just suppress pushes** — [VALUE: low · EFFORT: M] — The presence signal (`applicantDigest.js:860-916`) knows when the user is actively here. Use that to deliver a *win* the instant they arrive (in-app celebration) rather than only to suppress a Discord duplicate. Presence → reward timing is an underused engagement asset. Anchor: presence consumer engine-side.

40. **Consistent daily digest *time* + "yesterday you reviewed at 8:12am" learned cadence** — [VALUE: low · EFFORT: M] — Complements #8: learn the user's habitual review time and align delivery + nudges to it, reinforcing the personal ritual. Anchor: engine cadence learning from Decision timestamps.

41. **Streak-safe "vacation mode"** — [VALUE: low · EFFORT: S] — If streaks (#3) ship, add an explicit pause so a deliberate break doesn't feel like failure (respect the stress of the domain). Prevents the dark-pattern trap of streak anxiety. Anchor: Settings + streak logic.

42. **De-duplicate the two digest entry points into one canonical ritual** — [VALUE: low · EFFORT: S] — The digest lives both embedded in the Portal (`applicantPortal.js:1029`) and in the Email "Daily updates" panel (`applicantDigest.js`), plus deep-links jump between them (`_openDigest` clicks the email rail, `applicantPortal.js:646`). Two homes for the core ritual dilutes the habit anchor. Pick the Portal as the canonical daily surface; make Email a fan-out view. Anchor: nav + deep-link consolidation.

43. **Notification-center info rows read as clutter, not reward** — [VALUE: low · EFFORT: S] — Informational notifs render as dismissible gray "Update" rows (`_renderNotifRow`, `applicantPortal.js:585`) mixed under the action queue. Separate "wins/updates" visually from "chores," so the good news isn't buried under to-dos (reinforces #20). Anchor: `_renderList` sectioning (`applicantPortal.js:606`).

44. **Give the user a lightweight goal-setting moment ("I want a job in ~8 weeks")** — [VALUE: low · EFFORT: M] — A stated goal turns abstract activity into progress-toward-a-finish-line, powering pacing copy and ring targets (#13). Optional, set in OOBE or Settings. Anchor: onboarding intake + momentum surface.

45. **Weekly "tune-up" prompt turns the survey into a recurring investment beat** — [VALUE: low · EFFORT: S] — The quick survey (`applicantDigest.js:609`) exists but is a hidden toolbar button. A gentle weekly "30-second tune-up? Your last answers already changed what I send" makes teaching-the-agent a recurring investment ritual (Hooked's loop-deepening stage). Anchor: schedule survey prompt; reuse existing modal.

46. **Emotional framing of rejections when they arrive** — [VALUE: low · EFFORT: S] — When a rejection outcome lands (once #4 exists), frame it forward, never as a dead-end: "Acme passed — I've already got 3 similar roles queued." Protects morale and immediately re-points at momentum. Anchor: outcome row copy.

47. **"Streak" of agent uptime / reliability as a trust signal** — [VALUE: low · EFFORT: S] — A quiet "running 24/7 for 12 days straight, 0 missed" reliability line reinforces the delegation trust that underpins the whole product. Anchor: Activity snapshot; data from run history.

48. **Deep-link every notification straight to the rewarding thing** — [VALUE: med · EFFORT: S] — Notifications carry a `deep_link` field (`notifications.py:51`) but the Portal center doesn't always route on it; a push should open *the exact match/win*, minimizing the trigger→reward distance (friction kills loops). Anchor: wire `deep_link` through toast/desktop-notify click handlers (`applicantPortal.js:123`).

---

## The through-line

The engine already earns the reward — it discovers, scores, pre-fills, and learns tirelessly. The gap is **surfacing that labor back to the user as felt progress**. Four moves would transform retention more than all the rest: (1) an **overnight recap** that pays off delegation every morning, (2) a **visible momentum scoreboard** promoted out of the admin Debug tab, (3) a **response/interview variable-reward loop** (the missing dopamine), and (4) **re-engagement + a consistent daily trigger** so the ritual survives a bad week. Do those and the daily digest stops being a chore queue and becomes the thing the user opens first with their coffee — because it reliably tells them they are moving forward, even when the market is silent.
