"""Tests for CaptchaSolverPort stub adapter (#350)."""

from __future__ import annotations

from applicant.adapters.captcha.stub_solver import StubCaptchaSolver
from applicant.ports.driven.captcha_solver import CaptchaKind, SolveStrategy


class TestDetect:
    def test_detects_recaptcha(self):
        solver = StubCaptchaSolver()
        html = '<script src="https://www.google.com/recaptcha/api.js"></script>'
        detections = solver.detect(html)
        assert len(detections) >= 1
        assert any(d["kind"] == CaptchaKind.RECAPTCHA_V2 for d in detections)

    def test_detects_hcaptcha(self):
        solver = StubCaptchaSolver()
        html = '<script src="https://hcaptcha.com/1/api.js"></script>'
        detections = solver.detect(html)
        assert any(d["kind"] == CaptchaKind.HCAPTCHA for d in detections)

    def test_detects_turnstile(self):
        solver = StubCaptchaSolver()
        html = '<div id="cf-turnstile"></div>'
        detections = solver.detect(html)
        assert any(d["kind"] == CaptchaKind.TURNSTILE for d in detections)

    def test_returns_empty_for_clean_page(self):
        solver = StubCaptchaSolver()
        html = "<html><body>No CAPTCHA here</body></html>"
        assert solver.detect(html) == []


class TestSelectStrategy:
    def test_handoff_when_detected(self):
        solver = StubCaptchaSolver()
        detections = [{"kind": CaptchaKind.RECAPTCHA_V2, "selector": None, "confidence": 0.8}]
        assert solver.select_strategy(detections) == SolveStrategy.HANDOFF

    def test_avoid_when_no_detection(self):
        solver = StubCaptchaSolver()
        assert solver.select_strategy([]) == SolveStrategy.AVOID


class TestAvoidance:
    def test_avoidance_returns_false(self):
        solver = StubCaptchaSolver()
        assert solver.attempt_avoidance("https://example.com") is False


class TestHandoff:
    def test_handoff_succeeds(self):
        solver = StubCaptchaSolver()
        ok = solver.request_human_handoff("c-1", "a-1", {"url": "https://example.com"})
        assert ok is True
