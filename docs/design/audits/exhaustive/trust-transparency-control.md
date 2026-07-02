# Trust, Transparency & Agent Control — Applicant front-door audit

**Lens:** This is an autonomous agent touching a person's livelihood and identity. Trust is the whole product. The audit below is ranked best-ROI-first. Anchors are to the white-labeled front-door (`workspace/`) surfaces since reachability there is the definition of done (principle #2). Findings focus on transparency, consent, control, explainability, safety-surfacing, and trust signals — not visual/CSS/HIG styling.

Legend: `[VALUE: high|med|low · EFFORT: S|M|L]`

---

## Tier 1 — Control reachability & irreversibility gravity (the load-bearing gaps)

1. **No global pause / kill-switch reachable outside the admin-only Debug modal** — [VALUE: high · EFFORT: M] — The only Pause/Resume control lives in `applicantDebug.js` `_renderRun()` (Run controls tab, gated admin-only + campaign-scoped). A 24/7 agent acting under the user's name MUST have a one-tap "stop everything now" that a non-admin owner can hit from the home base. The always-on status strip (`applicantActivity.js` `_renderStrip`) shows a live/paused dot but is click-through-to-modal only — it is the natural home for a pause affordance and has none. Add a global pause to the status strip and/or Portal header that pauses all campaigns.

2. **Status strip is read-only — the most-visible trust surface offers zero control** — [VALUE: high · EFFORT: S] — `applicantActivity.js:117` renders "Applicant is: …" with a live/paused dot, but clicking only opens the Activity history modal. The one always-present pulse of the agent should let the user pause-in-place, or at minimum expose a pause button on hover. Right now the user watches the agent work with no brake within reach.

3. **Pause is per-campaign, not system-wide** — [VALUE: high · EFFORT: M] — `applicantDebug.js:621` pauses/resumes a single `_campaignId`. A user with 2+ job searches who panics ("stop applying under my name") cannot stop everything in one action. Provide an "Pause all searches" that fans out across campaigns.

4. **Final-submit authorization confirm is a text `styledConfirm`, not a weighted decision surface** — [VALUE: high · EFFORT: M] — The single irreversible action in the product (`applicantRemote.js:480` `_onAuthorizeFinish`, `applicantPortal.js:882`) is gated only by a `_confirm(..., {danger:true})` dialog. For an action that sends a real application to a real employer under the user's name, the confirm should restate the exact role/company, show *what will be submitted* (the immutable snapshot preview — see #10), and require a deliberate gesture. The confirm copy is good ("cannot be undone") but the affordance weight is the same as declining a digest row.

5. **No undo / recall window after authorize-to-submit** — [VALUE: high · EFFORT: L] — Once `authorizeEngineFinish` fires (`applicantRemote.js:425`), there is no "cancel — I changed my mind" grace period surfaced anywhere. Even a 5–10s "Submitting… [Cancel]" hold on the button before the engine clicks would convert an irreversible action into a recoverable one. Today the toast immediately says "the assistant submitted the application."

6. **Egress/residential-connection transparency is invisible until the final-submit row** — [VALUE: high · EFFORT: M] — `FR-STEALTH-4/5` route all automation through the user's home IP and present a coherent browser identity. The only place this is surfaced is the best-effort `egress_caveat` on the remote modal (`applicantRemote.js:315`) and final-approval rows (`applicantPortal.js:915`) — and it renders *nothing* if the engine returns an empty caveat. A user creating accounts and applying under their name and home IP deserves an always-available "How your privacy & identity are handled" explainer (which connection is used, that no CAPTCHA is solved, that a coherent-but-honest fingerprint is presented). Surface it in Settings and the OOBE, not only at the last gate.

7. **The "what Applicant never does" trust contract lives only in OOBE welcome + Portal empty state** — [VALUE: high · EFFORT: S] — `NEVER_DOES` (`applicantOnboarding.js:100`) is the product's core safety promise (never submits without approval, never solves CAPTCHA, never guesses EEO). It appears on the welcome step and the Portal *empty* state (`_neverDoesHTML`), i.e. it vanishes the moment the user has pending items — exactly when they're anxious. Persist a "What it will never do" link in the Portal header, the remote/takeover surface, and Settings.

