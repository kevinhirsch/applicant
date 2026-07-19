"""Parallel-safe unit tests for HumanHandoffAdapter (AZ0-116)."""

from __future__ import annotations

import pytest

from applicant.adapters.captcha.human_handoff import HumanHandoffAdapter
from applicant.ports.driven.captcha import (
    CaptchaContext,
    CaptchaDisposition,
    CaptchaKind,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """xdist parallel-execution isolation — HumanHandoffAdapter has no cache."""


class TestHumanHandoffAdapter:
    """Verify HumanHandoffAdapter always classifies as HANDOFF."""

    @staticmethod
    def _context(**overrides) -> CaptchaContext:
        return CaptchaContext(
            url=overrides.get("url", "https://example.com/login"),
            kind=overrides.get("kind", CaptchaKind.RECAPTCHA_V2),
            site_key=overrides.get("site_key", "6Lc..."),
        )

    def test_classify_always_handoff(self) -> None:
        adapter = HumanHandoffAdapter()
        for ctx in [
            self._context(),
            self._context(url="https://other.com", kind=CaptchaKind.UNKNOWN),
            self._context(kind=CaptchaKind.TURNSTILE, site_key=""),
            self._context(kind=CaptchaKind.HCAPTCHA, site_key="xxx"),
        ]:
            assert adapter.classify(ctx) is CaptchaDisposition.HANDOFF

    def test_resolve_returns_handoff_not_solved(self) -> None:
        adapter = HumanHandoffAdapter()
        outcome = adapter.resolve(self._context())
        assert outcome.disposition is CaptchaDisposition.HANDOFF
        assert outcome.solved is False
        assert "handed off" in outcome.detail.lower()

    def test_resolve_detail_descriptive(self) -> None:
        adapter = HumanHandoffAdapter()
        outcome = adapter.resolve(self._context())
        assert len(outcome.detail) > 10
        assert "operator" in outcome.detail.lower() or "handoff" in outcome.detail.lower()
