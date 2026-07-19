"""Unit tests for RejectionService — rejection classifier (AZ0-107)."""

from __future__ import annotations

import pytest

from applicant.application.services.rejection_service import RejectionService


# ---------------------------------------------------------------------------
# Parallel safety (xdist): no caches to clear; pure stateless module.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """xdist parallel-safety: no-op for pure stateless module."""
    pass


# ===================================================================
# classify_message
# ===================================================================


class TestClassifyMessage:
    """Tests for ``RejectionService.classify_message``."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # ----- normal rejection phrases -----
            ("we have decided not to proceed with your application", "rejected"),
            ("we regret to inform you that your application is not selected", "rejected"),
            ("the position has been filled", "rejected"),
            ("we will not be moving forward with your application", "rejected"),
            # ----- case insensitivity -----
            ("WE REGRET TO INFORM YOU", "rejected"),
            ("We Have Decided Not To Proceed", "rejected"),
            # ----- partial match within larger body -----
            ("Thank you for applying. We regret to inform you that the role is closed.", "rejected"),
            (
                "After careful review, we have decided not to proceed "
                "with your candidacy at this time.",
                "rejected",
            ),
            # ----- non-rejection phrases -----
            ("thank you for your application", None),
            ("we look forward to speaking with you", None),
            ("congratulations, you have been shortlisted", None),
            # ----- empty / blank -----
            ("", None),
            ("   ", None),
            # ----- None -----
            (None, None),
        ],
    )
    def test_classify_message(
        self, text: str | None, expected: str | None
    ) -> None:
        assert RejectionService.classify_message(text) == expected


# ===================================================================
# classify_status_page
# ===================================================================


class TestClassifyStatusPage:
    """Tests for ``RejectionService.classify_status_page``."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            # ----- normal rejection status phrases -----
            ("no longer under consideration", "rejected"),
            ("not selected", "rejected"),
            ("application closed", "rejected"),
            ("position filled", "rejected"),
            ("not moving forward", "rejected"),
            ("candidate withdrawn", "rejected"),
            ("rejected", "rejected"),
            ("declined", "rejected"),
            # ----- case insensitivity -----
            ("NO LONGER UNDER CONSIDERATION", "rejected"),
            ("Application Closed", "rejected"),
            # ----- partial match -----
            ("Status: No longer under consideration as of today", "rejected"),
            ("Your application has been rejected on 2024-01-15", "rejected"),
            # ----- non-rejection phrases -----
            ("in progress", None),
            ("under review", None),
            ("interview scheduled", None),
            # ----- empty / blank -----
            ("", None),
            ("   ", None),
            # ----- None -----
            (None, None),
        ],
    )
    def test_classify_status_page(
        self, text: str | None, expected: str | None
    ) -> None:
        assert RejectionService.classify_status_page(text) == expected


# ===================================================================
# is_rejection
# ===================================================================


class TestIsRejection:
    """Tests for ``RejectionService.is_rejection``."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("outcome", "expected"),
        [
            ("rejected", True),
            ("submitted", False),
            ("converted", False),
            ("interview_invited", False),
            ("ghosted", False),
            ("offer", False),
            ("unknown", False),
            ("", False),
            (None, False),
        ],
    )
    def test_is_rejection(self, outcome: str | None, expected: bool) -> None:
        assert RejectionService.is_rejection(outcome) is expected
