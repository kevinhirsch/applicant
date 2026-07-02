# Applicant — Product Gaps & Competitive Parity Audit

**Lens:** What is MISSING as a *product* that would make Applicant genuinely invaluable to a job-seeker. Ranked best-ROI first (highest value / lowest effort at top). Grounded in the actual tree (engine `src/applicant/`, front-door `workspace/`) vs. what the spec/feature-map promise. Distinguishes **table-stakes** (competitors all have it) from **differentiators** (would make us category-leading).

**Legend:** VALUE high|med|low · EFFORT S(mall)|M(edium)|L(arge). "Reachability" = the CLAUDE.md principle #2 (done = operable in the white-labeled front-door), not just engine code.

---

## Tier 1 — Built-but-dark: reachability wins (highest ROI; the engine already did the work)

1. **Application Pipeline / Tracker board (applied → interview → offer → rejected)** — [VALUE: high · EFFORT: M] — The engine already has a full post-submission state machine (`POST_SUBMISSION → AWAITING_RESPONSE → REJECTED/GHOSTED/FOLLOWING_UP → ARCHIVED`) in `post_submission_service.py`, but there is **no engine router and no front-door surface** for it (`grep`: `PostSubmissionService` is wired only in `container.py`). Every competitor (Teal, Huntr, Simplify) leads with a kanban tracker; we have the data and hide it. Add a router + `applicant_pipeline_routes.py` proxy + a tracker JS surface. Single biggest "invaluable" unlock: the user sees their whole funnel, not just the pre-submit queue.

2. **Follow-up outreach drafting surface** — [VALUE: high · EFFORT: S] — `followup_service.py` already drafts timed check-in messages (`draft_followup`, `followup_is_due`, `DEFAULT_FOLLOWUP_DUE_DAYS`) and `post_submission_service.schedule_follow_up`/`send_scheduled_follow_ups` exist — but nothing surfaces them. Follow-ups are a proven conversion lever recruiters respond to. Wire due follow-ups into the Portal as review-and-send rows. Near-free given the service exists.

3. **Ghosting / rejection detection surfacing** — [VALUE: high · EFFORT: S] — `post_submission_service.check_ghosting` (SLA-day based), `scan_email_for_rejection`, `detect_outcome`, and `process_rejection_signal` already run, but the user never sees "3 apps have gone quiet 14+ days" or "auto-detected rejection from email." Surface these as Portal notifications + tracker badges. Turns silent state transitions into user-visible closure, which the conversion-learning loop (`FR-LEARN-2`) also needs.

4. **Interview scheduling → prep loop** — [VALUE: high · EFFORT: M] — The internal callback already auto-detects interview calendar events (`applicant_internal_routes.py` Lane A: `technical interview`/`phone screen`/`onsite` classification) and writes calendar events, but there is **no interview-prep product** on top: no company-specific prep brief, no likely-questions, no "here's your resume for this role + the JD + your notes." Detected interview → generate a prep packet (company research + role + your materials) surfaced in the Portal/Calendar. This is where Applicant could uniquely beat trackers: it already holds the JD, your tailored resume, and your attributes.

5. **Offer comparison / management** — [VALUE: med · EFFORT: M] — Zero offer-comparison capability exists (`grep`: no `Offer` class, no `offer_compare`). The lifecycle has no OFFER terminal state. Competitors (Teal) offer side-by-side comp/benefits/location comparison. Add an OFFER state + a Compare-surface variant (`applicantCompare.js` already does cross-entity diff tables — lift-and-shift it) scoped to offers. Closes the funnel at the top and is a natural payoff for Beat 6.

---

## Tier 2 — Table-stakes competitors have that we lack

6. **LinkedIn Easy Apply automation** — [VALUE: high · EFFORT: L] — Discovery aggregates LinkedIn postings (JobSpy), and ATS adapters cover Workday/Greenhouse/Lever/iCIMS/Generic (`ats.py`), but there is **no LinkedIn Easy Apply flow** — the single most-common one-click apply path and the headline feature of LazyApply/Simplify. Easy Apply is a distinct in-LinkedIn modal flow, not a standard ATS form. Highest-volume path a job-seeker expects; its absence is conspicuous vs. every consumer competitor.

