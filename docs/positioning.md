# Positioning statement — P4-1

**Status: DONE — owner picked Candidate A.** The chosen line — *"The autopilot that can't
fire itself: free, open source, and built so a human always has the final say before anything
gets submitted."* — is now applied: the landing hero (`workspace/static/landing.html` slogan
"The autopilot that can't fire itself." + the lede's "Free, open source, self-hosted … built
so a human always has the final say") and the `README.md` tagline. The candidate analysis
below is kept as the rationale of record.

## What's now decided + proven (the ground this is built on)

- **P4-DEC-1 (open source vs. closed): decided — open source, keeping the existing MIT
  license.** Combined with
  **pricing: free/donate** (no license fee; the project accepts optional donations rather
  than charging a seat/subscription price). Both are now settled inputs to this story,
  where the backlog previously carried P4-DEC-1 as an open owner decision (`—` in the
  index table) and P4-6 (pricing validation) as blocked on a cohort. This positioning
  statement is a first-cut, not a validated one — P4-6 still runs a real pricing test
  with the early-access cohort before public launch.
- **Review-before-submit is architectural, not a setting** — `docs/competitive-teardown.md`
  §4.1 confirms it's the sharpest, cheapest-to-defend claim: within the eight researched
  competitors, every one either auto-submits by default or treats "autofill so a human
  clicks submit" as the whole product, with no reviewed/tailored pipeline behind it.
  Applicant is the only one in that set where a human final say is enforced in core logic
  (the engine cannot self-authorize a final submit), not a UI convention a future release
  could quietly drop.
- **Honest by construction (the H-series)** — an unverified parse says so, corrections/
  drops/restorations are counted and surfaced, and "I read N details" only ever counts
  what actually happened this run. `docs/competitive-teardown.md` §4.5 finds no researched
  competitor publishes anything like this.
- **Protected-question honesty is a stated, code-enforced policy** — EEO/demographic and
  work-authorization questions are never AI-answered in either lane; the user's own words
  or an honest deferral, decided server-side (`core/rules/sensitive_fields.py`). No
  researched competitor discloses any such policy at all (`docs/competitive-teardown.md`
  §3, §4.2) — an absence, not a claim we're contradicting.
- **Human final say** — every application is filed for review before anything ships; the
  existing `#trust`/`#faq` copy on the landing page already states this in plain language
  and is the anchor the new line must stay consistent with, not exceed.
- **No vendor mortality / no Applicant-operated server** — self-hosted, so there is no
  company-operated cloud that can shut down and take a user's job-search history with it.
  Sonara's 2024 shutdown → acquisition → relaunch → reported 2026 outages
  (`docs/competitive-teardown.md` §0, §3) is a sourced, real cautionary tale for this
  argument, not a hypothetical.

## Guardrails this line must respect (so it doesn't over-claim)

- **Scope every comparative word.** `docs/competitive-teardown.md`'s scope caveat applies:
  "no competitor," "the only one," etc. are bounded to the eight researched products
  (AIHawk, LazyApply, Simplify, Teal, Huntr, JobRight.ai, AIApply, Sonara), not the whole
  market. None of the candidates below use an unscoped absolute claim in the line itself;
  the *supporting* copy that explains the line (landing `#trust`/competitive callouts)
  is where the scoping caveat has to be carried, per H5's calibrated-copy bar.
- **Don't win a volume argument.** The teardown explicitly recommends not competing on
  raw application counts (LazyApply's 1,500/day, Sonara's "100/week") — none of the
  candidates below mention volume.
- **Don't overstate LinkedIn.** P2-14 is assisted-mode only; no candidate implies full
  LinkedIn autopilot.
