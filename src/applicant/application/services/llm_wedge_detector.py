"""LlmWedgeDetector + WedgeDetectingLLM — ADR-0008 (EPIC SELF-HEAL) Slice S1.

Grounds: `docs/adr/0008-autonomous-self-healing.md` §Decision layer 1 (detector
#1 "LLM tier-ladder exhaustion" / #3 "local vLLM wedged / unreachable"),
`docs/stories/self-healing.md` S1.

The real incident this closes: the local vLLM's API stayed up but generation
deadlocked, silently freezing scoring + auto-draft for ~5.5 hours with no
alert. `adapters/llm/openai_compatible.py`'s tier ladder already climbs past a
failing tier and (when a fallback tier is configured, see `setup_service.
build_ladder`) already escalates to it -- but nothing recognized "the primary
tier keeps failing" as a distinct, alertable signal, and nothing alerted LOUDLY
when there was no fallback to catch the failure.

This module adds exactly that detection, reusing existing seams end to end
(ADR-0008's reuse-first principle -- no parallel event system, no new alert
channel):

* :class:`LlmWedgeDetector` -- a small, bounded, in-process counter (the same
  consecutive-failure-count idiom already used by
  `scoring_service.py`'s `_bump_transient_failures` and `agent_loop.py`'s
  `_record_approval_start_failure`/`_record_resume_failure`) that tells a
  single transient blip (the ladder already absorbs these silently -- that's
  fine) apart from a genuine wedge (N consecutive primary-tier failures). On
  crossing the threshold it emits a typed :class:`~applicant.core.events.
  LocalLlmWedgeDetected` event on the **existing** `DomainEventBus`
  (`core/events.py`) -- so it lands on the audit trail via the **existing**
  `AuditLogService` with zero new plumbing -- and fires an operator alert
  through the **existing** `NotificationService.notify_error` (IMMEDIATE
  urgency, any hour, per FR-NOTIF-5). Alerting is deduped per (streak, escalated
  -vs-unrecovered state) so a wedge that keeps failing pages the operator once,
  not once per call (guardrail: bounded, no alert storms). It also emits an
  **optional** `RemediationRequested` event that an external watchdog could
  consume -- S1 does NOT implement the actual local-service restart (out of
  scope, see ADR-0008 Consequences: "genuine new build, not reuse").

* :class:`WedgeDetectingLLM` -- a transparent `LLMPort` decorator (same
  wrap-with-`__getattr__`-passthrough shape as `notification_service.py`'s
  `_RealtimePublishingNotifier`, which already does this for `NotificationPort`
  in this exact codebase) that feeds every `complete()`/`complete_with_tools()`
  outcome to a detector, then re-raises/returns exactly what the wrapped
  adapter did -- it OBSERVES, it never changes behavior, never swallows an
  exception, and never itself calls the network.
"""

from __future__ import annotations

import threading
from typing import Any

from applicant.core.events import (
    DomainEventBus,
    LocalLlmWedgeDetected,
    RemediationRequested,
    event_bus,
)
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import LLMLadderExhausted

log = get_logger(__name__)

#: Default consecutive-failure threshold before a wedge is declared (mirrors
#: `scoring_service.DEFAULT_MAX_TRANSIENT_RETRIES`'s bounded-retry idiom).
#: Tunable via `LLM_WEDGE_DETECTION_THRESHOLD` (see `app/config.py`).
DEFAULT_WEDGE_THRESHOLD = 3