---

## Tier 2 — Explainability & per-decision transparency

8. **No plan-preview before the agent acts (plan-as-data is proposal-only)** — [VALUE: high · EFFORT: L] — `docs/design/plan-as-data.md` describes a typed, inspectable plan the model emits before executing, but it is explicitly "proposal (forward-looking; not yet implemented)" and nothing in the front-door shows the user the agent's plan for an application before it pre-fills. The trust arc (JOURNEY_MAP Beat 4) hinges on "it's about to act — do I let it?" but the user cannot see *what it intends to fill* until it has already filled it. Surface the plan (or at minimum the ordered field-fill intentions) in the remote view before execution.

9. **Per-decision "why I applied" explainability is thin — only a digest-time score** — [VALUE: high · EFFORT: M] — The prompt's ideal is "I applied because you match 8/10 criteria." Today the digest row shows `{score}% match` + a free-text `why_suggested` (`applicantDigest.js:263,270`), but once approved that rationale is not carried forward to the application record, the Portal final-approval row, or the Debug activity detail. At the final-submit gate the user re-decides with no per-criterion breakdown. Attach the criteria-match rationale to the application and echo it at every downstream decision.

10. **Immutable submission snapshot is admin-Debug-only and post-hoc** — [VALUE: high · EFFORT: M] — `_renderSnapshot` (`applicantDebug.js:165`) shows the exact answers, document versions, posting, and timestamp — but only in the admin Debug → Activity drill-in, and only *after* submission ("captured when an application is submitted"). The most valuable moment for this is *before* authorize-to-submit: the user should preview the exact answers and documents that are about to be sent. Surface a "review exactly what will be submitted" snapshot on the final-approval affordance.

11. **Fabrication guard / resume honesty is asserted but never shown in the redline** — [VALUE: high · EFFORT: M] — `NFR-TRUTH-1` and the fabrication guard are core promises, and `docs/spec/master-spec.md:256` even describes a graded "capped-confidence review flag" for claims not derivable from true attributes. The redline review (`documentLibrary.js:2251` `_renderApplicantReview`) shows additions/subtractions and "Nothing is submitted until you approve" — but nothing tells the user "every change here reframes your *real* experience; no new skills/titles/dates were invented," and no per-change confidence/flag is surfaced. A user reading diffs to a document representing *them* needs an explicit honesty attestation and any low-confidence flags highlighted.

12. **Redline injects engine `rendered_html` via `innerHTML` with no truthfulness annotation layer** — [VALUE: med · EFFORT: M] — `documentLibrary.js:2281` sets `redline.innerHTML = renderedHtml`. Beyond the (same-origin-trusted) XSS surface, this means the *only* channel for surfacing which additions are flagged-for-review is baked into engine HTML — the front-door can't independently badge a claim as "verify this." Give the redline a structured annotation slot so flagged claims render distinctly regardless of engine HTML.

13. **"Why the assistant suggested this" truncates to 2 lines with no expand** — [VALUE: med · EFFORT: S] — `applicantDigest.js:278` clamps the rationale to `-webkit-line-clamp:2`. For the single most important explainability field in the daily loop, add a "more" expander so the full reasoning is readable, not cut mid-sentence.

14. **Confidence / uncertainty is never communicated on matches or fills** — [VALUE: med · EFFORT: M] — Scores appear as a bare `%match`, but the agent's *own* uncertainty (borderline match, ambiguous field mapping escalated to the LLM per `FR-PREFILL-3`, a guessed-vs-confirmed attribute) is nowhere surfaced. When the agent is unsure it should say so ("I'm 60% sure this fits — worth a look"), so the user calibrates trust rather than treating every score as ground truth.

15. **Agent-question rows give no context for *why* it's asking** — [VALUE: med · EFFORT: S] — `applicantPortal.js:398` `_renderAnswer` renders a bare textarea for `agent_question`/`error` kinds. The user sees "The assistant has a question for you" with no application/role context or reason. Carry the role·company and the reason into the row so answering isn't blind.

---

