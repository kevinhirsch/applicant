"""Real-postings validation gate (``adapters/discovery/validate.py``, NFR-EXT-1).

Kevin's explicit rule: "verified data sources that actually serve real jobs" is a
REQUIREMENT for adding any discovery source. These tests pin the gate's behavior
in isolation (pure, no network) so both ``DiscoveryService.add_board`` and the
offline pre-deploy validation script (``scripts/validate_discovery_boards.py``)
can rely on it.
"""

from __future__ import annotations

import pytest

from applicant.adapters.discovery.validate import (
    PROVIDER_SHAPES,
    SourceValidationResult,
    validate_postings_shape,
    validate_provider_rows,
)


@pytest.mark.unit
class TestValidatePostingsShape:
    def test_empty_list_rejected(self):
        result = validate_postings_shape([], title_keys=("title",), url_keys=("url",))
        assert result.ok is False
        assert result.posting_count == 0
        assert "empty response" in result.reason

    def test_non_list_rejected(self):
        for junk in (None, {}, "not a list", 42):
            result = validate_postings_shape(
                junk, title_keys=("title",), url_keys=("url",)
            )
            assert result.ok is False
            assert result.posting_count == 0

    def test_rows_missing_title_or_url_rejected(self):
        rows = [{"title": "Engineer"}, {"url": "https://x.test/1"}, {"other": 1}]
        result = validate_postings_shape(rows, title_keys=("title",), url_keys=("url",))
        assert result.ok is False
        assert result.posting_count == 3  # raw row count, reported for diagnosis
        assert "not real postings" in result.reason

    def test_non_dict_rows_are_skipped_not_crashed(self):
        rows = ["a string row", 123, None, {"title": "Engineer", "url": "https://x.test/1"}]
        result = validate_postings_shape(rows, title_keys=("title",), url_keys=("url",))
        assert result.ok is True
        assert result.posting_count == 1

    def test_at_least_one_real_row_passes(self):
        rows = [
            {"title": "Engineer", "url": "https://x.test/1"},
            {"title": None, "url": None},  # junk row alongside a real one
        ]
        result = validate_postings_shape(rows, title_keys=("title",), url_keys=("url",))
        assert result.ok is True
        assert result.posting_count == 1  # only the REAL row is counted
        assert result.reason == ""

    def test_multiple_url_keys_either_satisfies(self):
        rows = [{"title": "Engineer", "applyUrl": "https://x.test/apply"}]
        result = validate_postings_shape(
            rows, title_keys=("title",), url_keys=("hostedUrl", "applyUrl")
        )
        assert result.ok is True
        assert result.posting_count == 1

    def test_result_is_frozen_dataclass(self):
        result = SourceValidationResult(ok=True, posting_count=3)
        with pytest.raises(Exception):
            result.ok = False  # frozen: mutation must raise


@pytest.mark.unit
class TestValidateProviderRows:
    @pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby", "smartrecruiters", "workday"])
    def test_every_supported_provider_has_a_shape(self, provider):
        assert provider in PROVIDER_SHAPES

    def test_greenhouse_real_row_passes(self):
        rows = [{"title": "Senior Engineer", "absolute_url": "https://boards.greenhouse.test/x"}]
        result = validate_provider_rows("greenhouse", rows)
        assert result.ok is True and result.posting_count == 1

    def test_lever_real_row_passes(self):
        rows = [{"text": "Senior Engineer", "hostedUrl": "https://jobs.lever.co/x/1"}]
        result = validate_provider_rows("lever", rows)
        assert result.ok is True and result.posting_count == 1

    def test_ashby_real_row_passes(self):
        rows = [{"title": "TPM", "jobUrl": "https://jobs.ashbyhq.com/x/1"}]
        result = validate_provider_rows("ashby", rows)
        assert result.ok is True and result.posting_count == 1

    def test_smartrecruiters_real_row_passes(self):
        rows = [{"name": "Delivery Manager", "id": "12345"}]
        result = validate_provider_rows("smartrecruiters", rows)
        assert result.ok is True and result.posting_count == 1

    def test_workday_real_row_passes(self):
        rows = [{"title": "Scrum Master", "externalPath": "/job/1"}]
        result = validate_provider_rows("workday", rows)
        assert result.ok is True and result.posting_count == 1

    def test_unknown_provider_fails_closed(self):
        result = validate_provider_rows("carrier-pigeon", [{"title": "x", "url": "y"}])
        assert result.ok is False
        assert result.posting_count == 0
        assert "unknown provider" in result.reason

    def test_greenhouse_rejects_rows_shaped_like_lever(self):
        # A row with Lever's fields but not Greenhouse's ("text"/"hostedUrl" instead
        # of "title"/"absolute_url") must NOT pass the Greenhouse gate -- proves the
        # shape check is provider-specific, not "any job-like dict".
        rows = [{"text": "Senior Engineer", "hostedUrl": "https://jobs.lever.co/x/1"}]
        result = validate_provider_rows("greenhouse", rows)
        assert result.ok is False
