# Audit 07 — Outcomes, Analytics & the Learning Story

**Lens:** "Is it working, and is it getting smarter?" — the payoff beat (Journey Map Beat 6). This is
what turns a tool into an indispensable partner: a clear, motivating picture of results, and a
*tangible, trustworthy* learning narrative.

**The one-sentence finding.** The engine already computes a rich outcome/learning corpus — a
post-submission funnel (`submitted → rejected → ghosted → interview_invited → offer`,
`core/entities/outcome_event.py:23`), per-variant interview-conversion rate
(`core/entities/resume_variant.py:72`), per-source funnels with conversion-weighted ranking, a learned
converting-role signature by facet, follow-up scheduling, and taste/feature stats — **but almost none
of it reaches a non-admin user.** The payoff surfaces that exist are (a) an admin-only Debug → Insights
tab (`applicantDebug.js`, `_require_admin`), (b) a hidden "what tends to convert" pill buried in the
Memory → profile criteria editor (`entities.js:251`), and (c) the Mind panel (learned lessons/skills).
There is **no home dashboard, no outcome funnel, no weekly recap, no variant scoreboard, and no
response/interview/offer tracking anywhere in the front door.** The single highest-leverage move is to
build a first-class, non-admin **Results / Insights** surface and a **weekly recap**, promoting signal
out of the Debug tab.

Anchors are grounded in the files read: `applicantDebug.js` (Insights tab, admin-gated),
`applicant_admin_routes.py` (all learning/outcome proxies behind `_require_admin`), `entities.js`
(profile learning = only LaTeX/docx; signature card hidden), `applicantActivity.js` (run history, no
outcomes), `applicantPortal.js` (notifications, no metrics), `applicantCompare.js`, `applicantMind.js`,
and the engine services surveyed (`learning_service`, `learning_advanced`, `post_submission_service`,
`conversion.py`/`outcomes.py`/`admin.py` routers).

Format: `N. **Title** — [VALUE · EFFORT] — rationale + anchor.`

---

## Tier 1 — Make outcomes & the learning story reachable (the core gap)

1. **Build a first-class, non-admin "Results" surface** — [VALUE: high · EFFORT: M] — Today every
   outcome/learning read-model is locked behind `_require_admin` in
   `applicant_admin_routes.py:55` (`/history`, `/learning`, `/outcomes`, `/variants`) and only opens via
   the admin-only `tool-debug-btn` (`applicantDebug.js:801`). The *owner* of a self-hosted single-user
   deployment is the one who needs "is this working?" most, yet the payoff beat is gated as "operator
   grade." Add a rail entry + owner-scoped proxy (`/api/applicant/results/*`) that surfaces the funnel,
   per-source, per-role, and per-variant analytics without admin. This is the #1 reachability failure
   for Beat 6.

2. **Surface the post-submission funnel (submitted → rejected → ghosted → interview → offer)** —
   [VALUE: high · EFFORT: M] — The engine defines the full outcome catalogue
   (`core/entities/outcome_event.py:23-32`) and `PostSubmissionService` transitions apps through
   REJECTED/GHOSTED/AWAITING_RESPONSE, but the front door only shows raw per-application outcome *types*
   as a comma list in Debug → Activity (`applicantDebug.js:296`, `:344`). No campaign-wide funnel is
   computed or shown. Add an engine aggregate (`outcome_counts` per campaign) and render a funnel card:
   "50 submitted · 8 rejected (16%) · 12 ghosted (24%) · 7 interviews (14%) · 1 offer (2%)." This is the
   single most motivating "it's working" artifact and it is entirely absent.