## Tier 3 — "What did it do overnight" & audit-trail visibility

16. **Overnight/absence recap is missing — the anxious "First light / Sustain" beats are unserved** — [VALUE: high · EFFORT: M] — JOURNEY_MAP Beat 2/5 is "is it actually doing anything / can I glance and relax." The Activity modal (`applicantActivity.js`) shows a reverse-chron run list and a now/next snapshot, but there is no "while you were away, here's what happened" digest (applied N, blocked on M, awaiting you on K). A returning user has to piece it together from run rows. Add a since-last-visit summary at the top of Portal/Activity.

17. **Audit-log download is admin-only and buried in Debug** — [VALUE: med · EFFORT: S] — The full ordered action trail export (`applicantDebug.js:253` `_downloadAuditLog`) is a genuine trust asset ("every action the engine took, in order") but only admins reach it and only via the Debug modal's campaign picker. The account owner — even non-admin — should be able to see/export the trail for their own searches. This is a per-user identity/livelihood record.

18. **Screenshots exist but the run-history rows don't link to what the agent saw** — [VALUE: med · EFFORT: M] — Per-application screenshots live in Debug detail (`applicantDebug.js:337`) and the Gallery, but the Activity run rows (`applicantActivity.js:290`) are text-only. "Show me what it saw when it applied" is a strong trust primitive — link run rows to their screenshots.

19. **Activity/run history is not per-application filterable from the trust surfaces** — [VALUE: med · EFFORT: M] — The owner's Activity modal lists runs but can't answer "what exactly happened for the Acme application?" without dropping into admin Debug. Give the non-admin Activity view a per-application drill-in (state timeline + screenshots + outcome).

20. **Logs tab is "redacted" but the user is never told what/why is redacted** — [VALUE: low · EFFORT: S] — `applicantDebug.js:440` dumps redacted log entries with no note explaining redaction protects their secrets. A one-line "secrets and personal values are redacted from these logs" turns an opaque dump into a trust signal.

21. **No "explain this run" affordance beside the Debug "Ask the assistant" button** — [VALUE: low · EFFORT: S] — `applicantDebug.js:119` opens chat beside Debug, but the user must compose the question. A "Explain what happened here" one-click that seeds the chat with the run/application context would make the audit trail conversational.

---

## Tier 4 — Credential vault trust signals

22. **Vault claims "never shown again / never read back" but shows no proof-of-encryption state** — [VALUE: high · EFFORT: S] — `applicantVault.js:54` copy is good ("encrypted and never shown again"), and the list shows a 🔒 per tenant, but there is no trust signal that a secret was actually sealed (no "sealed ✓ · encrypted at rest" affirmation on save, no indication of *where/how*). The account-status line only flips "not set → saved ✓" (`applicantVault.js:246`). Add an explicit "encrypted with libsodium, stored sealed, this app can never display it" reassurance at save time.

23. **Password fields are `type=password` but reuse `.settings-select` class — no vault-grade focus/opacity cue** — [VALUE: low · EFFORT: S] — Per FEATURE_MAP §5, a credential sheet must read as opaque/sealed. The inputs (`applicantVault.js:75,88,107`) are functionally fine but carry no distinct "this is a secret" visual grammar. Minor, but the vault is the highest-sensitivity input.

24. **Credential capture during takeover confirms via plain `window.confirm` fallback** — [VALUE: med · EFFORT: S] — `offerApplicantCredentialCapture` (`applicantVault.js:326`) and `_offerSaveSignIn` (`applicantRemote.js:389`) fall back to `window.confirm` when `styledConfirm` is unavailable. For "save the password you just typed," a raw browser confirm undercuts the sealed-vault trust framing. Ensure the styled, reassuring path is always used.

25. **No way to see *which* saved sign-in the agent will use for a given application** — [VALUE: med · EFFORT: M] — The vault lists tenants with a lock, and the account section explains Google-vs-default precedence in prose (`applicantVault.js:61-66`), but at application time the user can't confirm "it will sign in as you@gmail via Google here." Surface the credential selection on the live-session / pre-fill surface so account use is transparent, not implicit.

