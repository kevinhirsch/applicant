# Citable invariants: truthfulness, human final say, and protected questions

Three product claims are strong enough to market only because they are pinned
by executable evidence. This page names each claim exactly, states its honest
boundaries, and gives the one-command reproduction. If any suite goes red, the
claim is no longer citable — treat that as a launch blocker, not a flaky test.
(Backlog: P2-5, P2-8, and P2-7; all pair with the Phase 1.5 honesty
invariants.)

## Claim 1 — "It rewrites freely; it never invents facts."

**Evidence:** `tests/unit/test_truth_claim_evidence.py`

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -q tests/unit/test_truth_claim_evidence.py
```

What the suite proves, case by case:

- **Every fact class is caught when invented** — employer, title,
  credential/certification, date, number/metric. One red-team case per class,
  each run under BOTH policies: the default **balanced** policy *surfaces* the
  invention for human review (returns it, never raises), and **strict** refuses
  it outright (`TruthfulnessViolation`).
- **Rewriting is genuinely free** — the same true claims aggressively
  re-ordered and re-framed produce zero flags (résumé-class mode), and a
  complete re-wording with new vocabulary passes in prose mode (cover letters /
  essays) as long as every named entity, credential, and figure stays real.
- **The shipped default is balanced** — surface-not-block is pinned as the
  no-argument behavior, per the owner's directive (P1-13).

Honest boundaries of the claim (also pinned, not hidden):

- The résumé-class check is **verbatim about claim tokens**: "processing"
  cannot silently become "processed". Free re-*wording* is the prose mode's
  domain; résumé-class freedom means re-ordering, re-framing, re-emphasis.
- The claim is "never **invents** facts" — NOT "never rewrites". The
  over-broad promise is deliberately absent from the product's copy.
- A surfaced fact is a *proposal*: it reaches a human in the review panel
  ("A few facts to double-check") with one-tap confirm-into-profile or remove.
  Nothing surfaced can reach a submission on its own — that is Claim 2.

## Claim 2 — "A human has the final say on every submission."

**Evidence:** `tests/unit/test_final_say_invariant.py`

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -q tests/unit/test_final_say_invariant.py
```

What the suite proves:

- **Behavioral** — every submit-recording entry point (auto-detected
  confirmation, one-tap mark-submitted, the durable pipeline's call) funnels
  through `SubmissionService.record_submission`, which enforces the review
  gate *before anything is recorded*: unapproved generated material — a cover
  letter, a screening answer, or the linked generated résumé variant — raises
  `ReviewRequired` and stores nothing. Approval itself refuses until the
  redline review surface has actually been opened. The full chain
  (review → approve → submit) is exercised end-to-end.
- **Structural** — an AST scan of the engine source proves the gated service
  (plus the demo seeder's synthetic fixtures) is the **only** code that
  constructs a submitted outcome, and that the post-submission service's
  outcome vocabularies (rejected / ghosted / interview / offer) cannot emit
  one. A new construction site anywhere in the engine turns the suite red, so
  a bypass cannot appear silently — the invariant is enforced against future
  code, not just today's.
- **The dynamic path is refused, not just unscanned** — review found the one
  writer a literal scan cannot see: the tracker's manual "record what
  happened" endpoint passes its outcome type straight through, and
  "submitted"/"converted" were recognized types. The service now refuses both
  submission-class types on that path (the human's "I submitted this myself"
  action is mark-submitted, which runs the gate), and the refusal is pinned
  behaviorally with unapproved material in place.

## Claim 3 — "Protected questions are never answered by AI."

**Evidence:** `tests/unit/test_sensitive_question_policy.py`

```bash
DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' \
  uv run pytest -q tests/unit/test_sensitive_question_policy.py
```

Two question classes are protected (P2-7), in BOTH lanes — screening-answer
generation and the pre-fill field resolver:

- **Demographic / EEO self-identification** — filled only from the user's
  explicit stored answer, else the canned decline-to-self-identify. Never
  guessed, and never saved into the reusable cross-application answer library.
- **Work authorization / visa / sponsorship** — answered only in the user's
  OWN words: an explicit answer, their onboarding intake, or a stored
  attribute. With nothing stored the engine defers with an honest
  needs-your-answer placeholder; it never answers a sponsorship question
  either way on its own. Presence-aware on purpose: an *unanswered* intake is
  never treated as "no".

Why this needs its own lane at classification time: an invented "No, I don't
require sponsorship" contains no fact-class tokens (no employer, date, or
number), so the fabrication guard of Claim 1 could not catch it downstream —
the refusal has to happen before any model is consulted. The tests wire an
LLM stub that fails the suite on ANY consultation, the strongest form of
"never guessed", and pin that a caller's `essay` flag cannot opt a protected
question back into the LLM path (enforcement is server-side).

Honest boundaries of the claim:

- Detection is cue-based (locale-configurable). A phrasing the cues miss does
  not fail silent — it lands in the ordinary essay/review lane, where Claim 2
  still holds: nothing reaches a submission without human approval.
- Each policy answer carries a visible `policy` provenance marker into the
  review UI's "What I drew on" panel, so a canned decline or deferral is
  distinguishable from a generated answer at review (no silent degradation).

Related, already-pinned guards this page does not restate: the engine cannot
self-authorize a final click past the pre-fill stop boundary (FR-PREFILL-5,
remote-router 403 path), and review-before-submit returns 409 at the HTTP
surface (`ensure_submittable`). See `docs/traceability.md` (FR-RESUME-8,
FR-PREFILL-5) for the full requirement mapping.