3. **Response / interview / offer tracking is invisible in the UI** — [VALUE: high · EFFORT: M] — Grep
   confirms zero front-door references to interview/offer/response/heard-back tracking (only email
   "reply" UI and research follow-ups). The engine records `interview_invited`, `offer`, `rejected`,
   `ghosted` events and follow-up templates (`core/entities/follow_up.py:10`), but a user never sees "3
   employers responded, 1 interview." Add per-application outcome badges (Responded / Interview / Offer /
   Rejected / Ghosted) to the application history and Portal rows, driven by the existing
   `admin_application_outcomes` data (`applicant_admin_routes.py:188`) promoted to an owner surface.

4. **Ship a weekly / overnight recap** — [VALUE: high · EFFORT: M] — The digest is *only* new-role
   suggestions (`applicantDigest.js:8`); there is no periodic "here's how the week went." The engine has
   all the ingredients (run stats, outcome events, source funnels). Generate a weekly recap
   notification + Portal card: "This week: 12 submitted, 3 interviews, 1 offer. LinkedIn had your best
   interview rate. 5 applications went quiet — I scheduled check-ins." Reuse the existing digest
   delivery + notification fan-out. Recaps are the heartbeat that sustains delegated trust across quiet
   stretches (Beat 5→6).

5. **A per-variant resume A/B scoreboard** — [VALUE: high · EFFORT: M] — `ResumeVariant.conversion_rate`
   (share of submissions that reached an interview) and `submitted_posting_id` already exist
   (`core/entities/resume_variant.py:72`, `:63`), but the Variants tab only shows fit-score + approval +
   lineage (`applicantDebug.js:454-467`) — never "8 uses, 2 interviews (25%)." This is the concrete "is
   it getting smarter about *my* documents?" story. Add uses / interview-rate / offer-rate per variant
   and flag the winner ("Use Variant A more") — the highest-value learning-made-tangible artifact after
   the funnel.

6. **Promote the learned converting-role signature out of the Memory criteria editor** — [VALUE: high ·
   EFFORT: S] — The "What tends to convert for you" signature card
   (`entities.js:251`, facets role/seniority/skill/work_mode/comp/source/variant) is the literal FR-LEARN-5
   payoff, yet it is buried inside Memory → profile → criteria, hidden until non-empty, and easily
   missed. Give it a prominent home on the Results surface with the narrative framing the spec promises:
   "I've learned you convert better on remote Series-B backend roles, so I'm prioritizing them." The data
   is already fetched via `/signature`; this is mostly relocation + copy.

