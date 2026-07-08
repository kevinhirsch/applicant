# Eval golden set (P2-6)

**Provenance: SYNTHETIC.** Every profile and posting in this directory was
**authored for the eval harness**. None is a real person, a real résumé, or a
real live job posting. They are realistic composites (diverse roles, seniorities,
and industries) built to exercise the material-generation + judging pipeline.

Honesty invariant (H-series): the harness and its reports label this set as
synthetic. Do **not** describe results run against this set as validated against
"real" data — they prove the *machinery*, not real-world quality.

## Structure

- `profiles.json` — the candidate side. Each profile carries an identity, a
  base-résumé text (the truthfulness ground truth), a flattened attribute cloud,
  and a short voice sample. These stand in for the owner's real profiles; the
  runner accepts a `--golden-dir` pointing at a different (e.g. owner-curated,
  real) set with the same schema.
- `postings.json` — the job side. Each posting carries a company, title,
  location, a job-description body, and the extracted `jd_terms` used for fit
  scoring / relevance.
- `pairs.json` — curated `(profile_id, posting_id)` cases. Each profile is
  paired with the postings that plausibly fit it, so relevance is a meaningful
  signal rather than a random cross-product.

## Swapping in the owner's real profiles

Point the runner at a directory with the same three files:

```bash
uv run python -m applicant.evaluation.material_runner --golden-dir /path/to/real
```

The real set should keep the `provenance` field honest (e.g.
`"OWNER-CURATED — real profiles and postings"`), which the report echoes verbatim.

**PII warning — reports generated from real data must never be committed or
uploaded.** `write_report` serializes the FULL text of every generated material
plus the case/profile/posting ids into `material_eval_report.json`/`.md`. When
the golden set is the owner's real résumé/profile data, those artifacts contain
that real PII. The committed evidence under `docs/proof/eval/` and the CI lane's
uploaded artifact are safe **only because the shipped set is synthetic**. Before
any real-data use: keep `--out` pointed at a local, git-ignored directory; do
NOT run a real set through the CI lane (its report is uploaded as a build
artifact); and redact `results[*].text` (and any identifying ids) before sharing
a report. The harness has no built-in redaction step yet — until one exists,
treat every real-data report as containing the full résumé.
