"""CaptchaSolverPort — behavioral-avoidance + solver-service + human-handoff
interfaces for CAPTCHA resolution (issue #350, tied to #305).

Three complementary strategies, each a separate Protocol so a concrete adapter
may implement one, two, or all three:

1. **Behavioral avoidance** — steer the browser interaction so the site's
   CAPTCHA heuristic is never triggered (mouse-movement patterns, timing,
   scroll cadence). The default no-op adapter records calls without acting.

2. **Solver service** — farm the CAPTCHA challenge to an external solving
   service (e.g. 2Captcha, Anti-Captcha, CapSolver). The adapter holds the
   service API key and returns the solution token.

3. **Human hand-off** — when the solver cannot resolve (or the operator has
   disabled automated solving), escalate to the human takeover path: push a
   notification with a deep link to the takeover desktop so the user can
   resolve the CAPTCHA in the live session.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class BehavioralAvoidancePort(Protocol):
    """Steer browser interaction to avoid triggering CAPTCHA challenges.

    The adapter intercepts or wraps browser actions to inject human-like
    timing, mouse-movement patterns, scroll cadence, and click randomization.
    """

    def record_navigation(self, url: str) -> None:
        """Record that the browser is navigating to ``url``.

        Allows the adapter to prepare behavioral profiles for the target site.
        """
        ...

    def humanize_before_action(self, action_type: str = "") -> None:
        """Inject a human-like delay and optional mouse trajectory before an action.

        ``action_type`` hints at the kind of action (``click``, ``type``,
        ``scroll``, ``select``) so the adapter can vary timing per action.
        """
        ...

    def should_bypass_captcha(self, page_url: str) -> bool:
        """Return True when the current page context is unlikely to trigger a
        CAPTCHA challenge.

        A no-op adapter always returns False (no confidence), deferring to the
        solver or hand-off path.
        """
        ...


@runtime_checkable
class CaptchaSolverServicePort(Protocol):
    """Submit a CAPTCHA challenge to an external solving service.

    The adapter manages the service API key, rate limits, and polling for the
    solution.
    """

    def is_configured(self) -> bool:
        """True when the solver service API key and endpoint are set."""
        ...

    def solve_image_captcha(self, image_base64: str, *, instructions: str = "") -> str | None:
        """Submit an image-based CAPTCHA for solving.

        Returns the solution token string, or None if solving failed or timed out.
        ``instructions`` may carry additional context (e.g. "select all
        traffic lights" for reCAPTCHA-style challenges).
        """
        ...

    def solve_recaptcha_v2(
        self, site_key: str, page_url: str, *, invisible: bool = False
    ) -> str | None:
        """Solve a reCAPTCHA v2 challenge (checkbox or invisible).

        Returns the ``g-recaptcha-response`` token, or None on failure.
        """
        ...

    def solve_recaptcha_v3(
        self, site_key: str, page_url: str, *, action: str = "submit"
    ) -> str | None:
        """Solve a reCAPTCHA v3 challenge.

        Returns the action token, or None on failure.
        """
        ...

    def solve_hcaptcha(self, site_key: str, page_url: str) -> str | None:
        """Solve an hCaptcha challenge.

        Returns the solution token, or None on failure.
        """
        ...

    def solve_fun_captcha(self, site_key: str, page_url: str) -> str | None:
        """Solve a FunCAPTCHA challenge.

        Returns the solution token, or None on failure.
        """
        ...


@runtime_checkable
class CaptchaHumanHandoffPort(Protocol):
    """Escalate an unsolved CAPTCHA to the human operator via the takeover
    surface.

    The adapter pushes a notification that includes a deep link to the live
    session where the CAPTCHA is displayed, so the user can resolve it
    directly.
    """

    def request_human_captcha_resolution(
        self,
        session_url: str,
        *,
        site_name: str = "",
        timeout_minutes: int = 5,
    ) -> bool:
        """Request that a human resolve the CAPTCHA in the live session.

        ``session_url`` is the deep link to the takeover desktop or browser
        session where the CAPTCHA challenge is displayed. Returns True when
        the hand-off was successfully requested (the human may still need to
        act). Returns False when no notification channel is available.
        """
        ...

    def is_pending_resolution(self, session_url: str) -> bool:
        """True when a human CAPTCHA hand-off for this session is still
        pending (not yet resolved or expired).
        """
        ...

    def cancel_pending(self, session_url: str) -> None:
        """Cancel a pending human hand-off (e.g. the CAPTCHA timed out or the
        page changed).
        """
        ...