7. **Turn the Insights summary into a narrated, motivating story (not a stat dump)** — [VALUE: high ·
   EFFORT: S] — Debug → Insights renders bare counts ("120 matched · 30 approved · 5 submitted",
   `applicantDebug.js:394`) with no rates, no deltas, no interpretation. Add derived rates
   (approval rate, submission rate, per-source conversion %) and a one-line lead ("Your best source is X;
   your approval taste is getting sharper — approvals up week-over-week"). The engine's `build_summary`
   already ranks sources by conversion; expose the ratios it hides.

8. **Per-source conversion *rate* funnel, not opaque yield dicts** — [VALUE: high · EFFORT: S] — Sources
   render "matched · approved · submitted" (`applicantDebug.js:428`, `applicantDebug.js:661`) but the
   ratios that decide reweighting (approval-rate, submission-rate, conversion-rate) are computed in
   `LearningModel.source_weights` and never shown. Surface "LinkedIn: 40% approve → 12% submit" so the
   user understands *why* the engine favors a source — closing the outcome→learning→behavior loop
   visibly.

9. **Show the closed loop: outcome → learning → changed behavior** — [VALUE: high · EFFORT: M] — Nothing
   ties a decline/rejection to a concrete future action. The learned-criteria adjustments blob is dumped
   as raw JSON (`entities.js:215`, `JSON.stringify(learned, null, 2)`) — the opposite of trustworthy.
   Replace with plain sentences: "Because you passed on 6 on-site roles, I down-weighted on-site and
   raised your remote priority." This is the trust-repaid narrative of Beat 6; the criteria delta already
   exists on decline (`digest.py` decline returns `criteria_delta`).

10. **Follow-up engagement + impact is untracked in the UI** — [VALUE: high · EFFORT: M] — The engine
    schedules thank-you (2h), check-in (7d), and rejection follow-ups (`post_submission_service.py:22`,
    `follow_up.py:10`), but the user never sees that follow-ups happen, let alone whether they help. Add a
    "Follow-ups" section: scheduled/sent counts and, once data allows, the impact comparison the flywheel
    can compute ("apps with a check-in reached interview 13% vs 8% without"). Silent follow-ups are both
    a missed trust cue and a missed learning artifact.

---

## Tier 2 — Deepen the analytics & benchmarking

11. **Outcome rates as headline metrics (rejection / ghosting / interview / offer rate)** — [VALUE: high
    · EFFORT: S] — Once #2's aggregate exists, promote the four rates to big-number tiles on the Results
    home. These are the KPIs a job-seeker actually cares about — currently computed nowhere in the front
    door.

12. **Time-to-response / time-to-ghost distributions** — [VALUE: med · EFFORT: M] — `PostSubmissionService`
    knows submit timestamps and the 14-day ghosting SLA (`post_submission_service.py:21`,
    `DEFAULT_SLA_DAYS`). Surface "median time to hear back: 6 days; apps go quiet after ~14." Sets
    expectations and reduces "why is nothing happening?" anxiety in Beat 2/5.

13. **Funnel *over time* (week-over-week trend), not just a snapshot** — [VALUE: high · EFFORT: M] — Every
    metric today is a lifetime total. A partner shows momentum: submissions/week, approval-rate trend,
    interview-rate trend. Add a small sparkline/trend per KPI. Run history (`run_history.py`) and outcome
    timestamps make this derivable.

14. **Per-role / per-title conversion breakdown** — [VALUE: med · EFFORT: S] — `converting_roles` is shown
    as a flat pill list (`applicantDebug.js:403`). The signature already has per-facet weights; show "top
    converting titles" with counts and "titles that never convert (consider dropping)" — actionable role
    tuning, not just a word cloud.

15. **Work-mode / comp-band / location conversion cuts** — [VALUE: med · EFFORT: M] — The signature carries
    `work_mode`, `comp`, `location` facets (`entities.js:247` `_SIGNATURE_FACET_LABELS`) but only renders
    them as undifferentiated pills. Break out "remote 22% interview vs on-site 4%" and "roles ≥ your
    salary floor convert 2x." Directly informs the user's own strategy.

16. **Benchmarking: "your response rate vs typical"** — [VALUE: med · EFFORT: L] — No baseline exists, so
    a 12% interview rate reads as neither good nor bad. Provide a reference band (a shipped heuristic
    baseline is fine for a single-user self-host; cross-campaign comparison where multiple campaigns
    exist). Turns raw numbers into a verdict — the essence of "is it working?"

17. **Cross-campaign comparison view** — [VALUE: med · EFFORT: M] — Multi-campaign users have no way to
    compare campaign performance. The Compare surface only diffs applications/postings by ID
    (`applicantCompare.js:76`). Add a "compare campaigns" mode (submitted/interview/offer rates side by
    side) — reuses the existing compare table renderer.

18. **Feature/taste-bias transparency ("what you consistently approve/decline")** — [VALUE: med · EFFORT:
    M] — `feature_stats` (per-feature approve/decline counts) drives `taste_bias()` scoring but is exposed
    by no endpoint. Surface "you reliably approve: Python, remote, Series-B; you reliably decline: agency,
    on-site, <$100k." Makes the taste model legible and correctable — a trust surface.

19. **Attribute-reconciliation ledger ("what I learned about you vs what I asked to confirm")** — [VALUE:
    med · EFFORT: M] — `learning_advanced.reconcile_inputs` produces applied/pending/conflict/skipped
    results, surfaced nowhere. Show "auto-learned 4 details from your resume, held 1 for confirmation,
    skipped 2 sensitive." Reinforces the "learning is transparent and reversible" promise (Beat 6 HIG
    lens) and exposes profile conflicts (resume says NYC, profile says SF).

