"""Unit tests for applicant.core.rules.freshness (posting-date display rule)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from applicant.core.rules.freshness import STALE_AFTER_DAYS, posting_freshness

_NOW = datetime(2026, 8, 10, tzinfo=UTC)


@pytest.mark.unit
class TestPostingFreshness:
    """Tests for posting_freshness()."""

    def test_both_timestamps_absent_returns_none(self):
        """No date_posted, no first_seen (legacy row) -> None, never a fabricated dict."""
        assert posting_freshness(None, None, now=_NOW) is None

    def test_prefers_real_posted_date_over_first_seen(self):
        """When both are present, the board-reported date_posted wins and is
        honestly labeled 'Posted' (never silently substituted for first_seen)."""
        posted = _NOW - timedelta(days=3)
        seen = _NOW - timedelta(days=10)
        result = posting_freshness(posted, seen, now=_NOW)
        assert result["posted_label"] == "Posted"
        assert result["posted_date"] == posted.isoformat()
        assert result["posted_relative"] == "3 days ago"
        assert result["posted_stale"] is False

    def test_falls_back_to_first_seen_and_labels_it_honestly(self):
        """No real posted date -> uses first_seen but labels it 'First seen', never
        'Posted', so the UI never implies a posted date the engine doesn't have."""
        seen = _NOW - timedelta(days=5)
        result = posting_freshness(None, seen, now=_NOW)
        assert result["posted_label"] == "First seen"
        assert result["posted_date"] == seen.isoformat()
        assert result["posted_relative"] == "5 days ago"

    def test_today_reads_as_today_not_zero_days_ago(self):
        result = posting_freshness(_NOW - timedelta(hours=2), None, now=_NOW)
        assert result["posted_relative"] == "today"
        assert result["posted_stale"] is False

    def test_one_day_ago_is_singular(self):
        result = posting_freshness(_NOW - timedelta(days=1), None, now=_NOW)
        assert result["posted_relative"] == "1 day ago"

    def test_exactly_at_stale_threshold_is_not_yet_stale(self):
        result = posting_freshness(_NOW - timedelta(days=STALE_AFTER_DAYS), None, now=_NOW)
        assert result["posted_stale"] is False

    def test_one_day_past_stale_threshold_is_stale(self):
        result = posting_freshness(_NOW - timedelta(days=STALE_AFTER_DAYS + 1), None, now=_NOW)
        assert result["posted_stale"] is True

    def test_coarsens_to_months_then_years(self):
        assert posting_freshness(_NOW - timedelta(days=40), None, now=_NOW)[
            "posted_relative"
        ] == "1 month ago"
        assert posting_freshness(_NOW - timedelta(days=400), None, now=_NOW)[
            "posted_relative"
        ] == "1 year ago"

    def test_future_date_clamps_to_today_not_negative(self):
        """Clock skew / a bad scraped date in the future must never render
        a nonsensical negative age."""
        result = posting_freshness(_NOW + timedelta(days=5), None, now=_NOW)
        assert result["posted_relative"] == "today"
        assert result["posted_stale"] is False

    def test_naive_datetimes_are_treated_as_utc(self):
        """Storage can hand back naive datetimes; the rule must not raise
        comparing naive vs aware."""
        naive_posted = datetime(2026, 8, 7)
        result = posting_freshness(naive_posted, None, now=_NOW)
        assert result["posted_relative"] == "3 days ago"
