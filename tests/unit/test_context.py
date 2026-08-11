"""Tests for captcha family + site-key detection (issue #350).

Verifies that the regex-based sniffing in
``src/applicant/adapters/captcha/context.py`` correctly classifies hCaptcha,
Turnstile, reCAPTCHA v2, reCAPTCHA v3, and unknown captchas; that the site-key
extractor handles both ``data-sitekey`` and ``render`` query-param patterns;
and that ``build_captcha_context`` degrades safely when state lacks a ``body``.
"""

from __future__ import annotations

import dataclasses

import pytest

from applicant.adapters.captcha.context import (
    _detect_kind,
    _detect_site_key,
    build_captcha_context,
)
from applicant.ports.driven.captcha import CaptchaContext, CaptchaKind


@pytest.fixture(autouse=True)
def _no_state_leak():
    """No module-level state to clear; present for parallel xdist safety."""
    pass


class TestDetectKind:
    """_detect_kind() classification (order-sensitive: hCaptcha wins first)."""

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("<div class='h-captcha' data-sitekey='x'></div>", CaptchaKind.HCAPTCHA),
            ("<script src='https://hcaptcha.com/1/api.js'></script>", CaptchaKind.HCAPTCHA),
            ("<div class='cf-turnstile' data-sitekey='x'></div>", CaptchaKind.TURNSTILE),
            ("https://challenges.cloudflare.com/turnstile/v0/api.js", CaptchaKind.TURNSTILE),
            ("<div class='g-recaptcha' data-sitekey='x'></div>", CaptchaKind.RECAPTCHA_V2),
            ("<script src='https://www.google.com/recaptcha/api.js'></script>", CaptchaKind.RECAPTCHA_V2),
            ("<script src='https://www.google.com/recaptcha/api.js?render=6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'></script>", CaptchaKind.RECAPTCHA_V3),
            ("<div class='g-recaptcha' data-sitekey='x'></div><script>grecaptcha.execute()</script>", CaptchaKind.RECAPTCHA_V3),
            ("<div>no captcha here</div>", CaptchaKind.UNKNOWN),
            ("", CaptchaKind.UNKNOWN),
        ],
    )
    def test_various_markup(self, body: str, expected: CaptchaKind) -> None:
        assert _detect_kind(body) == expected

    def test_hcaptcha_wins_over_turnstile(self) -> None:
        """hCaptcha regex is checked before Turnstile; hCaptcha wins."""
        body = "<div class='h-captcha cf-turnstile'></div>"
        assert _detect_kind(body) == CaptchaKind.HCAPTCHA

    def test_recaptcha_v3_wins_over_v2(self) -> None:
        """v3 check runs after the base reCAPTCHA match; v3 wins."""
        body = "<div class='g-recaptcha' data-sitekey='x'></div>"
        assert _detect_kind(body) == CaptchaKind.RECAPTCHA_V2
        body_v3 = "<div class='g-recaptcha'></div><script>grecaptcha.execute()</script>"
        assert _detect_kind(body_v3) == CaptchaKind.RECAPTCHA_V3


class TestDetectSiteKey:
    """_detect_site_key() extraction from markup."""

    @pytest.mark.parametrize(
        ("body", "expected"),
        [
            ("<div data-sitekey='abc123'></div>", "abc123"),
            ('<div data-sitekey="xyz789"></div>', "xyz789"),
            ("https://recaptcha/api.js?render=6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI", "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"),
            ("<div>no key here</div>", ""),
            ("", ""),
        ],
    )
    def test_patterns(self, body: str, expected: str) -> None:
        assert _detect_site_key(body) == expected

    def test_data_sitekey_with_single_quote(self) -> None:
        assert _detect_site_key("<div data-sitekey='key_single'></div>") == "key_single"

    def test_data_sitekey_with_double_quote(self) -> None:
        assert _detect_site_key('<div data-sitekey="key_double"></div>') == "key_double"


