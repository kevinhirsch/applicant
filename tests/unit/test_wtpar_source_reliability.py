"""WTPAR-2 — Source reliability scoring module.

Pure, deterministic tests for the source-reliability scoring functions in
``src/applicant/core/rules/source_reliability.py``. No IO, no network —
all inputs are inline dicts and strings.
"""

from __future__ import annotations

import pytest

from applicant.core.rules.source_reliability import (
    SOURCE_TIERS,
    reliability_detail,
    reliability_label,
    reliability_score,
    reliability_tier,
    source_reliability,
)


class TestReliabilityTier:
    """Test reliability_tier for every source key prefix."""

    def test_sample_is_high(self):
        assert reliability_tier("sample") == "high"

    def test_jobspy_linkedin_is_medium(self):
        assert reliability_tier("jobspy:linkedin") == "medium"

    def test_jobspy_indeed_is_medium(self):
        assert reliability_tier("jobspy:indeed") == "medium"

    def test_jobspy_glassdoor_is_medium(self):
        assert reliability_tier("jobspy:glassdoor") == "medium"

    def test_jobspy_google_is_medium(self):
        assert reliability_tier("jobspy:google") == "medium"

    def test_jobspy_zip_recruiter_is_medium(self):
        assert reliability_tier("jobspy:zip_recruiter") == "medium"

    def test_searxng_is_medium(self):
        assert reliability_tier("searxng") == "medium"

    def test_rss_hn_hiring_is_medium(self):
        assert reliability_tier("rss:hn-hiring") == "medium"

    def test_rss_custom_is_medium(self):
        assert reliability_tier("rss:custom-1") == "medium"

    def test_unknown_is_medium(self):
        assert reliability_tier("unknown_source") == "medium"

    def test_empty_string_is_medium(self):
        assert reliability_tier("") == "medium"

    def test_colon_prefixed_key(self):
        assert reliability_tier(":weird") == "medium"


class TestReliabilityScore:
    """Test reliability_score with yield_stats and tier baselines."""

    # --- status-based scores ---

    def test_status_ok(self):
        stats = {"last_run": {"at": "2024-01-01", "status": "ok", "found": 5}}
        assert reliability_score("jobspy:indeed", stats) == 1.0

    def test_status_empty(self):
        stats = {"last_run": {"at": "2024-01-01", "status": "empty", "found": 0}}
        assert reliability_score("jobspy:indeed", stats) == 0.5

    def test_status_rate_limited(self):
        stats = {"last_run": {"at": "2024-01-01", "status": "rate_limited", "found": 0}}
        assert reliability_score("jobspy:indeed", stats) == 0.3

    def test_status_error(self):
        stats = {"last_run": {"at": "2024-01-01", "status": "error", "found": 0}}
        assert reliability_score("jobspy:indeed", stats) == 0.0

    def test_unknown_status_falls_back_to_tier_baseline(self):
        stats = {"last_run": {"at": "2024-01-01", "status": "unknown_status"}}
        assert reliability_score("jobspy:indeed", stats) == 0.75

    # --- tier baselines (no yield_stats) ---

    def test_sample_baseline(self):
        assert reliability_score("sample") == 1.0

    def test_jobspy_baseline(self):
        assert reliability_score("jobspy:indeed") == 0.75

    def test_searxng_baseline(self):
        assert reliability_score("searxng") == 0.75

    def test_rss_baseline(self):
        assert reliability_score("rss:hn-hiring") == 0.75

    # --- edge cases ---

    def test_none_yield_stats(self):
        assert reliability_score("jobspy:indeed", None) == 0.75

    def test_empty_yield_stats_dict(self):
        assert reliability_score("jobspy:indeed", {}) == 0.75

    def test_yield_stats_without_last_run(self):
        assert reliability_score("jobspy:indeed", {"other_key": 1}) == 0.75

    def test_yield_stats_non_dict(self):
        assert reliability_score("jobspy:indeed", "not_a_dict") == 0.75

    def test_last_run_non_dict(self):
        assert reliability_score("jobspy:indeed", {"last_run": "not_a_dict"}) == 0.75


