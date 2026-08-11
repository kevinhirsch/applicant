# Work order: fix ~49 test regressions introduced this session (digest skip-unscored + jobspy kwargs)

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc`. Commit locally, **do NOT push**. Fix CODE only — do NOT modify any test file. Apply EXACTLY the two changes below (both were pre-verified in a throwaway copy: 126/126 digest tests + 10/10 source tests pass, full suite drops to only 2 pre-existing failures). Do the minimal change; touch only the two files named.

## FIX 1 — digest includes unscored postings again. File: `src/applicant/application/services/digest_service.py`, method `_build_scored_pairs` (~lines 369-372)

Commit `9a53c4a5d` inserted a 2-line skip that drops unscored postings from the digest read path. The perf concern it claimed to solve is ALREADY handled by the pre-existing `DigestCache` (cache per campaign/UTC-day/posting-count/criteria), so this skip is redundant AND breaks the "unscored postings still surface" contract (~37 tests) and the freshness goal. **Delete the two inserted lines.**

```python
# BEFORE (current):
            user_added = (posting.source_key or "") == USER_ADDED_SOURCE_KEY
            if getattr(posting, "viability_score", None) is None and not user_added:
                continue  # digest is a fast READ: never LLM-score here; the tick scores the backlog
            row = {

# AFTER:
            user_added = (posting.source_key or "") == USER_ADDED_SOURCE_KEY
            row = {
```

Nothing else in this file changes. Do NOT touch the freshness sort (`_recency_bonus`, `build_digest`'s `rows.sort(...)`) or `first_seen`/`date_posted` capture.

**Verify green:**
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_s4_flow_fixes.py tests/unit/test_digest_delivery.py tests/unit/test_digest_email_styling_lens10.py tests/unit/test_bugsweep_batch_f_security.py tests/unit/test_cov_backlog_dupguard.py tests/unit/test_bugsweep_batch_i.py tests/unit/test_p1_8_keyword_coverage.py tests/unit/test_easy_apply_tag.py tests/unit/test_cov_backlog_perfdigestcache.py tests/unit/test_phase5_safety_gates.py tests/unit/test_cov_backlog_presubmit_verdicts_preview.py tests/unit/test_digest_criteria_wiring.py -q --tb=short
```
Expect: 126 passed, 0 failed.

## FIX 2 — discovery passes jobspy-only kwargs safely. File: `src/applicant/adapters/discovery/jobspy_searxng.py`

Commit `2fa300ca9` made `JobSpySource.fetch` call `self._client.scrape(..., is_remote=True, country_indeed="usa", hours_old=336)` unconditionally. Test doubles whose `scrape()` doesn't declare those kwargs (and has no `**kwargs`) raise `TypeError`, which `fetch`'s `except` swallows into SOURCE_ERROR → every board reports failure (~12 tests). Also, hardcoding `is_remote/country_indeed=usa` wrongly forces explicit international (UK/Germany) searches through the US-remote lane.

**Step 2a.** Add `import inspect` near the top (after `from __future__ import annotations`, alongside `import time as _time`):
```python
# BEFORE:
import time as _time
from dataclasses import dataclass, field
# AFTER:
import inspect
import time as _time
from dataclasses import dataclass, field
```

**Step 2b.** Replace `JobSpySource.fetch` from `def fetch(...)` through the line `except Exception as exc:  # a flaky board must never crash the whole run` inclusive:

```python
# BEFORE:
    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        location = criteria.locations[0] if criteria.locations else None
        # US-remote scoping (FR-DISC): "Remote"/unset is not a jobspy PLACE; default to
        # the US and request remote-only so discovery yields US-remote roles.
        if not location or location.strip().lower() in ("remote", "anywhere", "us remote"):
            location = "United States"
        # H2 (no silent underdelivery): a swallowed fetch failure must stay
        # observable — the aggregator reads ``last_error`` after each fetch so a
        # failed board is reported as *failed*, never as merely empty.
        self.last_error: str | None = None
        try:
            rows = self._client.scrape(
                site=self.site,
                search_term=_search_term(criteria),
                location=location,
                results_wanted=self._results_wanted,
                proxies=self._proxy.as_list(),
                is_remote=True,
                country_indeed="usa",
                hours_old=336,  # ~2 weeks: keep the pool FRESH so we surface recent roles early
            )
        except Exception as exc:  # a flaky board must never crash the whole run

# AFTER:
    def fetch(self, campaign_id: CampaignId, criteria: SearchCriteria) -> list[JobPosting]:
        location = criteria.locations[0] if criteria.locations else None
        # US-remote scoping (FR-DISC): "Remote"/unset is not a jobspy PLACE; default to
        # the US and request remote-only ONLY when the caller didn't state a region --
        # an explicit non-US location (UK/Germany/etc.) must reach ITS OWN country/board,
        # never be silently forced into US-remote-only.
        us_remote_default = not location or location.strip().lower() in (
            "remote", "anywhere", "us remote",
        )
        if us_remote_default:
            location = "United States"
        # H2 (no silent underdelivery): a swallowed fetch failure must stay
        # observable — the aggregator reads ``last_error`` after each fetch so a
        # failed board is reported as *failed*, never as merely empty.
        self.last_error: str | None = None
        scrape_kwargs: dict = dict(
            site=self.site,
            search_term=_search_term(criteria),
            location=location,
            results_wanted=self._results_wanted,
            proxies=self._proxy.as_list(),
        )
        # cf25c17be's freshness window applies to every fetch; US-remote scoping only
        # applies when we defaulted the location ourselves.
        extra_kwargs: dict = {"hours_old": 336}  # ~2 weeks: keep the pool FRESH
        if us_remote_default:
            extra_kwargs["is_remote"] = True
            extra_kwargs["country_indeed"] = "usa"
        # These jobspy-specific extras are OPTIONAL on the JobSpyClient Protocol --
        # only pass the ones the injected client's scrape() actually declares, so a
        # lightweight/legacy test double without a **kwargs catch-all is never handed
        # an unexpected keyword argument (which would otherwise misreport a healthy
        # board as SOURCE_ERROR instead of SOURCE_OK).
        try:
            sig_params = inspect.signature(self._client.scrape).parameters
        except (TypeError, ValueError):
            sig_params = {}
        accepts_all_kwargs = any(
            p.kind is inspect.Parameter.VAR_KEYWORD for p in sig_params.values()
        )
        for key, value in extra_kwargs.items():
            if accepts_all_kwargs or key in sig_params:
                scrape_kwargs[key] = value
        try:
            rows = self._client.scrape(**scrape_kwargs)
        except Exception as exc:  # a flaky board must never crash the whole run
```

The `except:` body and the `for raw in rows:` loop below are unchanged.

**Verify green:**
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit/test_p2_13_source_reliability.py -q --tb=short
```
Expect: 10 passed.

## FINAL verification + commit
Run the FULL unit suite:
```
cd /a0/usr/projects/applicant && uv run python -m pytest tests/unit -q --tb=line
```
Expect: exactly **2 failed** — ONLY `test_prod_compose_env_file.py::test_applicant_ui_env_file_still_references_dotenv` and `test_deploy_hardening_lens04.py::test_chromadb_is_pinned_persists_to_data_and_ui_gates_on_it` (both pre-existing, NOT this session's — leave them). Everything else green (~8166 passed).

Then ONE commit on the branch (NO push):
`fix(engine): restore digest surfacing of unscored postings + pass jobspy-only kwargs safely — repair regressions from 9a53c4a5d and 2fa300ca9 [FR-FIX]`

Report exact files changed + the final full-suite pass/fail counts.