- **The decided claim is "open source (MIT)," not "source-available."** DEC-1 resolved to
  *keep the existing MIT `LICENSE`* — genuinely open source, a stronger and simpler claim
  than "source-available." The existing landing copy (`#start`: "It's open source and
  free") and the shipped MIT `LICENSE` already agree with the decided line, so there is no
  license-text change to reconcile and no silent contradiction to guard against. Every
  candidate below therefore says "open source," never "source-available." (P2-4 already
  confirmed fork/dependency license compatibility, so no follow-up license edit is pending —
  only the positioning wording this story drafts.)

## Candidates

Each names the enemy first, then the defensible proof underneath it.

### Candidate A — "The autopilot that can't fire itself"

> **The autopilot that can't fire itself: free, open source, and built so a human
> always has the final say before anything gets submitted.**

- **Enemy named:** auto-apply tools that submit on your behalf by default (LazyApply,
  Sonara, and the archived AIHawk script all auto-submit once configured) — the category's
  most common failure mode is "it applied for me before I could stop it."
- **Why defensible:** review-before-submit is enforced in the engine's core logic, not a
  toggle (competitive-teardown §4.1) — this is the single sharpest, most code-provable
  claim available. "Free, open source" is now a decided fact (DEC-1 + free/donate
  pricing), not aspirational.
- **Risk:** "can't fire itself" is a strong, slightly cute phrase — reads clearly once you
  know the product, but on a cold read a visitor might parse "fire" as "launch" rather than
  "self-terminate/self-authorize." Worth a plain-language gloss immediately under it (the
  existing lede already does this well).

### Candidate B — "Won't fake it to make you feel good"

> **Free, open source, and honest about what it doesn't know — the job-application
> agent that would rather tell you it isn't sure than invent an answer.**

- **Enemy named:** the general pattern of AI tools (in this category and generally) that
  paper over uncertainty — silently guessing, auto-filling a plausible-sounding answer to
  a protected question, or claiming full coverage/verification it didn't actually do.
- **Why defensible:** the H-series honesty invariants (unverified parse says so, drops/
  restorations counted, "I read N" only counts what happened) plus the protected-question
  policy (EEO/work-authorization never AI-answered, `core/rules/sensitive_fields.py`) are
  both code-enforced and, per the teardown, undisclosed by every researched competitor.
- **Risk:** "honest about what it doesn't know" is the most novel claim (per teardown §4.5,
  no competitor publishes anything like it) but also the hardest for a first-time visitor
  to *feel* without a concrete demo — it lands better after the proof screenshots (P4-3)
  exist than as a cold-open headline. Doesn't foreground the review-before-submit or
  self-hosted facts at all, which are more immediately legible.

### Candidate C — "No company to shut down"

> **Self-hosted with no company behind it to shut down — free, open source, and it
> can't submit anything without you, so your job search doesn't disappear if we do.**

- **Enemy named:** vendor mortality — cloud SaaS tools whose shutdown (or acquisition, or
  outage) takes a user's application history and job-search state with them. Sonara is the
  concrete, sourced example (2024 abrupt shutdown → BOLD acquisition → relaunch → reported
  2026 outages, teardown §0/§3).
  Sonara-specific detail is
  kept out of the tagline itself — it's a supporting proof point for the landing page, not
  a claim to put in the one-liner (naming a specific competitor by name in the headline
  invites a dated, falsifiable claim if their status changes again, per the teardown's own
  "this category moves fast" warning).
- **Why defensible:** self-hosted + no Applicant-operated server is verifiable in the
  source itself (open source lets a visitor go check this claim directly, not take it
  on faith) — pairs naturally with the open-source (MIT) decision.
- **Risk:** leads with the "no company" framing before explaining what the product *does*
  — reads as a privacy/durability pitch rather than a "here's what it automates" pitch;
  works best as a secondary line under a hero that opens with the autonomous-agent framing
  already on the landing page.

## Recommendation

**Candidate A** — *"The autopilot that can't fire itself: free, open source, and
built so a human always has the final say before anything gets submitted."*

Reasoning: it leads with the single hardest-to-copy, code-provable differentiator
(review-before-submit as architecture — no researched competitor enforces this in logic,
not just policy), names the enemy a first-time visitor already expects to worry about
("will this thing submit garbage under my name without asking me?"), and folds in both
newly-decided facts (open source, free/donate) without contradicting the existing
`#trust`/`#faq`/`#pricing` copy — it's a tightening of what's already shipped, not a new
claim. Candidate B is the more novel claim but reads better as supporting copy once P4-3's
proof assets exist; Candidate C is a strong secondary/privacy-section line but leads with
a fear appeal before establishing what the product does. If the owner wants to combine two,
A (headline) + C (as the `#privacy`/self-hosted section's framing, which already exists in
substance) is the cleanest split — no rewrite needed to make that combination work, since
`#privacy`'s existing "Applicant doesn't have any [servers]" section already carries C's
argument almost verbatim.

## The throughline (how every asset derives from the chosen line)

Once the owner picks a line (A, B, C, or a hybrid), it becomes the single source every
other asset is trimmed to fit, not re-derived independently:

- **Tagline / hero (`workspace/static/landing.html` `.hero .slogan` + `<h1>`):** the
  current slogan ("Always on call.") and h1 ("An autonomous agent that applies to jobs for
  you, 24/7.") describe *what* it does but not the chosen line's *enemy*. The chosen line's
  enemy-naming clause would replace or sit directly under the h1's `<p class="lede">`,
  which already states "holds it for your review before anything is ever submitted" and
  "Self-hosted, local-first" — the lede needs no new claim, only tightening to the exact
  chosen wording once picked (and adding "open source"/"free" language explicitly, if
  the chosen line makes that pairing).
- **`#trust` section (already ships "the honest contract, in plain language"):** the
  positioning line's proof points map directly onto its three existing cards ("What it
  does," "What it promises," "You stay in control") — no new card needed, just confirming
  the chosen line doesn't say anything these cards don't already back up.
- **`#pricing` section:** already states "$0 for the software" / "Free to run. You bring
  the compute." — consistent with "free/donate" already; would gain the donate framing
  explicitly once decided (a "support the project" link/CTA is not currently present and
  is a natural, small follow-up once the line is blessed, tracked as a P4-2 follow-up, not
  part of this story).
- **`#faq`:** already answers "does it submit without asking me" and "is my data stored on
  your servers" in the exact terms the chosen line needs — no rewrite, just verification
  once the line is picked that no FAQ answer contradicts it.
- **README.md:** currently a two-line stub ("A self-hosted, single-operator workspace.").
  The chosen line is the natural first sentence to add once blessed — this is the shortest,
  lowest-risk asset to update first as a proof-of-concept for the throughline, since it has
  no existing competing copy to reconcile.
- **P4-2 (landing page) DoD already quotes a placeholder P4-1 line verbatim** ("autopilot
  with a human final say — self-hosted, private, and honest") and flags that P4-1 itself
  isn't formally closed. Once the owner blesses a candidate here, that DoD quote should be
  swapped for the real line as part of closing this story, not before.

## Consumption plan (what does NOT change yet)

Per this story's DoD, no landing hero copy or README copy is being rewritten now. The
candidates above are staged for the owner's pick; once chosen, the "throughline" section
is the punch list for what to touch (hero lede tightening, README first sentence, P4-2's
DoD quote) — tracked as fast-follow edits once P4-1 is formally closed, not bundled into
this drafting pass.