class TestReliabilityLabel:
    """Test reliability_label thresholds."""

    def test_high_label_for_ok_status(self):
        stats = {"last_run": {"status": "ok"}}
        assert reliability_label("jobspy:indeed", stats) == "High"

    def test_high_label_for_sample(self):
        assert reliability_label("sample") == "High"

    def test_medium_label_for_empty_status(self):
        stats = {"last_run": {"status": "empty"}}
        assert reliability_label("jobspy:indeed", stats) == "Medium"

    def test_medium_label_for_medium_baseline(self):
        assert reliability_label("jobspy:indeed") == "Medium"

    def test_low_label_for_error_status(self):
        stats = {"last_run": {"status": "error"}}
        assert reliability_label("jobspy:indeed", stats) == "Low"

    def test_low_label_for_rate_limited(self):
        stats = {"last_run": {"status": "rate_limited"}}
        assert reliability_label("jobspy:indeed", stats) == "Low"


class TestReliabilityDetail:
    """Test reliability_detail for each source type and error appending."""

    def test_sample_detail(self):
        assert "In-process data source" in reliability_detail("sample")

    def test_jobspy_detail(self):
        assert "Network-backed source" in reliability_detail("jobspy:indeed")

    def test_searxng_detail(self):
        assert "Metasearch source" in reliability_detail("searxng")

    def test_rss_detail(self):
        assert "RSS feed source" in reliability_detail("rss:hn-hiring")

    def test_unknown_detail(self):
        assert "Unknown source type" in reliability_detail("unknown_source")

    def test_empty_key_detail(self):
        assert "Unknown source type" in reliability_detail("")

    def test_error_appends_shortfall(self):
        stats = {"last_run": {"status": "error", "error": "timeout"}}
        detail = reliability_detail("jobspy:indeed", stats)
        assert "Network-backed source" in detail
        assert "could not be searched" in detail

    def test_empty_appends_shortfall(self):
        stats = {"last_run": {"status": "empty"}}
        detail = reliability_detail("jobspy:indeed", stats)
        assert "returned nothing" in detail

    def test_rate_limited_appends_shortfall(self):
        stats = {"last_run": {"status": "rate_limited"}}
        detail = reliability_detail("jobspy:indeed", stats)
        assert "skipped" in detail

    def test_ok_status_no_shortfall_appended(self):
        stats = {"last_run": {"status": "ok"}}
        detail = reliability_detail("jobspy:indeed", stats)
        assert "—" not in detail or detail.count("—") == 0


class TestSourceReliability:
    """Test source_reliability returns a complete dict with all expected keys."""

    def test_returns_all_keys(self):
        result = source_reliability("jobspy:indeed")
        expected_keys = {"source_key", "tier", "score", "label", "detail"}
        assert set(result.keys()) == expected_keys

    def test_aggregates_values_correctly(self):
        result = source_reliability("sample")
        assert result["source_key"] == "sample"
        assert result["tier"] == "high"
        assert result["score"] == 1.0
        assert result["label"] == "High"
        assert "In-process data source" in result["detail"]

    def test_with_error_stats(self):
        stats = {"last_run": {"status": "error", "error": "connection refused"}}
        result = source_reliability("jobspy:linkedin", stats)
        assert result["source_key"] == "jobspy:linkedin"
        assert result["tier"] == "medium"
        assert result["score"] == 0.0
        assert result["label"] == "Low"
        assert "could not be searched" in result["detail"]

    def test_empty_source_key(self):
        result = source_reliability("")
        assert result["source_key"] == ""
        assert result["tier"] == "medium"
        assert result["score"] == 0.75
        assert result["label"] == "Medium"

    def test_unknown_source_key(self):
        result = source_reliability("new_source")
        assert result["tier"] == "medium"
        assert result["score"] == 0.75

    def test_malformed_yield_stats(self):
        result = source_reliability("jobspy:indeed", "not_a_dict")
        assert result["score"] == 0.75

    def test_none_yield_stats(self):
        result = source_reliability("jobspy:indeed", None)
        assert result["score"] == 0.75


class TestSourceTiersDict:
    """Verify SOURCE_TIERS has the expected entries."""

    def test_has_sample(self):
        assert "sample" in SOURCE_TIERS
        assert SOURCE_TIERS["sample"] == "high"

    def test_has_jobspy(self):
        assert "jobspy" in SOURCE_TIERS
        assert SOURCE_TIERS["jobspy"] == "medium"

    def test_has_searxng(self):
        assert "searxng" in SOURCE_TIERS
        assert SOURCE_TIERS["searxng"] == "medium"

    def test_has_rss(self):
        assert "rss" in SOURCE_TIERS
        assert SOURCE_TIERS["rss"] == "medium"