20. **Digest "why this role" rationale should persist into outcome review** — [VALUE: med · EFFORT: S] —
    `build_digest` computes `why_suggested` per row (`digest_service.py`), but it's only visible at
    approve-time in the digest. Carry it into application history so a user can retrospect "it suggested
    this because remote+Python — and it got an interview," reinforcing the model's credibility.

21. **Empty-day / "what I searched" note is under-surfaced** — [VALUE: low · EFFORT: S] — `FR-DIG-6`'s
    "no new matches; here's what I searched and why" note is generated (`_searched_summary`) but only in
    the digest. On a slow day the Results/Activity home should still show "searched 6 sources across 3
    titles, nothing cleared the bar" so silence never reads as breakage (Beat 2 anxiety).

---

## Tier 3 — Learning transparency (Mind / curation) & the flywheel

22. **Give Mind a proper home, not a button appended to the Brain modal** — [VALUE: med · EFFORT: S] —
    `applicantMind.js:289` literally appends "What the assistant remembers" to a native `#memory-modal h4`.
    The learned-lessons/playbooks/curation surface — a core Beat-6 trust artifact — deserves a rail entry
    or a section on the Results surface, discoverable without spelunking the Brain modal.

23. **Show learning-loop *activity* ("what I learned this week")** — [VALUE: med · EFFORT: M] —
    `CurationService.run_curation_tick` produces reviewed/staged/auto-applied counts
    (`CurationResult`) but the front door only shows the pending curation *queue* (`applicantMind.js:129`).
    Add "this week I saved 2 playbooks and learned 3 preferences" to the recap so learning is felt as
    ongoing, not just an approval chore.

24. **Playbook usage/effectiveness, not just a list** — [VALUE: low · EFFORT: M] — Saved playbooks render
    name/description/procedure (`applicantMind.js:96`) with no signal on whether a skill is *used* or
    *works*. Surface "used 12 times, last week" so the "procedural skills that improve on reuse" claim
    (FR-LEARN-8) is evidenced, not asserted.

25. **Surface the flywheel's parameter suggestions when wired** — [VALUE: med · EFFORT: M] —
    `learning_flywheel.py` architects `ParameterSuggestion` (source-weight/exploration-budget/scoring
    adjustments) and `Lesson` reflections, currently no-op stubs. When wired, show "I propose raising
    exploration to 0.3 because your proven sources are saturating" as a reviewable suggestion — the
    explicit outcome→learning→behavior loop, made a user-approved action (mirrors curation review).

26. **Explain the exploration budget in outcome terms** — [VALUE: low · EFFORT: S] — The budget is shown
    as a bare 0–1 number on Insights and Sources (`applicantDebug.js:411`, `:644`). Tie it to results:
    "20% of effort trying new sources — that found 2 of your interviews this month." Makes an abstract
    knob feel consequential.

27. **Confidence / sample-size labeling on all learned claims** — [VALUE: med · EFFORT: S] — The signature
    card already notes "from N converting applications" (`entities.js:262`); extend this everywhere. A
    "converts better on remote" claim from 2 samples must read as tentative, or an early wrong inference
    poisons trust. Gate strong statements behind a minimum sample and label the rest "early signal."

---

## Tier 4 — Reporting, export, and outcome capture

28. **Human-readable export / report (PDF or shareable summary)** — [VALUE: med · EFFORT: M] — The only
    export is a raw JSON audit log (`applicantDebug.js:253`, admin-only) and a JSON memory dump
    (`memory.js:1135`). Add a "download my results" report (funnel, top sources, top roles, variant
    scoreboard) — useful for the user's own tracking and career-coach conversations.

