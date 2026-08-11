# ADR-0012: Fit-Driven Scoring — score "would this candidate get a call?", not "is it in-domain?"

**Status:** Proposed (supersedes the hardcoded-allowlist approach in `src/applicant/core/rules/role_domain_fit.py`; grounds `docs/APPLICANT-BACKLOG.md` #46 profile-driven relevance gate).
**Numbering:** next free slot after `docs/adr/0011-candidate-fit-model.md`.
**Depends on:** ADR-0011 (Candidate Fit Model). **Sharpened by:** ADR-0013 (Outcome-Based Learning).

## Context

Same north star as ADR-0011: the product must make the fit judgment Claude makes live. Scoring is where that
judgment has to live.

**How scoring works today, and why it isn't fit.** After several hard-won iterations, viability scoring is:
(1) deterministic gates in `core/rules/posting_quality.py` (non-postings) + `core/rules/role_domain_fit.py`
(an **allowlist hardcoded to Agile-delivery role families**), then (2) an LLM tier that — verified live —
scores nearly everything ~93 and cannot discriminate, then (3) deterministic ranking factors (recency, US-
remote gate, SAFe-penalty, pay, seniority). This finally produces a *relevant* queue. But it answers **"is
this posting in Kevin's domain?"** — not **"would Kevin get a call for this specific role?"** The two diverge
sharply: a big-tech Senior TPM is "in domain" under a broadened allowlist yet a *reach* for a Scrum Master
with no TPM title and no degree; an enterprise Agile Coach is a *strong* fit. Today a human closes that gap.

**Two structural problems this ADR fixes:**
- The allowlist is **Kevin-hardcoded** — it doesn't generalize to a different target role or a different user
  (backlog #46). It must be **derived from the candidate**, not enumerated in code.
- The score has **no competitiveness dimension** — no title-history match, no degree gate, no level match,
  no industry fit — so it can't rank a strong fit above a reach.

## Decision

Scoring becomes a **fit judgment over the Candidate Fit Model (ADR-0011) × the posting**, deterministic-first,
in four ordered stages (the LLM assists on nuance, never as the primary discriminator — that lesson is banked):

1. **Hard gates (must-pass, else below-viable):** real job posting (`posting_quality`), and **US-remote**
   (inferred from location/description when `work_mode` is null; non-US or non-remote → gated out).
2. **Fit tier (DERIVED, not hardcoded):** match the posting's role against the candidate model's derived
   `strong_fit` / `viable_stretch` families (ADR-0011) — with synonyms + embedding similarity for near-matches.
   Out-of-tier → capped below viable. **This replaces `role_domain_fit`'s hand-listed allowlist with a
   profile-derived one** (backlog #46); today's Agile list becomes the derived default for an Agile résumé.
3. **Competitiveness signals (would they get a call?):**
   - **Title-history match** — has the candidate *held* this role/level, or is it a stretch? (strong-fit
     roles rank above stretch roles of equal freshness.)
   - **Degree gate** — if the description **hard-requires** a degree the candidate lacks, apply a penalty
     (ATS auto-filter reality); "preferred"/unstated → neutral.
   - **Level match** and **industry fit** (candidate's proven industries vs. the posting's).
4. **Preference & quality ranking (within-fit):** recency decay, pay-floor, SAFe-penalty (LeSS > SAFe taste),
   seniority — the factors already specified for the current ranking pass, now applied *within* the fit tiers.

Every stage is explainable and feeds the EXPLAIN greens/reds breakdown, so a score always carries *why*
("strong fit: title + certs + regulated-industry match; −: none" vs. "reach: no TPM title, degree-gated").

## Relation to other ADRs / migration

- **ADR-0011** supplies the model stages 2–3 reason over. Without it, scoring falls back to today's Agile
  allowlist (graceful degradation).
- The **fit-to-profile ranking + degree-penalty already requested of the scoring workstream** are the first
  slice of stage 3; this ADR is the architecture they land into.
- **ADR-0013** feeds outcome signals back into the tier boundaries + weights, so fit-scoring *improves with use*.
- Migration is incremental: `role_domain_fit` gains a `derive_from_profile(candidate_model)` path; the
  hardcoded lists remain as the Agile-default until the derivation ships, so no regression to today's working
  behavior.

## Consequences

- The product makes the reach-vs-strong-fit call **itself**, explainably — the core of "serve the right roles."
- **Generalizes** to any candidate/role (the point of #46).
- Deterministic-first keeps it cheap + reliable (the LLM-can't-discriminate lesson stays respected).
- Requires the degree/level/industry signals to be parsed from postings (bounded; description-based, with
  neutral defaults so unknowns don't over-penalize).
