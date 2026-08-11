import pytest

from applicant.adapters.detection.detection_monitor import classify_signals, DetectionMonitor
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.ids import ApplicationId, DetectionEventId


@pytest.fixture(autouse=True)
def _xdist_safe() -> None:
    """Module-level autouse fixture for safe parallel execution with pytest-xdist."""
    return None


class TestClassifySignals:
    """classify_signals() — returns a normalized signal type or None."""

    @pytest.mark.unit
    def test_blocking_status_403(self):
        result = classify_signals({"status": 403})
        assert result == "blocked_403"

    @pytest.mark.unit
    def test_blocking_status_429(self):
        result = classify_signals({"status": 429})
        assert result == "rate_limited"

    @pytest.mark.unit
    def test_widget_signal_recaptcha(self):
        result = classify_signals({"signals": ("recaptcha",)})
        assert result == "captcha"

    @pytest.mark.unit
    def test_widget_signal_turnstile(self):
        result = classify_signals({"signals": ("turnstile",)})
        assert result == "turnstile"

    @pytest.mark.unit
    def test_widget_signal_datadome(self):
        result = classify_signals({"signals": ("datadome",)})
        assert result == "datadome"

    @pytest.mark.unit
    def test_interstitial_marker_in_body(self):
        result = classify_signals({"body": "Checking your browser before accessing the site."})
        assert result == "cloudflare"

    @pytest.mark.unit
    def test_interstitial_marker_are_you_a_robot(self):
        result = classify_signals({"body": "Are you a robot? Please verify."})
        assert result == "captcha"

    @pytest.mark.unit
    def test_friction_marker_too_many_attempts(self):
        result = classify_signals({"body": "Too many attempts. Please try again later."})
        assert result == "account_friction"

    @pytest.mark.unit
    def test_anomalous_redirect(self):
        result = classify_signals({
            "url": "https://challenge.example.com/cdn-cgi/",
            "expected_host": "jobs.example.com",
        })
        assert result == "anomalous_redirect"

    @pytest.mark.unit
    def test_anomalous_redirect_case_insensitive(self):
        result = classify_signals({
            "url": "https://CHALLENGE.EXAMPLE.COM/cdn-cgi/",
            "expected_host": "Jobs.Example.Com",
        })
        assert result == "anomalous_redirect"

    @pytest.mark.unit
    def test_no_detection_when_none_match(self):
        result = classify_signals({
            "status": 200,
            "body": "Welcome to the application portal",
            "signals": (),
            "url": "https://jobs.example.com/apply",
            "expected_host": "jobs.example.com",
        })
        assert result is None

    @pytest.mark.unit
    def test_empty_signals_dict_returns_none(self):
        result = classify_signals({})
        assert result is None

    @pytest.mark.unit
    def test_missing_keys_gracefully_handled(self):
        result = classify_signals({"status": 200, "body": ""})
        assert result is None

    @pytest.mark.unit
    def test_signals_used_not_raw_body_for_widget(self):
        """Widget signal NOT in explicit signals tuple, but recaptcha mentioned
        only in raw body — should NOT trigger a detection per the module's docstring."""
        result = classify_signals({
            "body": "This page has a recaptcha script embedded",
            "signals": (),
        })
        assert result is None

    @pytest.mark.unit
    def test_interstitial_via_signals_fallback(self):
        """Interstitial markers also work when present in the signals string (lowered)."""
        result = classify_signals({
            "signals": ("attention required",),
        })
        assert result == "cloudflare"

    @pytest.mark.unit
    def test_status_403_takes_precedence_over_body_markers(self):
        """Status 403 should be detected even when body contains safe text."""
        result = classify_signals({
            "status": 403,
            "body": "Welcome to the portal",
        })
        assert result == "blocked_403"


class TestDetectionMonitorEvaluate:
    """DetectionMonitor.evaluate() — returns DetectionEvent or None."""

    @pytest.mark.unit
    def test_returns_detection_event_on_blocking_status(self):
        app_id = ApplicationId("app-1")
        monitor = DetectionMonitor()
        result = monitor.evaluate(app_id, {"status": 403})
        assert isinstance(result, DetectionEvent)
        assert result.application_id == app_id
        assert result.signal_type == "blocked_403"

    @pytest.mark.unit
    def test_returns_none_when_no_detection(self):
        app_id = ApplicationId("app-2")
        monitor = DetectionMonitor()
        result = monitor.evaluate(app_id, {"status": 200, "body": "all good"})
        assert result is None

    @pytest.mark.unit
    def test_detection_event_has_correct_fields(self):
        app_id = ApplicationId("app-3")
        monitor = DetectionMonitor()
        result = monitor.evaluate(app_id, {
            "status": 429,
            "body": "too many",
            "url": "https://example.com/rate-limited",
        })
        assert isinstance(result, DetectionEvent)
        assert isinstance(result.id, str)
        assert len(result.id) > 0
        assert result.application_id == app_id
        assert result.signal_type == "rate_limited"
        # detail should NOT include 'body'
        assert "body" not in result.detail
        assert result.detail.get("status") == 429
        assert result.detail.get("url") == "https://example.com/rate-limited"

    @pytest.mark.unit
    def test_detection_event_detail_excludes_body(self):
        app_id = ApplicationId("app-4")
        monitor = DetectionMonitor()
        result = monitor.evaluate(app_id, {
            "status": 200,
            "body": "checking your browser",
            "url": "https://challenge.example.com",
            "expected_host": "jobs.example.com",
            "signals": (),
        })
        assert result is not None
        assert result.signal_type == "cloudflare"
        assert "body" not in result.detail
        assert result.detail.get("url") == "https://challenge.example.com"
        assert result.detail.get("expected_host") == "jobs.example.com"

    @pytest.mark.unit
    def test_detection_event_with_widget_signal(self):
        app_id = ApplicationId("app-5")
        monitor = DetectionMonitor()
        result = monitor.evaluate(app_id, {
            "signals": ("turnstile",),
        })
        assert isinstance(result, DetectionEvent)
        assert result.signal_type == "turnstile"
        assert result.detail.get("signals") == ("turnstile",)