7. **Company/employer intelligence brief per posting** — [VALUE: high · EFFORT: M] — Company research exists only as an internal safety/material-gen input (`presubmit_safety.py`, `material_service.py`), never surfaced to the user. Job-seekers want a one-glance "what is this company, is it reputable, size, funding, Glassdoor sentiment, red flags" before approving. The deep-research tool is already vendored (`research` router, internal callback) — reuse it to attach an employer brief to each digest row. Turns the digest from a link list into a decision surface.

8. **Resume ↔ JD keyword-coverage / match-score explainer (user-facing)** — [VALUE: high · EFFORT: M] — We have `ats_match_rate.py` (internal *fill-quality* guard) and `ats_parseability.py`, but no **user-facing** "your resume covers 12/18 JD keywords; missing: Kubernetes, Terraform" explainer — the core value prop of Jobscan/Teal's match score. The variant fit-scorer (`FR-RESUME-7`) computes fit locally already; expose the *why* (matched/missing keywords) in the redline/digest so the user understands and can steer adaptation.

9. **Salary / market-comp intelligence** — [VALUE: med · EFFORT: M] — Only a user-set salary *floor* exists (onboarding, criteria); there is **no market benchmark** (`grep`: no `salary_lookup`, no market/benchmark). The reference repo even shipped a `salary_lookup.py` (per spec §5.1) we never adopted. Show "this role's posted range vs. market for the title/location vs. your floor" on the digest row. Directly informs approve/decline and negotiation.

10. **Manual / external application logging (browser extension or bookmarklet)** — [VALUE: high · EFFORT: L] — `applicant_admin_routes.py` explicitly notes it closes "the conversion-learning loop the engine cannot do on its own for **manual or hand-off**" applications — meaning the user is expected to hand-log manual apps but has no capture tool. Spec even flags "browser-extension capture" as a later option (`FR-LOG-4`). A one-click capture (extension/bookmarklet) for jobs the user applies to outside Applicant makes the tracker complete and feeds learning. Teal/Simplify's extension is their acquisition wedge.

11. **Referral / network-connection surfacing** — [VALUE: high · EFFORT: L] — Only **1 file** mentions `referral` and zero real feature (`grep`). A referral is the single highest-conversion application path in real hiring. Even a lightweight "do you know anyone at {company}? here's a draft intro message" prompt at approval time (LinkedIn 2nd-degree is out of reach without their API, but a manual "I have a contact here" flag + draft reach-out is cheap) would materially lift outcomes.

12. **Cover-letter reachability audit** — [VALUE: med · EFFORT: S] — Cover-letter generation is implemented (`FR-RESUME-10`, `material_service.py`) and flows through the redline review, but verify the *cover-letter-specific* entry (on-demand generation, base-template upload) is operable in the front-door and not only reachable when the ATS offers a field. Job-seekers want to generate a cover letter proactively. Confirm/expose a "draft a cover letter for this role" action in Documents.