class LlmWedgeDetector:
    """Recognizes a wedged/unreachable primary LLM tier as a distinct signal.

    Fed by :class:`WedgeDetectingLLM` (or any caller) via :meth:`record_attempt`
    once per completion attempt. Bounded, process-lived, thread-safe.
    """

    def __init__(
        self,
        *,
        bus: DomainEventBus | None = None,
        notifications: Any | None = None,
        threshold: int = DEFAULT_WEDGE_THRESHOLD,
    ) -> None:
        self._bus = bus or event_bus
        # Optional at construction: `NotificationService` is built later in the
        # composition root than the LLM adapter is (container.py) -- see
        # `set_notifications`. `None` here means "detect + audit, no alert yet"
        # rather than blocking the whole engine boot on wiring order.
        self._notifications = notifications
        self._threshold = max(1, int(threshold))
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        # None | "escalated" | "unrecovered" -- which alert (if any) is already
        # live for the CURRENT streak. Reset on the next success, so a later,
        # genuinely new wedge alerts again (guardrail: bounded, not silenced
        # forever -- only the noisy repeat-per-call case is deduped).
        self._alerted_state: str | None = None

    def set_notifications(self, notifications: Any) -> None:
        """Late-bind the alert channel (composition-root wiring-order seam).

        `NotificationService` is constructed after the LLM adapter in
        `container.py`; this lets the detector be built (and start counting)
        early while the alert path is wired in once it exists.
        """
        self._notifications = notifications

    @property
    def consecutive_failures(self) -> int:
        """Current consecutive-primary-tier-failure streak (observability/tests)."""
        with self._lock:
            return self._consecutive_failures

    def record_success(self) -> None:
        """The primary tier answered -- the streak (and any live alert) clears."""
        with self._lock:
            self._consecutive_failures = 0
            self._alerted_state = None

    def record_attempt(
        self,
        *,
        primary_tier_failed: bool,
        escalated: bool,
        fallback_configured: bool,
        tier_count: int,
        error: str = "",
    ) -> None:
        """Record one completion attempt's outcome.

        ``primary_tier_failed``: the tier the call actually started on did NOT
        answer (it either errored and something ELSE answered -- ``escalated``
        -- or the whole ladder exhausted). A single failure never fires
        anything; only crossing ``threshold`` CONSECUTIVE failures declares a
        wedge, which is what tells this apart from the ordinary transient noise
        the ladder already climbs past silently.
        """
        if not primary_tier_failed:
            self.record_success()
            return

        with self._lock:
            self._consecutive_failures += 1
            n = self._consecutive_failures
            if n < self._threshold:
                return
            state = "escalated" if escalated else "unrecovered"
            if self._alerted_state == state:
                # Already alerted for this exact streak+state -- dedupe so a
                # wedge that keeps failing doesn't page the operator every call
                # (guardrail: bounded, no alert storms).
                return
            self._alerted_state = state

        self._detect(
            n,
            escalated=escalated,
            fallback_configured=fallback_configured,
            tier_count=tier_count,
            error=error,
        )

    # -- detection -> audit + alert -----------------------------------------

    def _detect(
        self,
        consecutive_failures: int,
        *,
        escalated: bool,
        fallback_configured: bool,
        tier_count: int,
        error: str,
    ) -> None:
        event = LocalLlmWedgeDetected(
            consecutive_failures=consecutive_failures,
            tier_count=tier_count,
            fallback_configured=fallback_configured,
            escalated=escalated,
            last_error=error,
        )
        self._emit(event)
        self._emit(
            RemediationRequested(
                detector="local_llm_wedge",
                target="local_llm",
                reason=(
                    f"primary LLM tier failed {consecutive_failures} consecutive "
                    "calls"
                ),
            )
        )
        self._alert(
            consecutive_failures,
            escalated=escalated,
            fallback_configured=fallback_configured,
            error=error,
        )

    def _emit(self, event: Any) -> None:
        # The bus already swallows+logs a single bad handler (see
        # DomainEventBus.emit); this outer guard is defense against emit()
        # itself misbehaving so a detection can never break the calling
        # completion.
        try:
            self._bus.emit(event)
        except Exception:  # pragma: no cover - defensive, mirrors adapter idiom
            log.warning("llm_wedge_event_emit_failed", exc_info=True)

    def _alert(
        self,
        consecutive_failures: int,
        *,
        escalated: bool,
        fallback_configured: bool,
        error: str,
    ) -> None:
        if self._notifications is None:
            # Boot-window edge case only (see `set_notifications`) -- the
            # detection is still audited via the domain event above; only the
            # human-facing page is deferred.
            log.warning(
                "llm_wedge_notify_unavailable",
                consecutive_failures=consecutive_failures,
                escalated=escalated,
            )
            return
        if escalated:
            title = "Local LLM appears wedged — running on the cloud fallback"
            body = (
                f"The local model has failed {consecutive_failures} calls in a "
                "row. Applicant has escalated to the configured fallback tier "
                "so your job search keeps moving, but the local model is not "
                "healing itself — it likely needs a restart or reload. Every "
                "call is now paying cloud-inference cost until it's fixed."
            )
            dedup_key = "llm_wedge:escalated"
        else:
            title = "Local LLM is wedged — nothing is answering"
            reason = (
                "no fallback tier is configured"
                if not fallback_configured
                else "the fallback tier is failing too"
            )
            body = (
                f"The local model has failed {consecutive_failures} calls in a "
                f"row and {reason}. Scoring and drafting are stalled until this "
                "is fixed."
            )
            if error:
                body += f" Last error: {error}"
            dedup_key = "llm_wedge:unrecovered"
        try:
            self._notifications.notify_error(title=title, body=body, dedup_key=dedup_key)
        except Exception:  # pragma: no cover - an alert must never break a completion
            log.warning("llm_wedge_notify_failed", exc_info=True)


