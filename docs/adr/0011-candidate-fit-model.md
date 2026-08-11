# ADR-0011: Candidate Fit Model — a competitiveness model of the applicant

**Status:** Proposed (grounds `docs/APPLICANT-BACKLOG.md` § the "serve the right roles at the right time" core value; first of the fit-engine trio ADR-0011/0012/0013).
**Numbering:** next free slot after `docs/adr/0010-durable-agent-memory-sql-backend.md`.
**Feeds:** ADR-0012 (Fit-Driven Scoring) reasons over this model; ADR-0013 (Outcome-Based Learning) sharpens it.

## Context

North star, product owner verbatim (2026-08-11):

> "Applicant the software should be capable of — and even potentially better than you [Claude] are at — doing exactly what you're doing for me right now."

"What Claude does right now" is the operative spec: **read the résumé, build an understanding of the
candidate's real competitiveness, and judge each role for genuine fit** ("would this candidate get a
*call*?") — not keyword overlap, not domain membership. Worked example that exposed the gap: a
Scrum Master with a decade in regulated finance/insurance and CSP-SM/A-CSM/SAFe/KMP certs **but no
bachelor's degree** is a *strong* fit for an enterprise Agile Coach / Delivery Manager role and a
*reach* for a big-tech Senior TPM (no TPM title history, a degree the ATS auto-filters on, endpoint/
DevOps automation rather than software-services depth). That judgment currently lives **in Claude**,
not in Applicant.

**Honest gap today.** Onboarding parses the résumé into a flat attribute cloud
(`src/applicant/application/services/attribute_cloud_service.py`, ~54 atomic `skill:*` / `work_history:*`
/ `education:*` / contact rows for a real campaign). That is a good store of *facts*, but it is not a
model of the candidate's *competitiveness*: nothing represents which roles the candidate has actually
**held** (vs. is adjacent to), at what **level**, in which **industries**, with what **degree/credential
gate**, or what their true **technical depth** is. Scoring therefore cannot make the reach-vs-strong-fit
call — so a human (Claude) makes it by re-reading the résumé each time. This ADR gives the product the
substrate to make that call itself.

**What already exists to build on** (reuse-first, `docs/APPLICANT-BACKLOG.md` line 13):
- Parsed résumé + raw text: `onboarding.base_resume` (verify-block, per-section confidence, `raw_text`)
  via `src/applicant/application/services/onboarding_service.py`.
- Structured facts: `AttributeCloudService` (the attribute cloud) — the fact layer this model derives over.
- An LLM tier + local embeddings already wired into the container for the derivation + similarity.
- Per-campaign persistence via the existing storage/session pattern.

## Decision

Introduce a **`CandidateProfile`** (a.k.a. Fit Model) entity + a `CandidateProfileService` that **derives
a structured competitiveness model** from `onboarding.base_resume` + the attribute cloud, refreshed on any
résumé/profile change and persisted per campaign. It captures, as first-class fields (not free text):

1. **Role/title history** — the titles actually held, each with level (associate → lead → principal),
   tenure, and whether it was the *primary* role vs. a stretch/coverage stint.
2. **Seniority trajectory** — current level + realistic target band.
3. **Credentials** — certifications (typed), and **education/degree presence** as an explicit boolean-plus-
   detail field, because "no bachelor's" is a hard, common ATS gate (see ADR-0012).
4. **Industries** — with depth + recency (regulated finance/insurance/aerospace/healthcare vs. incidental).
5. **Functional domains & skills** — with *evidence strength* (demonstrated-and-quantified vs. mentioned).
6. **Quantified achievements** — the wins that make the candidate competitive ($ saved, cycle-time, scale).
7. **True technical depth** — distinguishing real depth from adjacent (e.g. DevOps/endpoint automation ≠
   software-services engineering), so the model doesn't over-credit adjacent tech.
8. **Derived fit bands** — `strong_fit` / `viable_stretch` role families **computed from the above**, plus a
   fit *rationale* per band. These are DERIVED, not hand-authored (this is what makes it general — ADR-0012,
   and the profile-driven relevance gate, backlog #46).

Derivation is **deterministic-first with an LLM assist**: structural fields come from the parsed résumé +
attributes; the LLM is used to normalize titles, infer level, and articulate the fit rationale — but the
model is stored + inspectable, and re-derivable, so it is auditable and revertible.

## Relation to other ADRs / the current state

- **ADR-0012 (Fit-Driven Scoring)** consumes this model to score each posting for genuine fit and to make
  the reach-vs-strong-fit call the human currently makes. The Kevin-specific hardcoded allowlist in
  `core/rules/role_domain_fit.py` becomes the **derived default** when the model's history is Agile-delivery
  — i.e. today's emergency fix graduates into a general capability (backlog #46).
- **ADR-0013 (Outcome-Based Learning)** treats this model as the thing that gets **sharpened** by real
  application outcomes, which is how the product exceeds a one-shot human read.
- **ADR-0009 (Self-improving agents)** — the Reflection Coach reads this model + outcomes to grade campaign
  effectiveness and apply reversible tweaks.

## Consequences

- Fit becomes **explainable** ("strong because your title history + certs + regulated-industry match;
  reach because no TPM title + degree-gated") and surfaces into the EXPLAIN breakdown.
- The product **generalizes** — any candidate/any target role, because the fit bands are derived from the
  candidate, not a hardcoded Agile list.
- New derivation cost on résumé change (bounded; cached; re-derive only on change).
- Requires the fit model to degrade gracefully to today's behavior when the résumé is sparse.
