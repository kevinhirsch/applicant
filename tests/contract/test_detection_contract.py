"""DetectionMonitor contract against the DetectionMonitor adapter (FR-PREFILL-6).

Asserts the behavioral contract: detection signals (CAPTCHA/Turnstile,
Cloudflare/DataDome, 403/429, anomalous redirects) classify into a DetectionEvent;
clean pages return None; the monitor NEVER solves a challenge (it only signals).
"""

from __future__ import annotations

import pytest

from applicant.adapters.detection.detection_monitor import DetectionMonitor, classify_signals
from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.ids import ApplicationId, new_id
from applicant.ports.driven.detection_monitor import DetectionMonitorPort


@pytest.mark.contract
class TestDetectionMonitorContract:
    @pytest.fixture
    def adapter(self) -> DetectionMonitor:
        return DetectionMonitor()

    @pytest.fixture
    def aid(self) -> ApplicationId:
        return ApplicationId(new_id())

    def test_satisfies_port_protocol(self, adapter):
        assert isinstance(adapter, DetectionMonitorPort)

    def test_clean_page_returns_none(self, adapter, aid):
        assert adapter.evaluate(aid, {"status": 200, "body": "welcome"}) is None

    @pytest.mark.parametrize(
        "signals,expected",
        [
            ({"signals": ("turnstile",)}, "turnstile"),
            ({"body": "Please complete the CAPTCHA"}, "captcha"),
            ({"body": "Checking your browser before accessing"}, "cloudflare"),
            ({"signals": ("datadome",)}, "datadome"),
            ({"status": 429}, "rate_limited"),
            ({"status": 403}, "blocked_403"),
            ({"body": "Too many attempts, please try again later"}, "account_friction"),
            ({"body": "Your account is temporarily locked"}, "account_friction"),
        ],
    )
    def test_known_signals_classified(self, adapter, aid, signals, expected):
        event = adapter.evaluate(aid, signals)
        assert isinstance(event, DetectionEvent)
        assert event.signal_type == expected
        assert event.application_id == aid

    def test_anomalous_redirect_detected(self, adapter, aid):
        event = adapter.evaluate(
            aid, {"url": "https://phish.example/login", "expected_host": "acme.workday"}
        )
        assert event is not None and event.signal_type == "anomalous_redirect"

    def test_classify_is_pure_helper(self):
        assert classify_signals({"status": 200}) is None
        assert classify_signals({"signals": ("hCaptcha",)}) == "captcha"

    def test_embedded_widget_script_in_body_is_not_a_challenge(self):
        # REGRESSION (live PwC playtest): a bare reCAPTCHA token in the page markup
        # (an invisible, embedded script) is NOT a challenge — only the adapter's
        # visibility-vetted ``signals`` tuple flags a widget. Otherwise the engine
        # would hand off on essentially every modern login page (automate-by-default).
        assert classify_signals({"body": "grecaptcha.render(...)", "status": 200}) is None
        assert classify_signals(
            {"body": "<script src='/recaptcha/api.js'></script>", "status": 200}
        ) is None
        # But the adapter-vetted explicit signal still classifies.
        assert classify_signals({"signals": ("recaptcha",)}) == "captcha"

    def test_event_detail_never_includes_raw_body(self, adapter, aid):
        # Body can contain a challenge phrase; the event detail must not carry it.
        event = adapter.evaluate(aid, {"body": "Please complete the CAPTCHA", "status": 200})
        assert event is not None
        assert "body" not in event.detail
