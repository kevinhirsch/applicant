"""CaptchaSolverPort — behavioral-avoidance + human-handoff interfaces.

Issue #350: Provides the port protocol for CAPTCHA solving strategies.
Only the interfaces are defined here; live solver service needs API keys
and is built by Claude/user separately.
"""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, Protocol, runtime_checkable


class CaptchaKind(StrEnum):
    """Types of CAPTCHA challenges the engine may encounter."""
    IMAGE = auto()
    RECAPTCHA_V2 = auto()
    RECAPTCHA_V3 = auto()
    HCAPTCHA = auto()
    TURNSTILE = auto()
    FUNCAPTCHA = auto()
    TEXT = auto()
    AUDIO = auto()


class SolveStrategy(StrEnum):
    """Strategy for handling a CAPTCHA."""
    AVOID = auto()       # Change behavior to not trigger CAPTCHA
    HANDOFF = auto()     # Escalate to human
    SOLVE_AUTO = auto()  # Automatic solving (requires API key)
    RETRY = auto()       # Retry the action


@runtime_checkable
class CaptchaSolverPort(Protocol):
    """Port for CAPTCHA detection, avoidance, and solving.

    Implementations range from behavioral avoidance (change timing/headers
    to avoid triggering CAPTCHAs) to full automated solving (needs keys).
    """

    def detect(self, page_source: str) -> list[dict[str, Any]]:
        """Scan ``page_source`` for known CAPTCHA patterns.

        Returns a list of detections, each with ``kind`` (CaptchaKind),
        ``selector`` (CSS selector if found), and ``confidence`` (0-1).
        Empty list when no CAPTCHA is detected.
        """
        ...

    def select_strategy(self, detections: list[dict[str, Any]]) -> SolveStrategy:
        """Choose the best strategy for the detected CAPTCHAs.

        Default implementation returns AVOID when possible, HANDOFF otherwise.
        """
        ...

    def attempt_avoidance(self, url: str, context: dict[str, Any] | None = None) -> bool:
        """Attempt to avoid triggering the CAPTCHA by changing behavior.

        Returns True if avoidance succeeded (page loaded without CAPTCHA),
        False if the CAPTCHA still appeared.
        """
        ...

    def request_human_handoff(
        self, campaign_id: str, application_id: str, details: dict[str, Any]
    ) -> bool:
        """Escalate to a human operator via notification + pending action.

        Returns True when the handoff was recorded successfully.
        """
        ...
