# ADR-0013: Outcome-Based Learning — how Applicant exceeds a one-shot human read

**Status:** Proposed (grounds the "even potentially better than you" half of the 2026-08-11 north star; extends ADR-0009).
**Numbering:** next free slot after `docs/adr/0012-fit-driven-scoring.md`.
**Depends on:** ADR-0011 (Candidate Fit Model), ADR-0012 (Fit-Driven Scoring). **Extends:** ADR-0009 (Reflection Coach).

## Context

North star, second clause (product owner, 2026-08-11): the software should be **"even potentially better"**
than Claude at fit-judging roles. A human career advisor — or Claude — reads the résumé **once** and reasons
from a fixed snapshot. The product's structural advantage is that it can do the opposite: **learn from every
outcome, across the entire market, continuously, forever.** That is the only durable way it beats a one-shot
human read — not by being smarter per-decision, but by never stopping calibrating on *what actually worked*.

**What "worked" means here:** which applications got a recruiter reply, a screen, an interview, an offer —
vs. which ghosted. That signal is the ground truth about fit that no résumé read contains: it tells you the
candidate's *real* competitiveness for a role family, at specific companies, at a specific moment.

**What already exists to build on** (reuse-first):
- **The learning substrate is already partly built.** `src/applicant/application/services/learning_service.py`
  + `core/entities/learning_model.py` already fold approve/decline **taste** signals (`feature_stats`,
  `taste_bias` → a bounded score multiplier, `top_likes`/`top_dislikes`) AND — critically — maintain a
  **`converting_role_signature`**: a running centroid of the roles that *actually convert* (approved +
  submitted), explicitly built to "bias future discovery + scoring toward what converts" (FR-LEARN-5). Outcome
  learning is the extension of this seam from *converts-in-our-funnel* to *converts-in-the-market*.
- **Post-submission tracking already exists.** `PostSubmissionService` + the `applications` state machine
  (`TRACKER_STATES` — submitted-and-later) already model application progression; inbox/email-match plumbing
  exists in the scheduler.
- **ADR-0009's Reflection Coach** is the agent that reads effectiveness and applies reversible tweaks; this
  ADR gives it the outcome signal to reflect on.

## Decision

Close the loop on **application outcomes** and feed them back into the fit engine:

1. **Capture outcome states per application** — extend the existing post-submission tracking to a fuller funnel:
   `applied → viewed → responded → screen → interview → offer → rejected/ghosted`. Sources, cheapest-first:
   explicit user marking (one tap on a review card), inbox/email-match (already partly wired), and status
   scrapes where a source supports it. Unknown is a valid state (no fabrication).
2. **Feed outcomes back into three places:**
   - **The Candidate Fit Model (ADR-0011):** role families / companies / seniority bands that draw responses
     *strengthen* the candidate's derived strong-fit signal; families that consistently ghost *down-weight* —
     grounded in real outcomes, not the résumé alone.
   - **Fit-scoring weights (ADR-0012):** the outcome-conditioned centroid (extending `converting_role_signature`)
     and the competitiveness weights are tuned toward what actually converts *for this candidate*.
   - **The Reflection Coach (ADR-0009):** grades campaign effectiveness on the real KPI — *is the candidate
     getting calls/interviews, faster?* — not application volume, and applies **reversible, transparent**
     tweaks via the existing `CriteriaService.apply_learned_adjustment` seam (revertible via `clear_learned`).
3. **Keep it honest + reversible:** every learned adjustment carries a human-readable summary and is revertible
   (the existing `learned_adjustments` mechanism), so outcome-learning never silently drifts the candidate away
   from their own intent — the human can always see + undo what the loop concluded.

## Relation to other ADRs

- Completes the trio: **ADR-0011** models the candidate, **ADR-0012** scores fit from it, **ADR-0013** makes
  both **improve with use** — the mechanism by which Applicant becomes "better than a one-shot human read."
- **Extends ADR-0009** by supplying the effectiveness signal the Reflection Coach optimizes; the Automation
  Engineer half is unchanged.
- **ADR-0010 (durable memory)** persists the learned outcome signal across restarts.

## Consequences

- The product's fit-judgment **compounds** — every application makes the next pick better, across the whole
  market, 24/7.
- The KPI shifts from *volume produced* to *calls/interviews earned* — the metric that actually matters.
- Requires outcome capture (some manual/inferred); the design tolerates sparse/unknown outcomes and never
  fabricates a signal.
- Reversibility + transparency are load-bearing: an outcome loop that silently narrows the search is a defect,
  not a feature.