class WedgeDetectingLLM:
    """Transparent `LLMPort` decorator feeding every completion to a detector.

    Pure pass-through for every method it doesn't override (`list_models`,
    `is_configured`, `supports_tools`, `ladder`, `refresh_ladder`, ...) via
    `__getattr__` -- the same proven shape as `notification_service.py`'s
    `_RealtimePublishingNotifier`. Never changes what the wrapped adapter
    returns or raises; it only observes.
    """

    __slots__ = ("_inner", "_detector")

    def __init__(self, inner: Any, detector: LlmWedgeDetector) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_detector", detector)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _tier_count(self) -> int:
        ladder = getattr(self._inner, "ladder", None)
        if ladder is None:
            return 0
        try:
            return len(ladder)
        except TypeError:  # pragma: no cover - defensive, ladder is always Sized
            return 0

    def complete(
        self,
        messages: list,
        *,
        start_tier: int = 1,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ):
        tier_count = self._tier_count()
        fallback_configured = tier_count > start_tier
        try:
            result = self._inner.complete(
                messages,
                start_tier=start_tier,
                json_schema=json_schema,
                max_tokens=max_tokens,
            )
        except LLMLadderExhausted as exc:
            self._detector.record_attempt(
                primary_tier_failed=True,
                escalated=False,
                fallback_configured=fallback_configured,
                tier_count=tier_count,
                error=str(exc),
            )
            raise
        primary_failed = result.tier != start_tier
        self._detector.record_attempt(
            primary_tier_failed=primary_failed,
            escalated=primary_failed,
            fallback_configured=fallback_configured,
            tier_count=tier_count,
        )
        return result

    def complete_with_tools(
        self,
        messages: list,
        tools: list,
        *,
        start_tier: int = 1,
        max_tokens: int | None = None,
    ):
        tier_count = self._tier_count()
        fallback_configured = tier_count > start_tier
        try:
            result = self._inner.complete_with_tools(
                messages, tools, start_tier=start_tier, max_tokens=max_tokens
            )
        except LLMLadderExhausted as exc:
            self._detector.record_attempt(
                primary_tier_failed=True,
                escalated=False,
                fallback_configured=fallback_configured,
                tier_count=tier_count,
                error=str(exc),
            )
            raise
        primary_failed = result.tier != start_tier
        self._detector.record_attempt(
            primary_tier_failed=primary_failed,
            escalated=primary_failed,
            fallback_configured=fallback_configured,
            tier_count=tier_count,
        )
        return result