26. **Auto-capture can't read the password from the sandbox — but the copy doesn't fully set that expectation** — [VALUE: low · EFFORT: S] — `applicantRemote.js:384` correctly notes the password can't be read out of the sandboxed session (so it re-prompts). Good honesty; make it explicit in the offer ("we can't see what you typed, so please re-enter it to save") so the re-typing doesn't read as a bug.

---

## Tier 5 — Takeover / live-session gravity & consent

27. **"I created the account — continue" and "I cleared the verification — continue" trust the human with no verification** — [VALUE: med · EFFORT: M] — `applicantRemote.js:158` resume buttons let the user assert a human-only step is done. If clicked prematurely the agent proceeds into an un-created-account state. A soft "are you sure the account exists / verification cleared?" or an engine-side re-check would prevent a confusing failure loop. Low-stakes but affects trust in the handoff.

28. **The two terminal final-submit choices are both `.cal-btn` variants — destructive weight not differentiated** — [VALUE: med · EFFORT: S] — `applicantRemote.js:128-131`: "I'll submit it myself" (`.cal-btn`) vs "Authorize the assistant to finish" (`.cal-btn cal-btn-primary`). Per FEATURE_MAP §5 and JOURNEY_MAP Beat 4, the irreversible authorize should read as *the* deliberate/destructive-weighted choice, unmistakably distinct — not merely "primary." (Flagged as trust-gravity, not pure styling: the semantic weight of the irreversible option is a consent signal.)

29. **Desktop-assist toggle ships dormant/disabled but its consent copy pre-commits trust** — [VALUE: low · EFFORT: S] — `applicantRemote.js:104` desktop-assist is honestly grayed ("coming in a future update"). Good. When it activates, ensure the "it asks before each step / never submits" promise is enforced *and* visibly logged per action, not just asserted in the tooltip.

30. **Live-session iframe has `allow-same-origin allow-scripts` — no user-facing note on what the embedded session can do** — [VALUE: low · EFFORT: S] — `applicantRemote.js:74` sandbox flags are a reasonable engineering choice, but the user watching a live browser under their identity gets no framing of "this is your isolated session on your machine." A one-line "This runs in an isolated browser on your own server" reinforces the residential-legitimacy story.

31. **Takeover ("Take control") gives no explicit hand-back / "return control to the assistant" affordance** — [VALUE: med · EFFORT: S] — `applicantRemote.js:344` `_onTakeover` grants control; the picker labels "(you are in control)" but there's no clear "give control back" button. The user can be unsure whether the agent is now waiting on them indefinitely. Add an explicit release-control action.

---

## Tier 6 — Consent for learning, memory & attribute changes

32. **Integral-change confirm is good — but the passive-inference source isn't always shown** — [VALUE: med · EFFORT: S] — `applicantPortal.js:473` `_renderConfirmChange` shows from→to and a reason, honoring FR-FB-3 (a core detail inferred from a survey/résumé is held until confirmed). Ensure `p.reason` always states the *source* ("inferred from your uploaded résumé" / "from your survey answer") so the user knows why the agent thinks it, not just what it proposes.

33. **Mind / learning curation is reachable only via a button inside Memory** — [VALUE: med · EFFORT: S] — Per FEATURE_MAP, the user approves/denies what the agent *remembers* via `applicantMind.js`, but its only opener is a button inside the Memory surface (`window.applicantMindModule.openApplicantMind()`). "The user is always the authority over the agent's memory" (JOURNEY_MAP Beat 6) deserves a first-class, discoverable entry — a user who never opens Memory never learns the agent is curating what it knows about them.

34. **Attributes/criteria edits apply silently — no "this changes what it applies to" preview** — [VALUE: med · EFFORT: M] — `memory.js` lets the user edit the attribute cloud + criteria, which biases discovery and fills. There's no surfaced consequence ("changing your salary floor will re-score N pending roles"). Editing identity that the agent acts on should preview the blast radius.

35. **Learning/conversion signals are shown but not consented — the agent adapts behavior from them invisibly** — [VALUE: low · EFFORT: M] — Insights (`applicantDebug.js:382`) shows conversion funnels and "roles that convert" that *bias future discovery*, but there's no control to say "stop favoring X" from that surface — it's read-only. Let the user steer the learned bias where it's shown, so learning is a dialogue not a black box.

