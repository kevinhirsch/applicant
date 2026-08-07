# Work order: fix digest.html row template — fields misaligned with the API (rows don't render)

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, NO push. File: `a0-applicant/webui/digest.html` ONLY.

BUG (exposed now that the FE resolves the real campaign — 55 rows in data, but 0 render): the row `<template x-for>` and item markup reference field names that DON'T exist on the digest API rows. Confirmed actual row keys from `GET /api/digest/{cid}`:
`_recency, added_by_you, company, easy_apply, keyword_coverage, keyword_matched, keyword_missing, link, posting_id, salary, source, summary, title, viability_score, warnings, why_suggested, work_mode`
There is NO `application_id`, NO `role`, NO `score`, NO `why` on the rows.

## Required fixes (align template → real fields)
1. **x-for key (THE render blocker):** `<template x-for="row in rows" :key="row.application_id">` → `:key="row.posting_id"`. (All rows have `application_id===undefined`, so the duplicate key makes Alpine render nothing.)
2. `row.role` → `row.title` (both the `x-show` and `x-text`).
3. `row.score` → `row.viability_score` (the `x-show` and the `'Score: ' + row.score` text).
4. `row.why` → `row.why_suggested`.
5. **Approve/decline actions:** they currently pass an `application_id` that's undefined on the row. The engine's `DigestService._application_for` resolves EITHER an application id OR a posting id (via get_by_posting), so pass `row.posting_id` instead. Update the approve() and decline() calls/handlers and the buttons to use `row.posting_id` (keep sending it as the `application_id` field the proxy expects IF that's the wire name — i.e. `callJsonApi("digest", {action:"approve", application_id: row.posting_id})` — the engine resolves it). Verify against a0-applicant/api/digest.py: the approve/decline actions read `application_id` from input and forward to `/api/digest/applications/{that}/approve|decline`; the engine accepts a posting id there. So the FE just needs to pass row.posting_id as that value.
6. Review the REST of the item markup (lines ~56-88): for any other `row.<field>` reference, align it to the real keys above (e.g. company=`row.company`, salary=`row.salary`, work mode=`row.work_mode`, easy-apply badge=`row.easy_apply`, keyword coverage=`row.keyword_coverage`/`keyword_matched`/`keyword_missing`, summary=`row.summary`, warnings=`row.warnings`, freshness=`row._recency`, link=`row.link`, added-by-you=`row.added_by_you`, source=`row.source`). Do NOT invent fields; only map to keys that exist. Leave the feedback-row block (already correctly uses `row.posting_id`) unchanged.

## Verify
- Unit test still green: `cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_az2_digest_panel.py -q` (update the test ONLY if it asserted the old wrong field names; prefer not to).
- The template must render one `.item` per row keyed by posting_id with title/score/why populated.

Commit: `fix(ui): align digest row template with real API fields (posting_id/title/viability_score/why_suggested) so rows actually render [FR-UI]`
Report files changed + confirm the x-for key + the 4 field renames + approve/decline use posting_id.
