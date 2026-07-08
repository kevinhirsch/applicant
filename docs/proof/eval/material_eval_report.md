# Material eval report (P2-6)

- **Provenance:** SYNTHETIC — authored for the eval harness; not real people or real résumés.
- **Run mode:** LIVE
- **Generation model:** `openai/gpt-4o-mini`
- **Judge model:** `openai/gpt-4o-mini`
- **Generated at:** 2026-07-08T21:10:13Z
- **Cases:** 20 · **Materials:** 32
- **Degraded (fallback) generations:** 0 · **Materials with a fabrication flag:** 2
- **Gate:** PASS

> Live run: a real model generated and judged every material.

> Deterministic fabrication flags are surfaced by the service's own entity-shaped prose guard under the shipped BALANCED policy, which flags tokens *for human review* rather than blocking. It is deliberately conservative (it flags verb synonyms like "Developed" for "Built", or a bare acronym the candidate genuinely uses), so a nonzero count is expected and reviewed — it is reported here, not treated as a gate failure unless `--max-fabrication-materials` is set.

## Per-dimension mean score (1-5)

| Dimension | Mean | Delta vs baseline |
| --- | --- | --- |
| relevance | 4.94 | — |
| tone | 4.22 | — |
| honesty | 4.78 | — |
| specificity | 4.62 | — |
| completeness | 4.44 | — |
| **overall** | **4.60** | |

## Per-material results

| Case | Type | Overall | Fabrications | Degraded |
| --- | --- | --- | --- | --- |
| prof-backend-eng|post-be-01 | cover_letter | 5.00 | none | no |
| prof-backend-eng|post-be-01 | screening_answer | 5.00 | none | no |
| prof-data-analyst|post-da-01 | cover_letter | 4.80 | none | no |
| prof-data-analyst|post-da-01 | screening_answer | 4.80 | none | no |
| prof-marketing-mgr|post-mk-01 | cover_letter | 4.60 | none | no |
| prof-marketing-mgr|post-mk-01 | screening_answer | 4.80 | none | no |
| prof-registered-nurse|post-rn-01 | cover_letter | 4.60 | none | no |
| prof-registered-nurse|post-rn-01 | screening_answer | 4.60 | none | no |
| prof-backend-eng|post-be-02 | cover_letter | 4.80 | none | no |
| prof-backend-eng|post-be-02 | screening_answer | 4.40 | none | no |
| prof-data-analyst|post-da-03 | cover_letter | 4.60 | none | no |
| prof-data-analyst|post-da-03 | screening_answer | 4.80 | none | no |
| prof-marketing-mgr|post-mk-04 | cover_letter | 4.60 | none | no |
| prof-marketing-mgr|post-mk-04 | screening_answer | 4.40 | none | no |
| prof-registered-nurse|post-rn-02 | cover_letter | 4.60 | none | no |
| prof-registered-nurse|post-rn-02 | screening_answer | 4.20 | none | no |
| prof-backend-eng|post-be-04 | cover_letter | 5.00 | Languages, Databases, Technologies, Areas, Expertise, APIs | no |
| prof-backend-eng|post-be-04 | screening_answer | 5.00 | none | no |
| prof-data-analyst|post-da-05 | cover_letter | 4.80 | none | no |
| prof-data-analyst|post-da-05 | screening_answer | 4.20 | none | no |
| prof-marketing-mgr|post-mk-03 | cover_letter | 4.60 | none | no |
| prof-marketing-mgr|post-mk-03 | screening_answer | 3.80 | ROI | no |
| prof-registered-nurse|post-rn-05 | cover_letter | 4.80 | none | no |
| prof-registered-nurse|post-rn-05 | screening_answer | 4.40 | none | no |
| prof-backend-eng|post-be-05 | screening_answer | 4.60 | none | no |
| prof-data-analyst|post-da-02 | screening_answer | 5.00 | none | no |
| prof-marketing-mgr|post-mk-02 | screening_answer | 4.60 | none | no |
| prof-registered-nurse|post-rn-03 | screening_answer | 4.80 | none | no |
| prof-backend-eng|post-be-03 | screening_answer | 3.60 | none | no |
| prof-data-analyst|post-da-04 | screening_answer | 4.80 | none | no |
| prof-marketing-mgr|post-mk-05 | screening_answer | 4.40 | none | no |
| prof-registered-nurse|post-rn-04 | screening_answer | 4.20 | none | no |