---

## Tier 7 — Honesty of state, errors & notifications

36. **Toasts are the primary success/failure channel for irreversible actions — they're transient** — [VALUE: med · EFFORT: S] — "Authorized — the assistant submitted the application" (`applicantRemote.js:492`, `applicantPortal.js:901`) is a *toast*. Confirmation of an irreversible, identity-bearing action should persist (a durable Portal row / activity entry the user can revisit), not vanish in seconds. A user who blinks past the toast has no in-app record it happened until they dig into Debug.

37. **Error pending-items are labeled "Hit a snag" and routed to a generic answer box** — [VALUE: med · EFFORT: S] — `applicantPortal.js:200` maps `error` kind to affordance `answer` with label "Hit a snag that needs a look." For an autonomous agent failing mid-application under the user's name, "snag" under-communicates and the free-text box offers no structured recovery. Surface what failed, on which application, and offer retry/skip/open-session rather than a blank textarea.

38. **First-load notification backlog is silently seeded (no toast) — genuinely-missed items can be lost** — [VALUE: low · EFFORT: S] — `applicantPortal.js:103` seeds the seen-marker to newest on first load without toasting, to avoid spam. Reasonable, but a user who was away for a day gets no signal that things happened while gone — reinforces #16 (need an explicit "while you were away" recap rather than relying on toasts).

39. **Gated vs offline is disambiguated well — extend the same honesty to the strip** — [VALUE: low · EFFORT: S] — The Portal/Debug/Activity correctly separate "engine offline" from "setup incomplete/gated" (`_renderGated` vs `_renderOffline`). The status strip (`applicantActivity.js:109`) just *hides* when `has_activity===false` — so a user mid-setup sees nothing rather than "finish setup to begin." Make the strip say why it's quiet.

40. **"Snooze until tomorrow" on final-approval and account-creation rows can silently defer time-sensitive applications** — [VALUE: med · EFFORT: S] — `applicantPortal.js:379` offers Snooze on *every* resolvable row, including `final_approval` and `account_creation`. Snoozing a role with a closing application window (or a live session that will expire) has real cost the user isn't warned about. Suppress or warn on snooze for time-critical kinds.

---

## Tier 8 — Onboarding trust-granting & framing

41. **OOBE welcome lists "never does" but not "what it *will* do autonomously under your name"** — [VALUE: high · EFFORT: S] — `applicantOnboarding.js:293` welcome covers what you'll set up + what it never does, but soft-pedals the magnitude: it will create accounts, fill real applications, and adapt your résumé 24/7 under your identity. Trust is granted here (JOURNEY_MAP Beat 1); an honest, non-alarming "here's the scope of what you're delegating" builds *more* durable trust than omitting it. Pair every "never" with the corresponding "will."

42. **EEO / sensitive-field policy is a one-liner in the never-does list — not explained at intake** — [VALUE: med · EFFORT: S] — `NEVER_DOES` says "Never guesses your voluntary self-identification (EEO) answers," and the intake collects EEO answers (FEATURE_MAP §3.3). But the profile step doesn't explain FR-ATTR-6 ("defaults to decline-to-self-identify; only filled from your explicit answers"). At the moment the user types demographic data into the machine, that policy is exactly what earns trust. Surface it inline on the EEO fields.

43. **Résumé LaTeX-conversion accept/reject gate: fidelity note is honest but binary** — [VALUE: low · EFFORT: S] — `applicantOnboarding.js:1486` shows "Looks like a faithful match" vs "Some formatting may differ." For the document that represents the user, a preview/diff of what changed (not just a verdict) would let the user consent with eyes open.

44. **No consent moment for residential-egress before automation starts** — [VALUE: med · EFFORT: M] — Given `FR-STEALTH-4` routes automation through the home connection and presents a coherent identity, the OOBE should include an explicit acknowledgment ("automation runs from this machine's connection, as you") before the first run — this is a meaningful privacy/identity consent that is currently implicit.

---

