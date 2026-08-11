"""Unit tests for applicant.core.rules.underdelivery."""

from __future__ import annotations

import pytest

from applicant.core.rules.underdelivery import (
    SOURCE_OK,
    SOURCE_EMPTY,
    SOURCE_ERROR,
    SOURCE_RATE_LIMITED,
    _MAX_NAMED_FIELDS,
    source_label,
    source_shortfall_message,
    discovery_shortfalls,
    prefill_shortfall,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Parallel-xdist safety: nothing cached at module level."""
    yield


# ── source_label tests ────────────────────────────────────────────────────────


class TestSourceLabel:
    """Tests for source_label()."""

    @pytest.mark.unit
    def test_empty_key(self):
        """An empty / None key returns 'an unnamed source'."""
        assert source_label("") == "an unnamed source"
        assert source_label(None) == "an unnamed source"  # type: ignore[arg-type]

    @pytest.mark.unit
    def test_whitespace_key(self):
        """A whitespace-only key returns 'an unnamed source'."""
        assert source_label("   ") == "an unnamed source"

    @pytest.mark.unit
    def test_no_prefix_capitalises(self):
        """A key without a colon prefix capitalises the first letter."""
        assert source_label("indeed") == "Indeed"

    @pytest.mark.unit
    def test_jobspy_prefix_removed(self):
        """A jobspy: prefix is stripped and the tail is capitalised."""
        assert source_label("jobspy:indeed") == "Indeed"
        assert source_label("jobspy:linkedin") == "Linkedin"

    @pytest.mark.unit
    def test_rss_prefix_yields_feed_label(self):
        """An rss: prefix produces '{Tail} feed'."""
        assert source_label("rss:hn-hiring") == "Hn-hiring feed"
        assert source_label("rss:stackoverflow") == "Stackoverflow feed"

    @pytest.mark.unit
    def test_searxng_becomes_web_search(self):
        """searxng (lowercase) yields 'Web search'."""
        assert source_label("searxng:searxng") == "Web search"

    @pytest.mark.unit
    def test_searxng_no_prefix(self):
        """A bare 'searxng' key yields 'Web search'."""
        assert source_label("searxng") == "Web search"

    @pytest.mark.unit
    def test_searxng_case_insensitive(self):
        """The searxng match is case-insensitive."""
        assert source_label("Searxng") == "Web search"
        assert source_label("SEARXNG") == "Web search"

    @pytest.mark.unit
    def test_searxng_inside_prefix(self):
        """A non-searxng tail with searxng prefix works normally."""
        assert source_label("searxng:indeed") == "Indeed"

    @pytest.mark.unit
    def test_unknown_prefix_keeps_capitalised_tail(self):
        """An unknown prefix is stripped, and the tail is capitalised."""
        assert source_label("custom:myboard") == "Myboard"

    @pytest.mark.unit
    def test_prefix_only_no_tail(self):
        """A key with a prefix but no tail (trailing colon) treats prefix as tail."""
        assert source_label("jobspy:") == "Jobspy"

    @pytest.mark.unit
    def test_mixed_case_tail(self):
        """The tail is capitalised preserving the rest of the case."""
        assert source_label("rss:hn-hiring") == "Hn-hiring feed"
        assert source_label("jobspy:indeed") == "Indeed"


# ── source_shortfall_message tests ────────────────────────────────────────────


class TestSourceShortfallMessage:
    """Tests for source_shortfall_message()."""

    @pytest.mark.unit
    def test_ok_returns_none(self):
        """SOURCE_OK returns None."""
        assert source_shortfall_message("jobspy:indeed", SOURCE_OK) is None

    @pytest.mark.unit
    def test_unknown_status_returns_none(self):
        """An unknown status returns None."""
        assert source_shortfall_message("jobspy:indeed", "unknown_status") is None

    @pytest.mark.unit
    def test_empty_status(self):
        """SOURCE_EMPTY returns a nothing-returned message."""
        msg = source_shortfall_message("jobspy:indeed", SOURCE_EMPTY)
        assert msg is not None
        assert "returned nothing" in msg
        assert "Indeed" in msg

    @pytest.mark.unit
    def test_error_no_detail(self):
        """SOURCE_ERROR without error details returns a 'could not be searched' message."""
        msg = source_shortfall_message("jobspy:indeed", SOURCE_ERROR)
        assert msg is not None
        assert "could not be searched" in msg
        assert "Indeed" in msg

    @pytest.mark.unit
    def test_error_with_detail(self):
        """SOURCE_ERROR with error details includes the error."""
        msg = source_shortfall_message("searxng", SOURCE_ERROR, error="Connection refused")
        assert msg is not None
        assert "could not be searched" in msg
        assert "Connection refused" in msg

    @pytest.mark.unit
    def test_error_with_none_error(self):
        """SOURCE_ERROR with error=None produces no parenthetical detail."""
        msg = source_shortfall_message("searxng", SOURCE_ERROR, error=None)
        assert msg is not None
        assert "could not be searched" in msg
        assert "(" not in msg

    @pytest.mark.unit
    def test_rate_limited(self):
        """SOURCE_RATE_LIMITED returns a 'skipped to avoid over-asking' message."""
        msg = source_shortfall_message("jobspy:indeed", SOURCE_RATE_LIMITED)
        assert msg is not None
        assert "skipped" in msg
        assert "avoid over-asking" in msg
        assert "Indeed" in msg

    @pytest.mark.unit
    def test_empty_source_key(self):
        """An empty source key uses 'an unnamed source' in the message."""
        msg = source_shortfall_message("", SOURCE_EMPTY)
        assert msg is not None
        assert "an unnamed source" in msg

    @pytest.mark.unit
    def test_rss_source_in_message(self):
        """An RSS source key produces a feed label in the message."""
        msg = source_shortfall_message("rss:hn-hiring", SOURCE_EMPTY)
        assert msg is not None
        assert "Hn-hiring feed" in msg


# ── discovery_shortfalls tests ────────────────────────────────────────────────


class TestDiscoveryShortfalls:
    """Tests for discovery_shortfalls()."""

    @pytest.mark.unit
    def test_empty_outcomes(self):
        """Empty outcomes list returns empty list."""
        assert discovery_shortfalls([]) == []

    @pytest.mark.unit
    def test_all_ok_returns_empty(self):
        """All sources with SOURCE_OK return no shortfalls."""
        outcomes = [
            {"source_key": "jobspy:indeed", "status": SOURCE_OK, "found": 5, "error": None},
            {"source_key": "searxng", "status": SOURCE_OK, "found": 3, "error": None},
        ]
        assert discovery_shortfalls(outcomes) == []

    @pytest.mark.unit
    def test_all_shortfall_statuses(self):
        """Each shortfall status yields a shortfall record."""
        outcomes = [
            {"source_key": "jobspy:empty", "status": SOURCE_EMPTY, "found": 0, "error": None},
            {"source_key": "jobspy:error", "status": SOURCE_ERROR, "found": 0, "error": "timeout"},
            {"source_key": "jobspy:rate", "status": SOURCE_RATE_LIMITED, "found": 0, "error": None},
        ]
        result = discovery_shortfalls(outcomes)
        assert len(result) == 3
        for r in result:
            assert "source_key" in r
            assert "status" in r
            assert "found" in r
            assert "message" in r
            assert "error" in r

    @pytest.mark.unit
    def test_mixed_ok_and_shortfalls(self):
        """Only shortfall statuses appear in the result; ok ones are filtered."""
        outcomes = [
            {"source_key": "jobspy:a", "status": SOURCE_OK, "found": 10, "error": None},
            {"source_key": "jobspy:b", "status": SOURCE_EMPTY, "found": 0, "error": None},
            {"source_key": "jobspy:c", "status": SOURCE_OK, "found": 2, "error": None},
        ]
        result = discovery_shortfalls(outcomes)
        assert len(result) == 1
        assert result[0]["source_key"] == "jobspy:b"
        assert result[0]["status"] == SOURCE_EMPTY

    @pytest.mark.unit
    def test_unknown_status_ignored(self):
        """Unknown statuses are ignored (same as SOURCE_OK)."""
        outcomes = [
            {"source_key": "jobspy:a", "status": "bogus", "found": 0, "error": None},
        ]
        assert discovery_shortfalls(outcomes) == []

    @pytest.mark.unit
    def test_missing_keys(self):
        """Missing 'source_key' or 'status' keys use empty strings."""
        outcomes = [
            {"status": SOURCE_EMPTY, "found": 0, "error": None},
        ]
        result = discovery_shortfalls(outcomes)
        # Empty source key + SOURCE_EMPTY => 'an unnamed source returned nothing ...'
        assert len(result) == 1
        assert result[0]["source_key"] == ""
        assert "an unnamed source" in result[0]["message"]

    @pytest.mark.unit
    def test_extra_keys_tolerated(self):
        """Extra keys in outcome dicts are tolerated."""
        outcomes = [
            {"source_key": "jobspy:a", "status": SOURCE_EMPTY, "found": 0, "error": None, "extra": "stuff"},
        ]
        result = discovery_shortfalls(outcomes)
        assert len(result) == 1
        assert result[0]["source_key"] == "jobspy:a"

    @pytest.mark.unit
    def test_non_dict_outcome_skipped(self):
        """Non-dict items in outcomes are skipped."""
        outcomes: list = [
            {"source_key": "jobspy:a", "status": SOURCE_EMPTY, "found": 0, "error": None},
            "not a dict",
            42,
            None,
        ]
        result = discovery_shortfalls(outcomes)
        assert len(result) == 1
        assert result[0]["source_key"] == "jobspy:a"

    @pytest.mark.unit
    def test_found_defaults_to_zero(self):
        """Missing 'found' defaults to 0."""
        outcomes = [
            {"source_key": "jobspy:a", "status": SOURCE_EMPTY, "error": None},
        ]
        result = discovery_shortfalls(outcomes)
        assert result[0]["found"] == 0

    @pytest.mark.unit
    def test_found_non_int_coerces_to_zero(self):
        """Non-integer 'found' values are coerced to 0."""
        outcomes = [
            {"source_key": "jobspy:a", "status": SOURCE_EMPTY, "found": "abc", "error": None},
            {"source_key": "jobspy:b", "status": SOURCE_ERROR, "found": None, "error": "err"},
        ]
        result = discovery_shortfalls(outcomes)
        assert len(result) == 2
        assert result[0]["found"] == 0
        assert result[1]["found"] == 0

    @pytest.mark.unit
    def test_error_gets_stringified(self):
        """Non-None errors are str()-ified in the output."""
        outcomes = [
            {"source_key": "jobspy:a", "status": SOURCE_ERROR, "found": 0, "error": 42},
        ]
        result = discovery_shortfalls(outcomes)
        assert result[0]["error"] == "42"

    @pytest.mark.unit
    def test_none_error_stays_none(self):
        """None error stays None in the output."""
        outcomes = [
            {"source_key": "jobspy:a", "status": SOURCE_EMPTY, "found": 0, "error": None},
        ]
        result = discovery_shortfalls(outcomes)
        assert result[0]["error"] is None

    @pytest.mark.unit
    def test_message_in_output(self):
        """Each shortfall record has a ready-made plain-language message."""
        outcomes = [
            {"source_key": "jobspy:indeed", "status": SOURCE_EMPTY, "found": 0, "error": None},
        ]
        result = discovery_shortfalls(outcomes)
        assert len(result) == 1
        assert "Indeed" in result[0]["message"]
        assert "returned nothing" in result[0]["message"]


# ── prefill_shortfall tests ──────────────────────────────────────────────────


class TestPrefillShortfall:
    """Tests for prefill_shortfall()."""

    @pytest.mark.unit
    def test_full_delivery_returns_none(self):
        """When all fields filled and no failures/deferrals, returns None."""
        result = prefill_shortfall(fields_detected=5, fields_filled=5)
        assert result is None

    @pytest.mark.unit
    def test_full_delivery_with_failed_empty_and_deferred_empty(self):
        """Zero unfilled, empty failed, empty deferred => None."""
        result = prefill_shortfall(
            fields_detected=3,
            fields_filled=3,
            failed_fields=[],
            deferred_questions=[],
        )
        assert result is None

    @pytest.mark.unit
    def test_partial_delivery_returns_record(self):
        """Unfilled fields produce a shortfall record."""
        result = prefill_shortfall(fields_detected=5, fields_filled=3)
        assert result is not None
        assert result["fields_detected"] == 5
        assert result["fields_filled"] == 3
        assert result["fields_unfilled"] == 2

    @pytest.mark.unit
    def test_failed_fields_named(self):
        """Failed fields appear in the failed_fields list with their labels."""
        result = prefill_shortfall(
            fields_detected=3,
            fields_filled=1,
            failed_fields=[
                {"label": "First Name"},
                {"label": "Last Name"},
            ],
        )
        assert result is not None
        assert len(result["failed_fields"]) == 2
        assert "First Name" in result["failed_fields"]
        assert "Last Name" in result["failed_fields"]

    @pytest.mark.unit
    def test_failed_field_with_selector(self):
        """A failed field without a label uses its selector."""
        result = prefill_shortfall(
            fields_detected=2,
            fields_filled=0,
            failed_fields=[
                {"selector": "#first_name"},
            ],
        )
        assert result is not None
        assert "#first_name" in result["failed_fields"]

    @pytest.mark.unit
    def test_failed_field_no_label_no_selector(self):
        """A failed field with neither label nor selector uses the fallback 'a field'."""
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            failed_fields=[{}],
        )
        assert result is not None
        assert result["failed_fields"] == ["a field"]

    @pytest.mark.unit
    def test_non_dict_failed_filtered(self):
        """Non-dict items in failed_fields are filtered out."""
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            failed_fields=[
                {"label": "Email"},
                "not a dict",
                42,
            ],
        )
        assert result is not None
        assert result["failed_fields"] == ["Email"]

    @pytest.mark.unit
    def test_deferred_questions_named(self):
        """Deferred questions appear in deferred_questions list with their labels."""
        result = prefill_shortfall(
            fields_detected=3,
            fields_filled=1,
            deferred_questions=[
                {"label": "Phone"},
            ],
        )
        assert result is not None
        assert len(result["deferred_questions"]) == 1
        assert "Phone" in result["deferred_questions"]

    @pytest.mark.unit
    def test_deferred_question_fallback(self):
        """A deferred question without a label uses fallback 'a question'."""
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            deferred_questions=[{}],
        )
        assert result is not None
        assert result["deferred_questions"] == ["a question"]

    @pytest.mark.unit
    def test_non_dict_deferred_filtered(self):
        """Non-dict items in deferred_questions are filtered out."""
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            deferred_questions=[None, "str", {"label": "Email"}],
        )
        assert result is not None
        assert result["deferred_questions"] == ["Email"]

    @pytest.mark.unit
    def test_summary_contains_counts(self):
        """The summary mentions the field counts."""
        result = prefill_shortfall(fields_detected=5, fields_filled=3)
        assert result is not None
        assert "3" in result["summary"]
        assert "5" in result["summary"]
        assert "double-check" in result["summary"]

    @pytest.mark.unit
    def test_summary_includes_failed(self):
        """The summary lists failed field names."""
        result = prefill_shortfall(
            fields_detected=5,
            fields_filled=3,
            failed_fields=[{"label": "First Name"}],
        )
        assert result is not None
        assert "First Name" in result["summary"]

    @pytest.mark.unit
    def test_summary_includes_deferred(self):
        """The summary mentions deferred questions using singular 'question needs' or plural 'questions need'."""
        # Single deferred
        result1 = prefill_shortfall(
            fields_detected=5,
            fields_filled=3,
            deferred_questions=[{"label": "Phone"}],
        )
        assert result1 is not None
        assert "question needs" in result1["summary"]
        # Multiple deferred
        result2 = prefill_shortfall(
            fields_detected=5,
            fields_filled=3,
            deferred_questions=[{"label": "Phone"}, {"label": "Email"}],
        )
        assert result2 is not None
        assert "questions need" in result2["summary"]

    @pytest.mark.unit
    def test_leftover_blank_counted(self):
        """Leftover (unfilled - failed - deferred) is named as 'left blank'."""
        result = prefill_shortfall(
            fields_detected=10,
            fields_filled=4,
            failed_fields=[{"label": "A"}, {"label": "B"}],
            deferred_questions=[{"label": "C"}],
        )
        assert result is not None
        # unfilled = 6, failed = 2, deferred = 1 => leftover = 3
        assert "3 left blank" in result["summary"]

    @pytest.mark.unit
    def test_no_leftover_when_accounted_for(self):
        """When unfilled == failed + deferred, no 'left blank' count appears."""
        result = prefill_shortfall(
            fields_detected=5,
            fields_filled=3,
            failed_fields=[{"label": "A"}],
            deferred_questions=[{"label": "B"}],
        )
        assert result is not None
        # unfilled = 2, failed = 1, deferred = 1 => leftover = 0
        assert "left blank" not in result["summary"]

    @pytest.mark.unit
    def test_negative_counts_clamped(self):
        """Negative fields_detected/fields_filled are clamped to 0."""
        result = prefill_shortfall(fields_detected=-1, fields_filled=-5)
        # detected = 0, filled = 0, unfilled = 0 => full delivery
        assert result is None

        result2 = prefill_shortfall(fields_detected=5, fields_filled=-1)
        # detected = 5, filled = 0, unfilled = 5 => not None
        assert result2 is not None
        assert result2["fields_detected"] == 5
        assert result2["fields_filled"] == 0
        assert result2["fields_unfilled"] == 5

    @pytest.mark.unit
    def test_max_named_fields_boundary(self):
        """The summary names up to _MAX_NAMED_FIELDS labels, then uses 'and N more'."""
        labels = [f"Field {i}" for i in range(_MAX_NAMED_FIELDS + 2)]
        fields = [{"label": lab} for lab in labels]
        result = prefill_shortfall(
            fields_detected=len(fields),
            fields_filled=0,
            failed_fields=fields,
        )
        assert result is not None
        # _MAX_NAMED_FIELDS shown, plus "and {rest} more"
        for i in range(_MAX_NAMED_FIELDS):
            assert f"Field {i}" in result["summary"]
        assert "and 2 more" in result["summary"]

    @pytest.mark.unit
    def test_less_than_max_named_fields(self):
        """When fewer than _MAX_NAMED_FIELDS, no 'and N more' suffix."""
        fields = [{"label": "Name"}, {"label": "Email"}]
        result = prefill_shortfall(
            fields_detected=2,
            fields_filled=0,
            failed_fields=fields,
        )
        assert result is not None
        assert "more" not in result["summary"]

    @pytest.mark.unit
    def test_exactly_max_named_fields(self):
        """With exactly _MAX_NAMED_FIELDS labels, no 'and N more' suffix."""
        fields = [{"label": f"F{i}"} for i in range(_MAX_NAMED_FIELDS)]
        result = prefill_shortfall(
            fields_detected=_MAX_NAMED_FIELDS,
            fields_filled=0,
            failed_fields=fields,
        )
        assert result is not None
        assert "more" not in result["summary"]

    @pytest.mark.unit
    def test_record_structure(self):
        """The shortfall record has all expected keys."""
        result = prefill_shortfall(
            fields_detected=3,
            fields_filled=1,
            failed_fields=[{"label": "Name"}],
        )
        assert result is not None
        assert set(result.keys()) == {
            "fields_detected",
            "fields_filled",
            "fields_unfilled",
            "failed_fields",
            "deferred_questions",
            "summary",
        }

    @pytest.mark.unit
    def test_empty_labels_combo(self):
        """A case with failed and deferred but zero unfilled leftover works."""
        result = prefill_shortfall(
            fields_detected=5,
            fields_filled=3,
            failed_fields=[{"label": "A"}],
            deferred_questions=[{"label": "B"}],
        )
        assert result is not None
        # unfilled=2, failed=1, deferred=1 => leftover=0 => no "left blank"
        assert "left blank" not in result["summary"]
        assert "A" in result["summary"]
        assert "B" in result["summary"]

    @pytest.mark.unit
    def test_only_deferred_no_failed(self):
        """Deferred questions without any failed fields works."""
        result = prefill_shortfall(
            fields_detected=3,
            fields_filled=3,
            deferred_questions=[{"label": "Consent"}],
        )
        # detected=3, filled=3 => unfilled=0, but deferred exists => record
        assert result is not None
        assert "Consent" in result["summary"]

    @pytest.mark.unit
    def test_only_failed_no_deferred(self):
        """Failed fields without deferred questions works."""
        result = prefill_shortfall(
            fields_detected=5,
            fields_filled=3,
            failed_fields=[{"label": "Phone"}, {"label": "Address"}],
        )
        assert result is not None
        assert "Phone" in result["summary"]
        assert "Address" in result["summary"]
        assert "Double-check" not in result["summary"]  # summary ends with lowercase

    @pytest.mark.unit
    def test_failed_fields_is_copy_not_reference(self):
        """The failed_fields in result is a new list (not the original)."""
        original = [{"label": "Name"}]
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            failed_fields=original,
        )
        assert result is not None
        assert result["failed_fields"] == ["Name"]

    @pytest.mark.unit
    def test_deferred_questions_is_copy_not_reference(self):
        """The deferred_questions in result is a new list (not the original)."""
        original = [{"label": "Q1"}]
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            deferred_questions=original,
        )
        assert result is not None
        assert result["deferred_questions"] == ["Q1"]

    @pytest.mark.unit
    def test_float_inputs_converted(self):
        """Float inputs for fields_detected/filled are truncated to int."""
        result = prefill_shortfall(fields_detected=5.7, fields_filled=3.2)
        assert result is not None
        assert result["fields_detected"] == 5
        assert result["fields_filled"] == 3

    @pytest.mark.unit
    def test_deferred_with_selector_fallback(self):
        """Deferred question selector is used when label is missing."""
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            deferred_questions=[{"selector": "#phone"}],
        )
        assert result is not None
        assert "#phone" in str(result["deferred_questions"])

    @pytest.mark.unit
    def test_empty_labels_empty_selector(self):
        """Empty label and empty selector fall through to fallback."""
        result = prefill_shortfall(
            fields_detected=1,
            fields_filled=0,
            failed_fields=[{"label": "", "selector": ""}],
        )
        assert result is not None
        assert result["failed_fields"] == ["a field"]
