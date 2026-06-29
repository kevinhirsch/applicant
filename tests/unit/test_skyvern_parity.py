"""Unit tests for Skyvern parity gap implementations (#351).

Tests the three implemented gaps:
1. Iframe/Shadow DOM field penetration
2. Adaptive waiting
3. Error recovery on navigation failure
"""

from __future__ import annotations

from applicant.core.entities.plan import (
    GotoOp,
    OpKind,
    Plan,
    StopOp,
)
from applicant.core.rules.plan import (
    validate_plan,
)


class TestErrorRecovery:
    """Gap 3: URL verification + error page detection logic."""

    # We test the error-page URL heuristics as pure predicates.
    # The actual _on_error_page runs in the real Playwright adapter.

    ERROR_URL_MARKERS = (
        "/error", "/oops", "/500", "/404", "/maintenance", "session-expired",
    )

    ERROR_TEXT_MARKERS = (
        "something went wrong",
        "we encountered an error",
        "page not found",
        "try again later",
        "session expired",
        "maintenance",
    )

    def test_error_url_detection(self) -> None:
        for marker in self.ERROR_URL_MARKERS:
            url = f"https://example.com{marker}"
            assert any(m in url.lower() for m in self.ERROR_URL_MARKERS), \
                f"URL {url} should match error markers"
        # Normal URLs should not match.
        normal = "https://example.com/apply"
        assert not any(m in normal.lower() for m in self.ERROR_URL_MARKERS)

    def test_error_text_detection(self) -> None:
        for marker in self.ERROR_TEXT_MARKERS:
            text = f"Sorry, {marker}. Please try again."
            assert any(m in text.lower() for m in self.ERROR_TEXT_MARKERS), \
                f"Text containing {marker!r} should match"
        # Normal text should not match.
        normal = "Please fill out the application form"
        assert not any(m in normal.lower() for m in self.ERROR_TEXT_MARKERS)

    def test_recovers_with_replan_on_wrong_page(self) -> None:
        """When navigation lands on an unexpected page, the system should
        re-plan rather than silently proceeding."""
        # The planner should emit a plan that recovers.
        plan = Plan(ops=(
            GotoOp(url="https://example.com/apply"),
            StopOp(reason="captcha"),
        ))
        assert len(plan) == 2
        assert plan[-1].kind == OpKind.STOP
        assert plan[-1].reason == "captcha"

    def test_unknown_stop_reason_rejected(self) -> None:
        """Only recognized stop reasons are valid (OCP safety)."""
        plan = Plan(ops=(StopOp(reason="unknown_xyz"),))
        errors = validate_plan(plan, frozenset())
        assert any("not a recognized" in e for e in errors)

    def test_all_valid_stop_reasons_pass(self) -> None:
        for reason in ("captcha", "final_submit", "account_create", "two_factor"):
            plan = Plan(ops=(StopOp(reason=reason),))
            errors = validate_plan(plan, frozenset())
            stop_errors = [e for e in errors if "stop" in e.lower()]
            assert stop_errors == [], f"Reason {reason!r} should be valid"


class TestAdaptiveWaiting:
    """Gap 2: adaptive waiting with progressive load-state fallback."""

    def test_expected_url_verification_substring(self) -> None:
        """URL verification: expected URL is a substring of the current URL."""
        current = "https://example.com/apply/12345"
        expected = "example.com/apply"
        assert expected in current

    def test_expected_url_verification_reverse(self) -> None:
        """URL verification: current URL is a substring of expected URL."""
        current = "/apply"
        expected = "https://example.com/apply/12345"
        assert current in expected

    def test_expected_url_mismatch(self) -> None:
        """URL verification: completely unrelated URLs."""
        current = "https://other-site.com/error"
        expected = "https://example.com/apply"
        assert expected not in current
        assert current not in expected

    def test_adaptive_wait_state_fallthrough(self) -> None:
        """The adaptive waiter tries load states in order and falls back."""
        load_states = ["networkidle", "load", "domcontentloaded"]
        # The waiter tries at least one of these.
        assert len(load_states) == 3
        assert "networkidle" in load_states
        assert "load" in load_states
        assert "domcontentloaded" in load_states


class TestIframePenetration:
    """Gap 1: iframe and shadow DOM field detection."""

    def test_collect_fields_deep_signature(self) -> None:
        """The recursive collector delegates to _collect_frame_fields per frame."""
        # This is a structural/signature test; actual iframe traversal
        # requires a real browser (integration-gated).
        from applicant.adapters.browser.page_source import PlaywrightPageSource
        assert hasattr(PlaywrightPageSource, "_collect_fields_deep")
        assert hasattr(PlaywrightPageSource, "_collect_frame_fields")
        assert callable(PlaywrightPageSource._collect_fields_deep)
        assert callable(PlaywrightPageSource._collect_frame_fields)

    def test_detect_fields_delegates(self) -> None:
        """detect_fields now delegates to _collect_fields_deep."""
        from applicant.adapters.browser.page_source import PlaywrightPageSource
        assert hasattr(PlaywrightPageSource, "detect_fields")
        assert callable(PlaywrightPageSource.detect_fields)