13. **Additional ATS adapters: Ashby, SmartRecruiters, SAP SuccessFactors, Taleo** — [VALUE: med · EFFORT: M] — `ats.py` has Workday/Greenhouse/Lever/iCIMS/Generic. `FR-PREFILL-2a` promises Ashby/SmartRecruiters explicitly and the GenericAts fallback covers them "generically," but named adapters add precision for the highest-volume platforms. Ashby (startups) and SuccessFactors/Taleo (enterprise) are large coverage holes. Also: iframe/shadow-DOM penetration (skyvern-parity Gap #2) blocks Workday/Taleo/SuccessFactors fields even for the generic path — that's a prerequisite.

14. **Bulk pre-fill queue / "apply to all approved"** — [VALUE: med · EFFORT: S] — Digest has bulk *approve* (`applicantPortal.js` "Approve all N", `resolve-bulk`), but there's no bulk-*pre-fill* momentum view: after approving 10 roles, the user should see a queue draining, not chase each. A simple "pre-fill queue" progress surface (leverages existing per-app durable workflows) makes 24/7 throughput felt. LazyApply's whole pitch is volume-felt.

15. **Duplicate/already-applied guard across campaigns** — [VALUE: med · EFFORT: S] — No cross-campaign "you already applied to this company/role" dedup (`grep`: dedup exists only for research/discovery caching, not applications). Applying twice to the same employer is embarrassing and hurts the user. Add an applied-companies index checked at digest time; surface "you applied here 20 days ago."

---

## Tier 3 — Workflow gaps in the discovery → prefill → review → submit → learn loop

16. **Real-time high-fit alerts (not just the daily digest)** — [VALUE: med · EFFORT: M] — Discovery batches into a once-daily digest (`FR-DIG-1`). Perfect-match roles (esp. fast-closing startup postings) should trigger an immediate "exceptional match found" notification via the existing ladder (`FR-NOTIF`), not wait for tomorrow's digest. The notification infra exists; add a fit-threshold real-time path.

17. **Application deadline / posting-freshness tracking** — [VALUE: med · EFFORT: S] — `deadline` appears in only 4 files with no user-facing deadline surface. Postings expire; a "this closes in 2 days" / "this posting is 45 days old (likely stale)" signal on digest rows prevents wasted effort on dead listings and prioritizes urgent ones.

18. **"Why declined" learning transparency loop** — [VALUE: med · EFFORT: S] — Decline-with-feedback is captured (`FR-DIG-5`, `FR-FB-1`) and feeds learning, but there's no visible "you keep declining X, so I stopped surfacing it" confirmation back to the user. Closing this loop visibly (in Memory/criteria) is what makes users trust the learning is real (Beat 6 payoff) — otherwise feedback feels like a void.

19. **Batch/side-by-side digest triage UX** — [VALUE: med · EFFORT: M] — The digest is a table (`FR-DIG-3`). Power job-seekers triage 20+ roles/day; a keyboard-driven swipe/triage mode (approve/decline/next) or a compare-two-roles view would make daily review fast rather than a chore (Beat 3 is the daily trust engine). Adjacent to but distinct from CSS polish.

20. **Screening-answer library / reuse** — [VALUE: med · EFFORT: S] — Screening answers are generated per-application (`FR-ANSWER-1`) through review, but there's no *library* of approved answers to common questions ("Why this company?", "Salary expectations", "Notice period") to reuse/adapt. Users answer the same essay questions repeatedly; a reusable answer bank (parallel to the resume variant library `FR-RESUME-6`) saves enormous time and keeps voice consistent.

21. **Portfolio / work-sample attachment handling** — [VALUE: low · EFFORT: M] — `portfolio` appears in 10 files but pre-fill explicitly *skips* file-upload controls beyond resume/cover (`FR-PREFILL-2a(e)`). Many applications request portfolio links, GitHub, writing samples. Store these as attributes and fill portfolio *URL* fields (not uploads) automatically.

22. **Multi-resume / multi-persona per campaign (career-pivot support)** — [VALUE: med · EFFORT: M] — Campaigns scope one base resume (`FR-RESUME-6`). Career-changers apply as, e.g., both "PM" and "Eng." The variant library forks from one base; supporting *distinct base personas* within a campaign (or making multi-campaign switching frictionless) serves pivoters — a large underserved segment.

23. **Application status change → notification / calendar sync** — [VALUE: med · EFFORT: S] — Once the tracker (#1) exists, status changes (interview scheduled, offer, rejection) should fan out through the notification ladder and write calendar events (the internal calendar callback already exists). Makes the tracker *active* not passive.

---

## Tier 4 — Analytics & insight the user would pay for

24. **Personal conversion analytics dashboard (user-facing, not admin-only)** — [VALUE: high · EFFORT: M] — Conversion funnel + top roles live in the **admin-only** Debug surface (`applicant_admin_routes.py` `learning_insights`, `applicantDebug.js`). A job-seeker's own "you applied to 40, heard back from 6, interviewed 2" analytics should be a first-class, non-admin surface — this is the payoff (Beat 6) that keeps users engaged and is exactly what Teal charges for. Promote insights out of Debug into a user Insights surface.

25. **Response-rate benchmarking by resume variant / role-type / source** — [VALUE: med · EFFORT: M] — Source-yield learning exists (`FR-DISC-5`), and per-variant fit-scores are stored, but the user never sees "your PM resume gets 2x callbacks vs. your generalist one" or "Greenhouse roles convert better for you than LinkedIn." Surfacing which variant/source/role-type actually converts is directly actionable intel that improves the user's own strategy.

26. **Time-to-response / velocity metrics** — [VALUE: low · EFFORT: S] — With the post-submission timestamps already tracked (`_submission_age`, ghosting SLA), compute and show median time-to-first-response, so users know when to follow up vs. move on. Cheap given the data.

27. **A/B resume experiment framing** — [VALUE: low · EFFORT: M] — Since the engine forks variants and tracks conversion, expose an explicit "we're testing variant A vs B for {role type}; A is winning" narrative. Turns the invisible learning into a compelling, trust-building story (competitive research #1 AWM/#2 ACE flywheel — the "smarter every application" pitch is our differentiator but currently invisible).

---

## Tier 5 — Differentiators that would make us category-leading

28. **Autonomous "smarter per ATS" workflow-induction, made visible** — [VALUE: high · EFFORT: M] — `competitive-research.md` #1 (AWM, Apache-2.0) is the single highest-leverage idea: induce reusable per-ATS form-fill workflows from successful pre-fills and inject as planner priors. `adapters/routine/` exists — verify it's wired and, critically, *surface* "I've now applied to 5 Workday portals; I'm faster each time." No competitor self-hosts a learning form-filler; this is our moat.

29. **Self-hosted privacy as the product wedge** — [VALUE: high · EFFORT: S] — Applicant runs on the user's own Proxmox with residential egress (`FR-STEALTH-4`); every SaaS competitor uploads your resume/PII to their cloud and applies from datacenter IPs (which employers flag). This is a genuine differentiator that is nowhere marketed in-product. A landing/onboarding message ("your data never leaves your box; applications come from your own connection") converts privacy-conscious/senior candidates. Near-free positioning win.

30. **Interview prep generation (mock questions + your-materials brief)** — [VALUE: high · EFFORT: M] — Building on #4: given a detected interview, generate likely questions from the JD, pull the user's tailored resume + attributes, and produce a prep sheet + STAR-story suggestions from their real history (truthfulness guard applies). No tracker competitor does prep well; we uniquely hold the JD + tailored materials + attribute cloud.

31. **Salary negotiation assistant** — [VALUE: med · EFFORT: M] — At the offer stage (needs #5), generate a data-backed negotiation script from market comp (#9) + the user's floor + competing offers. High-value moment competitors ignore; leverages material-gen infra.

32. **Recruiter / hiring-manager outreach drafting** — [VALUE: med · EFFORT: M] — Only 2 files mention `recruiter`. Draft personalized cold outreach to the hiring manager/recruiter for a role (voice-matched, from the user's real background) as an optional pre- or post-apply action. Combines with #11 referrals; recruiter outreach materially lifts response rates.

33. **Weekly strategy summary / coach** — [VALUE: med · EFFORT: S] — A weekly "here's your week: 15 applied, 3 responses, your Terraform gap is costing you DevOps roles, consider widening salary floor" narrative (LLM over already-tracked data). Turns Applicant from a tool into a coach — sticky, high-perceived-value, cheap given the data exists.

34. **Networking-event / warm-intro tracker** — [VALUE: low · EFFORT: M] — Extend the tracker to log networking touches (coffee chats, referrals requested) alongside applications, so the user sees their whole search effort. Differentiates from pure auto-apply tools that ignore the human side of job search.

35. **Multi-user / household or coaching mode** — [VALUE: low · EFFORT: L] — The front-door is already multi-user (`AuthManager`, owner-scoping). A career coach or a couple job-searching together could each run campaigns under one instance. Low near-term value for the self-hoster but a real expansion path the architecture already supports.

---

## Tier 6 — Robustness gaps that silently cost applications (parity with Skyvern)

36. **Iframe / shadow-DOM field penetration** — [VALUE: high · EFFORT: M] — `skyvern-parity-gaps.md` Gap #2 (HIGH): the generic driver detects only top-level DOM fields; Workday/Taleo/SuccessFactors render fields in iframes/shadow roots, so pre-fill silently fills almost nothing there. This is a *product* failure (the user thinks it applied; it didn't). Prerequisite for real Workday/enterprise coverage. Add recursive frame+shadow traversal to `PlaywrightPageSource`.

37. **Dynamic-element waiting + auto-retry on SPA transitions** — [VALUE: med · EFFORT: S] — skyvern-parity Gap #3 (LOW effort, HIGH impact): fixed 10s `networkidle` wait times out on SPA-heavy ATS, aborting applications. Adaptive waits + staleness retry. Cheap, prevents silent drop-offs.

38. **Wrong-page / redirect-loop recovery** — [VALUE: med · EFFORT: S] — skyvern-parity Gap #6: `advance()` returns None silently on unexpected pages (SSO loops, interstitials). Add URL-verification + replan. Prevents applications dying in the dark mid-flow.

39. **CAPTCHA/challenge classification (for better handoff, not solving)** — [VALUE: med · EFFORT: M] — skyvern-parity Gap #5: rule-based challenge detection has false negatives. Better vision+DOM classification means cleaner, faster human-handoff (we correctly never auto-solve, per `FR-PREFILL-6`). Improves the takeover experience.

40. **Post-submission confirmation reliability** — [VALUE: med · EFFORT: S] — `FR-LOG-4` submission auto-detection relies on confirmation-page heuristics. If it misfires, the funnel/learning is wrong. Pair the "mark submitted" fallback with an explicit confirm-screenshot the user can verify in the tracker — trust that the app actually went through.

---

## Tier 7 — Integrations & ecosystem

41. **Email integration for two-way tracking (IMAP/inbox scan)** — [VALUE: high · EFFORT: M] — `scan_email_for_rejection` exists but expects email text handed in — there's no live IMAP/Gmail connection to auto-ingest recruiter replies, interview invites, and rejections. Wiring an inbox connector auto-updates the tracker and follow-up loop with zero user effort — the magic moment that makes the pipeline feel alive.

42. **Calendar interview auto-scheduling (not just detection)** — [VALUE: med · EFFORT: M] — Internal callback *detects* interview events; going further to parse invite emails and *propose* calendar holds + prep reminders closes the loop. Builds on #4/#41.

43. **MCP server exposure of the engine** — [VALUE: low · EFFORT: S] — `mcp.py` router exists (competitive-research #8 fastapi_mcp). Verify/finish exposing Applicant as an MCP server so power users can drive it from Claude/other agents ("what's my pipeline this week?"). Cheap differentiator for the technical self-hoster audience.

44. **Job-board coverage beyond JobSpy's default set** — [VALUE: med · EFFORT: M] — Discovery is JobSpy (LinkedIn/Indeed/Glassdoor/Google/ZipRecruiter) + SearXNG. Missing: Ashby-hosted job pages, YC/WorkAtAStartup, Wellfound/AngelList, company career-page crawling. `FR-DISC-2` makes sources pluggable — add niche/startup sources (highest-yield for many seekers) as adapters.

45. **Export (CSV/PDF) of applications + tracker** — [VALUE: low · EFFORT: S] — No export of the application history/tracker. Job-seekers need this for unemployment/benefits reporting and their own records. Cheap, expected, and a trust signal (your data is portable).

---

## Tier 8 — Onboarding & activation gaps

46. **Sample/seeded first-run experience ("first light")** — [VALUE: high · EFFORT: M] — JOURNEY_MAP Beat 2 ("First light") is where a silent post-OOBE product feels broken — the user set everything up but sees nothing for hours until the first discovery run. A seeded demo campaign or an immediate first discovery pass on wizard completion gives an instant "it's working" payoff and prevents early abandonment.

47. **Import existing applications / LinkedIn profile at onboarding** — [VALUE: med · EFFORT: M] — Onboarding parses the base resume (`FR-ONBOARD-3`) but can't import a LinkedIn profile export or a list of jobs already applied to. Bootstrapping the attribute cloud from LinkedIn and pre-populating the tracker with in-flight applications reduces the upfront-cost funnel drop (Beat 1 is make-or-break).

48. **Resume health / ATS-parseability score at upload** — [VALUE: med · EFFORT: S] — `ats_parseability.py` exists in core but isn't surfaced. At base-resume upload, show "your resume is 85% ATS-parseable; these 2 sections may not parse" — an immediate value hit during onboarding that builds trust before any application runs. Cheap given the rule exists.

---

## Summary of biggest structural findings

- **The single highest-ROI theme is Tier 1: the engine already built a complete post-submission lifecycle (tracker states, follow-up drafting, ghosting/rejection detection, interview-event detection) that has NO front-door surface** — violating principle #2. Wiring these up delivers the table-stakes "application tracker + follow-ups + interview loop" that every competitor leads with, at low effort because the logic exists.
- **We are strong where competitors are thin (autonomous learning form-fill, self-hosted privacy, residential egress, tailored-material-per-role) but market/surface NONE of it** — the differentiators (#28–#30) are invisible to the user.
- **We are missing where consumers expect strength: LinkedIn Easy Apply, employer intel, market-salary intel, user-facing match scores and analytics, and iframe/shadow-DOM robustness** that silently breaks Workday/enterprise pre-fill.