class TestBuildCaptchaContext:
    """build_captcha_context() — the main entry point."""

    def test_with_full_state(self) -> None:
        """State with url + body produces a correctly classified context."""
        ctx = build_captcha_context(
            type("FakeState", (), {"url": "https://example.com", "body": "<div class='h-captcha' data-sitekey='sk123'></div>"})(),
            session_url="https://takeover/abc",
        )
        assert ctx.url == "https://example.com"
        assert ctx.kind == CaptchaKind.HCAPTCHA
        assert ctx.site_key == "sk123"
        assert ctx.session_url == "https://takeover/abc"
        assert ctx.response_field == "g-recaptcha-response"
        assert ctx.callback == ""
        assert ctx.extra == {}

    def test_body_missing_treated_as_empty(self) -> None:
        """If state has no ``body``, defaults to empty string → UNKNOWN."""
        ctx = build_captcha_context(
            type("FakeState", (), {"url": "https://example.com"})(),
        )
        assert ctx.kind == CaptchaKind.UNKNOWN
        assert ctx.site_key == ""

    def test_body_is_none(self) -> None:
        """``body=None`` is coerced to empty string."""
        ctx = build_captcha_context(
            type("FakeState", (), {"url": "https://example.com", "body": None})(),
        )
        assert ctx.kind == CaptchaKind.UNKNOWN

    def test_no_state_attributes(self) -> None:
        """A bare object with neither url nor body still builds; everything defaults."""
        ctx = build_captcha_context(type("FakeState", (), {})())
        assert ctx.url == ""
        assert ctx.kind == CaptchaKind.UNKNOWN
        assert ctx.site_key == ""

    def test_session_url_overrides_url(self) -> None:
        """session_url is stored separately, distinct from state.url."""
        ctx = build_captcha_context(
            type("FakeState", (), {"url": "https://original.com", "body": ""})(),
            session_url="https://takeover/xyz",
        )
        assert ctx.url == "https://original.com"
        assert ctx.session_url == "https://takeover/xyz"

    def test_recaptcha_v3_through_build(self) -> None:
        """End-to-end: render-param markup produces RECAPTCHA_V3 with site key."""
        body = "<script src='https://recaptcha/api.js?render=6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI'></script>"
        ctx = build_captcha_context(
            type("FakeState", (), {"url": "https://example.com", "body": body})(),
        )
        assert ctx.kind == CaptchaKind.RECAPTCHA_V3
        assert ctx.site_key == "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"

    def test_turnstile_through_build(self) -> None:
        """End-to-end: turnstile markup produces TURNSTILE kind."""
        body = "<div class='cf-turnstile' data-sitekey='0x4AAAAAAAHwA'></div>"
        ctx = build_captcha_context(
            type("FakeState", (), {"url": "https://example.com", "body": body})(),
        )
        assert ctx.kind == CaptchaKind.TURNSTILE
        assert ctx.site_key == "0x4AAAAAAAHwA"


class TestCaptchaContextDataclass:
    """CaptchaContext dataclass properties one level deeper."""

    def test_frozen(self) -> None:
        """Instance is frozen — setting a field raises FrozenInstanceError."""
        ctx = CaptchaContext(url="https://x.com")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.url = "other"

    def test_defaults(self) -> None:
        """Fields default to safe empty values when not provided."""
        ctx = CaptchaContext(url="https://x.com")
        assert ctx.kind == CaptchaKind.UNKNOWN
        assert ctx.site_key == ""
        assert ctx.response_field == "g-recaptcha-response"
        assert ctx.callback == ""
        assert ctx.session_url == ""
        assert ctx.extra == {}

    def test_extra_roundtrip(self) -> None:
        """Extra dict carries detector signal through the dataclass."""
        ctx = CaptchaContext(url="https://x.com", extra={"score": "0.9"})
        assert ctx.extra == {"score": "0.9"}
