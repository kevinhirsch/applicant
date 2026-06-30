"""Stub CaptchaSolverPort adapter — behavioral-avoidance + handoff only.

This is the default adapter used when no live solver service is configured.
It implements AVOID and HANDOFF strategies; SOLVE_AUTO always returns False.
Live solving requires API keys (Claude/user adds that adapter).
"""

from __future__ import annotations

from typing import Any

from applicant.observability.logging import get_logger
from applicant.ports.driven.captcha_solver import CaptchaKind, SolveStrategy

log = get_logger(__name__)


class StubCaptchaSolver:
    """Stub solver that only handles avoid/handoff strategies."""

    def detect(self, page_source: str) -> list[dict[str, Any]]:
        detections: list[dict[str, Any]] = []
        markers: list[tuple[str, CaptchaKind]] = [
            ("recaptcha/api", CaptchaKind.RECAPTCHA_V2),
            ("hcaptcha.com", CaptchaKind.HCAPTCHA),
            ("cf-turnstile", CaptchaKind.TURNSTILE),
            ("funcaptcha", CaptchaKind.FUNCAPTCHA),
            ("data-sitekey", CaptchaKind.RECAPTCHA_V2),
        ]
        for marker, kind in markers:
            if marker in page_source.lower():
                detections.append({"kind": kind, "selector": None, "confidence": 0.8})
        return detections

    def select_strategy(self, detections: list[dict[str, Any]]) -> SolveStrategy:
        if not detections:
            return SolveStrategy.AVOID
        return SolveStrategy.HANDOFF

    def attempt_avoidance(self, url: str, context: dict[str, Any] | None = None) -> bool:
        log.info("captcha_avoidance_attempted", url=url)
        return False

    def request_human_handoff(
        self, campaign_id: str, application_id: str, details: dict[str, Any]
    ) -> bool:
        log.info("captcha_handoff_requested", campaign=campaign_id, app=application_id)
        return True