29. **One-tap outcome capture beyond "I submitted this"** — [VALUE: high · EFFORT: M] — The only
    manual outcome control is "I submitted this" (`applicantDebug.js:301`, admin Debug). But
    auto-detection can't see interviews/offers that arrive by phone or a portal the engine doesn't watch.
    Give the user quick "Mark: got a response / interview / offer / rejected" actions on each application
    (Portal or Results), feeding `record_outcome` (`outcomes.py`). Without this the funnel undercounts the
    outcomes that matter most, and the learning loop misses its strongest positive signal.

30. **Outcome capture is only reachable by admins** — [VALUE: high · EFFORT: S] — Because mark-submitted
    lives in the admin Debug tab, a non-admin owner literally cannot teach the system that they submitted
    or got an interview. `FR-LOG-4` demands a one-tap "mark submitted"; move it (and #29's outcomes) to an
    owner-reachable surface. Pure reachability fix over an existing endpoint.

31. **Interview → calendar closes the loop visibly** — [VALUE: med · EFFORT: M] — The engine already writes
    interview events to the workspace calendar via the internal callback (Feature Map §3.5). When an
    `interview_invited` outcome is captured, surface "added to your calendar" in the recap/Portal so the
    positive outcome is celebrated and connected, not silent.

32. **Portal should show a results glance, not only pending actions** — [VALUE: med · EFFORT: S] — The
    Portal is the post-login home base (`applicantPortal.js`) but carries only action rows + notifications
    — zero standing metrics. A compact header ("This week: 8 sent · 2 interviews · best source: LinkedIn")
    turns the home base into a place that answers "is it working?" at a glance every login (Beat 5→6).

33. **Activity run history should fold in outcomes** — [VALUE: med · EFFORT: S] — `_statSummary`
    (`applicantActivity.js:266`) reports discovered/shortlisted/pre-filling/completed but never
    outcomes. Add "· 1 interview came back" so the chronological story includes results, not just agent
    effort.

---

## Tier 5 — Polish, honesty, and the "small-data" experience

34. **Designed empty/early states for every analytics surface** — [VALUE: med · EFFORT: S] — The current
    empties are flat one-liners ("Not enough approved/submitted roles yet", `applicantDebug.js:404`). The
    first days ARE Beat 6 for a new user. Design an encouraging "you're 3 submissions from your first
    conversion insight — here's what will appear" state so the payoff surface motivates before it has data.

35. **Kill raw-JSON leakage in user-facing learning views** — [VALUE: med · EFFORT: S] — Learned criteria
    render as `JSON.stringify(learned, null, 2)` (`entities.js:215`) and submission-answer objects as
    `JSON.stringify` (`applicantDebug.js:173`). Raw JSON in a "getting smarter" surface reads as
    unfinished and untrustworthy. Render as sentences/rows.

36. **Distinguish "approval conversion" from "real conversion" in copy** — [VALUE: med · EFFORT: S] —
    `FR-LEARN-2` insists conversion = approval + *submission*, and the code honors it
    (`learning_advanced.is_conversion`). But the Insights "Conversion so far" card
    (`applicantDebug.js:391`) blurs matched/approved/submitted. Label clearly: "approval taste" vs
    "real conversions (submitted, and beyond)" so the user learns what the engine optimizes.

37. **Make the variant "fit score vs actual outcome" honesty check visible** — [VALUE: low · EFFORT: M] —
    Variants show a predicted `fit_score` (`applicantDebug.js:458`); the engine also knows actual interview
    rate. Show both so the user (and the model) can see whether the fit score is predictive — a
    self-auditing signal that builds trust in the scoring.

38. **Per-application outcome timeline drill-in** — [VALUE: low · EFFORT: M] — The app-detail drill-in lists
    outcomes as "type (source)" text (`applicantDebug.js:344`). Render a proper timeline (submitted →
    awaiting → follow-up sent → interview) with dates, so a single application's story is legible.

39. **Reconcile Compare with outcomes** — [VALUE: low · EFFORT: M] — The Compare table diffs entities by
    dimension (`applicantCompare.js:225`) but includes no outcome dimension. Add "interview? / days to
    response / variant used" rows so comparing two applications actually explains *why one worked*.

40. **Notification taxonomy should include positive outcomes** — [VALUE: med · EFFORT: S] — Portal folds
    informational notifications (digest ready / submitted / errors, `applicantPortal.js:68`) but there is
    no evidence of "you got an interview!" as a first-class celebratory notification. Positive outcomes are
    the emotional peak of the whole product; make them their own toast + Portal row + optional fan-out.

41. **"Roles/sources to drop" recommendations** — [VALUE: med · EFFORT: M] — All learning today is
    additive (favor what converts). The user also wants "stop wasting effort on X." The feature/decline
    stats and per-source funnels support "Indeed: 30 sent, 0 responses — consider disabling." A concrete,
    trust-building, effort-saving recommendation.

42. **Show learning is *per campaign* explicitly** — [VALUE: low · EFFORT: S] — `FR-LEARN-1` scopes
    learning per campaign; surfaces have a campaign picker but never state that insights are campaign-
    specific. A small "learned for this job search" label prevents the confusion of comparing incomparable
    campaigns.

43. **Offer/interview outcomes should feed a visible "wins" log** — [VALUE: low · EFFORT: S] — A dedicated
    "Wins" list (interviews + offers, with the role and the variant that got them) is the single most
    motivating artifact for a discouraged job-seeker. Cheap to build once outcomes are captured (#29) and
    reinforces the whole delegation.

44. **Digest decline reasons should roll up into an insight** — [VALUE: med · EFFORT: S] — Decline feedback
    feeds learning (`digest.py` decline → `criteria_delta`) but is never reflected back. Aggregate: "your
    top reasons for passing: not remote (11), salary too low (7) — I've tightened the filter." Closes the
    feedback→visible-change loop from the user's own words.

45. **Surface source-yield learning on the campaign settings sources toggle** — [VALUE: low · EFFORT: S] —
    Campaign settings claims "toggle sources with learned yield stats" (Feature Map §3.3) and Debug shows
    yield, but ensure the *owner-facing* sources toggle (not the admin Debug one) shows conversion, so the
    user disables low-yield sources from an informed position.

46. **Time-boxed goal / progress framing** — [VALUE: low · EFFORT: M] — Run modes include "until N viable"
    (`applicantDebug.js:474`). Tie outcomes to the goal: "target 20 submitted, 14 done (70%)" as a progress
    bar. Gives the numbers a destination.

47. **Explain what the agent will do *differently* next run** — [VALUE: med · EFFORT: S] — The Activity
    "now/next" snapshot (`applicantActivity.js:198`) states intent but not learned change. Add "next run
    I'll weight remote higher and try 1 new source" so the user sees learning translate into a plan,
    pre-outcome — anticipatory trust.

48. **Consolidate the three scattered learning surfaces** — [VALUE: med · EFFORT: M] — Learning signal is
    split across Debug→Insights (admin), Memory→profile signature card (buried), and Mind (Brain-modal
    button). A user cannot form a coherent "is it getting smarter?" picture from three disconnected places.
    The Results surface (#1) should be the single narrative home that links to Mind and criteria, not a
    fourth silo.

---

### Cross-cutting note

The recurring pattern: **the engine is analytically rich and the front door is analytically silent.**
Nearly every Tier-1/2 item is a *surfacing/reachability* fix over data the engine already computes and
often already exposes on an admin route — not new modeling. The biggest single win is #1+#2+#4 together:
a non-admin Results home with the outcome funnel and a weekly recap. That trio converts a capable but
opaque agent into one that visibly earns and repays trust every week (Journey Map Beat 6). Reachability,
per principle #2, is the definition of done here — and today the payoff beat fails it.