## Tier 9 — Miscellaneous trust signals & polish

45. **Portal is the home base + inbox but the "never does" trust footer only shows when empty** — [VALUE: med · EFFORT: S] — (Reinforces #7.) Move the trust contract to the Portal *header* or a persistent info affordance so it's present when the queue is full — the anxious moment — not only when caught up.

46. **No single "trust center / how this works" surface** — [VALUE: med · EFFORT: M] — Trust signals are scattered: egress caveat (remote/final rows), never-does (OOBE/empty Portal), snapshot (admin Debug), vault sealing (vault modal), fabrication guard (asserted nowhere visible). A consolidated, always-reachable "How Applicant protects you" page (privacy, safety gates, what it can/can't do, where your data goes) would anchor the whole trust arc.

47. **Authorize-finish success can't be verified by the user against the actual employer** — [VALUE: low · EFFORT: M] — After authorize, the user has only the toast + (admin) snapshot. A "view the submitted application / confirmation" link (posting URL + captured confirmation screenshot) would let them verify the agent actually did what it claimed under their name.

48. **Compare surface requires the user to type entity IDs by hand** — [VALUE: low · EFFORT: M] — `applicantCompare.js` (per FEATURE_MAP §3.2) needs raw application/posting IDs. For a transparency tool ("what differs between these two applications the agent made?") the friction of hand-typing opaque IDs makes it effectively unreachable. Seed it from the Activity/Portal context.

49. **"Run now" success toast reports discovery count but not what it will *do* with results** — [VALUE: low · EFFORT: S] — `applicantDebug.js:606` toasts "Found N posting(s)." The user doesn't learn whether those will auto-advance to pre-fill or wait for digest approval. State the next step so a manual "Run now" doesn't feel like it might have kicked off applications.

50. **Tool-registry toggles (`applicantDebug.js:713`) let admins disable agent capabilities with no audit of what changed** — [VALUE: low · EFFORT: S] — Turning agent tools on/off is a real capability change; there's no record in the audit trail that "tool X was disabled at time T." For a system whose trust rests on the audit trail, config changes should be logged there too.

51. **Snapshot/"submission record" is the strongest honesty artifact but is unreachable to the very user whose name is on it if they're non-admin** — [VALUE: med · EFFORT: M] — (Reinforces #10/#17.) The immutable record of exactly what was submitted under the user's identity should be visible to that owner, not gated behind admin. This is arguably the single most trust-important surface and it is admin-Debug-only today.

52. **No visible "the agent is waiting on YOU vs working" distinction in the badge** — [VALUE: low · EFFORT: S] — The Portal rail badge (`applicantPortal.js:981`) sums pending actions + informational notifs into one count. A user can't tell "3 things need my decision" from "3 FYIs." Distinguish action-required from informational in the badge so the user knows when they're the blocker.

53. **Two-factor hand-off waits up to 60s with only a button-label change** — [VALUE: low · EFFORT: S] — `applicantPortal.js:851` sets the button to "Waiting for your phone…" during a 60s poll. A progress/countdown and a clear "if you don't see a prompt, tap again" reduces the anxiety of a blocked, identity-bearing sign-in.

---

## Summary of the highest-leverage trust gaps

The product's safety *architecture* is strong (server-side gates, can't self-authorize submit, held integral changes, redline-before-submit, sealed vault). The **front-door gaps are about reachability and surfacing** of that safety:

- **Control is not where the user is** — no global/kill-switch pause outside admin Debug; the always-visible status strip is inert (#1–#3, #2).
- **The irreversible moment lacks the weight and recoverability it deserves** — text-confirm only, no undo window, no pre-submit snapshot preview (#4, #5, #10).
- **Honesty artifacts are hidden from the owner** — snapshot, audit log, and fabrication-guard attestation are admin-only or absent, exactly when/where the user is deciding to trust (#7, #10, #11, #17, #51).
- **Explainability degrades downstream** — the "why" exists at digest time but isn't carried to the final gate; uncertainty is never communicated (#8, #9, #14).
- **"What did it do overnight" is unserved** — no since-last-visit recap for the anxious returning user (#16).
