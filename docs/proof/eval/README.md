# LLM output eval — golden-set material harness (P2-6)

This directory holds the **evidence** for the material-quality eval harness: a
live run's per-dimension scores + report, and the committed **baseline** the CI
lane gates future runs against.

## What the harness does

1. Loads a **golden set** of profiles × postings
   (`src/applicant/evaluation/goldens/`). The shipped set is **SYNTHETIC** — see
   its `README.md`. The runner accepts `--golden-dir` so the owner's real
   profiles can be dropped in with the same schema.
2. For every case, drives the **real `MaterialService` generation path** (the
   same code the agent loop uses) to produce a cover letter and/or an essay
   screening answer, deriving the truthfulness ground truth from a seeded
   profile exactly as the live loop does.
3. Judges each material across the agreed **rubric** — `relevance`, `tone`,
   `honesty` (zero-fabrication), `specificity`, `completeness` — with an
   LLM-as-judge (`material_judge.judge_material`), and cross-checks honesty with
   the service's **own deterministic fabrication guard**.
4. Aggregates per rubric dimension and **gates per dimension**: a regression in
   any dimension beyond the threshold (vs `baseline.json`) — or, without a
   baseline, any dimension below an absolute floor — fails the check.

## Running it

```bash
# Live (needs an OpenRouter key; cheap model by default):
OPENROUTER_API_KEY=sk-or-... uv run python -m applicant.evaluation.material_runner \
    --baseline docs/proof/eval/baseline.json --out reports/eval

# Offline smoke (no egress: deterministic generation + heuristic judging):
uv run python -m applicant.evaluation.material_runner --offline --max-cases 3
```

The **trigger** is the `Eval Lane` GitHub workflow
(`.github/workflows/ci-eval.yml`), `workflow_dispatch` + weekly — it reads
`OPENROUTER_API_KEY` from repo secrets (never inline) and fails the job on a
per-dimension regression, so a "meaningful prompt or model change" that degrades
output quality is caught. It is a dispatch/weekly lane (not a per-PR gate)
because live judging needs an LLM key and costs tokens — the same posture as the
integration lane.

## The evidence in this directory

- `material_eval_report.json` / `.md` — the first live run:
  **gpt-4o-mini** generating + judging the 20-case (32-material) synthetic
  golden set. Gate **PASS**; overall mean **4.60/5**; per-dimension means
  relevance 4.94, honesty 4.78, specificity 4.62, completeness 4.44, tone 4.22.
  Zero degraded (fallback) generations; 2 materials carried a deterministic
  fabrication flag (verb synonyms / an acronym the candidate genuinely uses),
  surfaced-for-review under the BALANCED policy, not blocked.
- `baseline.json` — the per-dimension means the CI lane gates against.

## Honest caveats (H-series)

- **Synthetic, not real.** These scores prove the *machinery* works end to end
  against realistic composites. They are **not** a claim about real-world quality
  on the owner's actual profiles. When real profiles are curated, re-run with
  `--golden-dir` and re-bless the baseline.
- **Judge is not ground truth.** The LLM-as-judge is a proxy; the deterministic
  fabrication cross-check and the human review gate remain the real
  truthfulness guarantees. The honesty dimension is reported *alongside* the
  deterministic flag count, never in place of it.
- A single cheap model produced both the material and the judgment in this run;
  a stronger judge (`--judge-model`) is supported when budget allows.
