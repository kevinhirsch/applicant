"""LlmWedgeDetector + WedgeDetectingLLM — ADR-0008 (EPIC SELF-HEAL) Slice S1.

Grounds: `docs/adr/0008-autonomous-self-healing.md` §Decision layer 1 (detector
#1/#3), `docs/stories/self-healing.md` S1,
`src/applicant/application/services/llm_wedge_detector.py`.

The real incident: the local vLLM's API stayed up but generation deadlocked,
silently freezing scoring + auto-draft for ~5.5 hours with no alert. These
tests prove, red->green:

* a SINGLE transient failure never fires anything (the ladder already
  absorbs that silently -- that's correct behavior, not a gap);
* N CONSECUTIVE primary-tier failures IS recognized as a distinct, escalatable
  "wedge" signal -- a typed `LocalLlmWedgeDetected` domain event + an operator
  alert;
* when a fallback tier is configured, escalation is verified end to end
  (the caller gets a real answer, never `LLMLadderExhausted`) AND still gets
  flagged (a working cloud fallback masking a dead local model is itself a
  cost/risk the operator needs to know about, per ADR-0008 Consequences);
* when NO fallback is configured, the failure is never silent: it is recorded
  (typed audit event) and alerted LOUDLY instead of the caller just eating an
  exception with nothing surfacing to the operator;
* alerting is bounded/deduped (guardrail: no alert storms) and clears on
  recovery so a LATER, genuinely new wedge alerts again.
"""

from __future__ import annotations

import httpx
import pytest

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.audit_log_service import AuditLogService
from applicant.application.services.llm_wedge_detector import (
    DEFAULT_WEDGE_THRESHOLD,
    LlmWedgeDetector,
    WedgeDetectingLLM,
)
from applicant.core.events import DomainEventBus, LocalLlmWedgeDetected, RemediationRequested
from applicant.ports.driven.llm import ChatMessage, LLMLadderExhausted, TierConfig, TierLadder

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingNotifications:
    """Stands in for NotificationService -- records every notify_error call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def notify_error(self, *, title: str, body: str, dedup_key: str | None = None) -> str:
        self.calls.append({"title": title, "body": body, "dedup_key": dedup_key})
        return f"handle-{len(self.calls)}"


def _collecting_bus() -> tuple[DomainEventBus, list]:
    bus = DomainEventBus()
    received: list = []
    bus.on(LocalLlmWedgeDetected, received.append)
    bus.on(RemediationRequested, received.append)
    return bus, received


# ---------------------------------------------------------------------------
# LlmWedgeDetector — pure unit tests (no network, no adapter)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWedgeThresholdDistinguishesBlipFromWedge:
    def test_single_failure_is_a_blip_not_a_wedge(self):
        """AC: a single transient failure must NOT fire detection/alert."""
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        detector.record_attempt(
            primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
        )

        assert received == []
        assert notifications.calls == []

    def test_failures_below_threshold_stay_silent(self):
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        for _ in range(2):
            detector.record_attempt(
                primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
            )

        assert received == []
        assert notifications.calls == []

    def test_reaching_threshold_emits_typed_event_and_alerts(self):
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        for _ in range(3):
            detector.record_attempt(
                primary_tier_failed=True,
                escalated=True,
                fallback_configured=True,
                tier_count=2,
                error="ConnectTimeout",
            )

        wedge_events = [e for e in received if isinstance(e, LocalLlmWedgeDetected)]
        remediation_events = [e for e in received if isinstance(e, RemediationRequested)]
        assert len(wedge_events) == 1
        assert wedge_events[0].consecutive_failures == 3
        assert wedge_events[0].tier_count == 2
        assert wedge_events[0].escalated is True
        assert wedge_events[0].fallback_configured is True
        assert wedge_events[0].last_error == "ConnectTimeout"
        # Optional remediation-requested signal for an external watchdog (never
        # consumed/actioned in this slice -- see module docstring).
        assert len(remediation_events) == 1
        assert remediation_events[0].detector == "local_llm_wedge"
        assert len(notifications.calls) == 1

    def test_default_threshold_matches_documented_default(self):
        assert DEFAULT_WEDGE_THRESHOLD == 3

    def test_success_resets_the_streak(self):
        """Two failures, a success, then two more failures never reaches a
        3-in-a-row streak -- must stay silent (proves the counter is
        CONSECUTIVE, not cumulative)."""
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        detector.record_attempt(
            primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
        )
        detector.record_attempt(
            primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
        )
        detector.record_success()
        detector.record_attempt(
            primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
        )
        detector.record_attempt(
            primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
        )

        assert received == []
        assert notifications.calls == []
        assert detector.consecutive_failures == 2


@pytest.mark.unit
class TestAlertBoundedAndDeduped:
    def test_alert_fires_once_while_the_wedge_persists(self):
        """Guardrail: bounded, no alert storms -- a wedge that keeps failing
        must page the operator ONCE for the streak, not once per call."""
        bus, _ = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        for _ in range(10):
            detector.record_attempt(
                primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
            )

        assert len(notifications.calls) == 1

    def test_recovery_then_re_wedge_alerts_again(self):
        """A NEW, distinct wedge after a real recovery is a genuinely new
        incident and must alert again -- dedup must not silence forever."""
        bus, _ = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        for _ in range(3):
            detector.record_attempt(
                primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
            )
        assert len(notifications.calls) == 1

        detector.record_success()

        for _ in range(3):
            detector.record_attempt(
                primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
            )
        assert len(notifications.calls) == 2

    def test_state_transition_from_escalated_to_unrecovered_alerts_again(self):
        """A wedge that WAS being caught by the fallback but then the fallback
        itself starts failing too is materially worse -- re-alert."""
        bus, _ = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)

        for _ in range(3):
            detector.record_attempt(
                primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
            )
        assert len(notifications.calls) == 1
        assert notifications.calls[0]["dedup_key"] == "llm_wedge:escalated"

        detector.record_attempt(
            primary_tier_failed=True, escalated=False, fallback_configured=True, tier_count=2
        )
        assert len(notifications.calls) == 2
        assert notifications.calls[1]["dedup_key"] == "llm_wedge:unrecovered"


@pytest.mark.unit
class TestAlertCopyDistinguishesEscalatedFromUnrecovered:
    def test_escalated_alert_says_running_on_fallback(self):
        bus, _ = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=1)

        detector.record_attempt(
            primary_tier_failed=True, escalated=True, fallback_configured=True, tier_count=2
        )

        call = notifications.calls[0]
        assert call["dedup_key"] == "llm_wedge:escalated"
        assert "fallback" in call["title"].lower()

    def test_no_fallback_configured_alerts_loudly(self):
        """AC: 'when NO fallback is configured, the failure must be recorded +
        alerted LOUDLY ... instead of silently degrading'."""
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=1)

        detector.record_attempt(
            primary_tier_failed=True,
            escalated=False,
            fallback_configured=False,
            tier_count=1,
            error="ReadTimeout after 120s",
        )

        wedge_events = [e for e in received if isinstance(e, LocalLlmWedgeDetected)]
        assert len(wedge_events) == 1
        assert wedge_events[0].escalated is False
        assert wedge_events[0].fallback_configured is False

        call = notifications.calls[0]
        assert call["dedup_key"] == "llm_wedge:unrecovered"
        assert "wedged" in call["title"].lower()
        assert "no fallback tier is configured" in call["body"]
        assert "ReadTimeout after 120s" in call["body"]

    def test_fallback_configured_but_also_failing_names_that_distinctly(self):
        bus, _ = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=1)

        detector.record_attempt(
            primary_tier_failed=True,
            escalated=False,
            fallback_configured=True,
            tier_count=2,
        )

        assert "the fallback tier is failing too" in notifications.calls[0]["body"]


@pytest.mark.unit
class TestNotificationsLateBinding:
    def test_no_notifications_wired_yet_still_audits_without_raising(self):
        """Boot-window edge case (composition-root wiring order): detection +
        audit must never depend on the alert channel existing yet."""
        bus, received = _collecting_bus()
        detector = LlmWedgeDetector(bus=bus, notifications=None, threshold=1)

        detector.record_attempt(
            primary_tier_failed=True, escalated=False, fallback_configured=False, tier_count=1
        )

        assert len(received) == 2  # wedge + remediation-requested still fire

    def test_set_notifications_late_binds_the_alert_channel(self):
        bus, _ = _collecting_bus()
        detector = LlmWedgeDetector(bus=bus, notifications=None, threshold=1)
        notifications = _RecordingNotifications()
        detector.set_notifications(notifications)

        detector.record_attempt(
            primary_tier_failed=True, escalated=False, fallback_configured=False, tier_count=1
        )

        assert len(notifications.calls) == 1


# ---------------------------------------------------------------------------
# WedgeDetectingLLM — decorator wired around the REAL adapter, escalation
# proven end-to-end over httpx.MockTransport (mirrors test_llm_fallback_tier.py)
# ---------------------------------------------------------------------------


def _two_tier_ladder_local_always_fails() -> TierLadder:
    return TierLadder(
        tiers=[
            TierConfig(
                provider="ollama",
                base_url="http://127.0.0.1:11434",
                model="qwen3.6:27b",
                context_window=32768,
            ),
            TierConfig(
                provider="openai",
                base_url="https://api.deepseek.com/v1",
                model="deepseek-chat",
                api_key="sk-fallback-test-key",
                context_window=65536,
            ),
        ]
    )


def _handler_local_wedged_fallback_answers(request: httpx.Request) -> httpx.Response:
    if "deepseek" not in str(request.url):
        # The local model's API is UP (connects) but generation deadlocks --
        # modeled here as a hard transport failure, which is exactly how the
        # ladder's existing `httpx.HTTPError` catch treats a genuine timeout too
        # (see openai_compatible.py `complete()`).
        raise httpx.ConnectTimeout("local model wedged (simulated)")
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "a real fallback answer"}}]},
    )


@pytest.mark.unit
class TestWedgeDetectingLlmEscalationVerified:
    def test_calls_still_succeed_through_the_wrapper(self):
        """The wrapper must be a pure observer: behavior is unchanged."""
        inner = OpenAICompatibleLLM(
            ladder=_two_tier_ladder_local_always_fails(),
            transport=httpx.MockTransport(_handler_local_wedged_fallback_answers),
        )
        bus, _ = _collecting_bus()
        detector = LlmWedgeDetector(bus=bus, notifications=_RecordingNotifications(), threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        result = llm.complete([ChatMessage(role="user", content="hi")])

        assert result.tier == 2
        assert result.text == "a real fallback answer"

    def test_repeated_local_failures_are_classified_escalated_after_threshold(self):
        inner = OpenAICompatibleLLM(
            ladder=_two_tier_ladder_local_always_fails(),
            transport=httpx.MockTransport(_handler_local_wedged_fallback_answers),
        )
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        for _ in range(3):
            result = llm.complete([ChatMessage(role="user", content="hi")])
            assert result.tier == 2  # every call still succeeds via the fallback

        wedge_events = [e for e in received if isinstance(e, LocalLlmWedgeDetected)]
        assert len(wedge_events) == 1
        assert wedge_events[0].escalated is True
        assert wedge_events[0].fallback_configured is True
        assert notifications.calls[0]["dedup_key"] == "llm_wedge:escalated"

    def test_single_local_failure_below_threshold_stays_silent(self):
        inner = OpenAICompatibleLLM(
            ladder=_two_tier_ladder_local_always_fails(),
            transport=httpx.MockTransport(_handler_local_wedged_fallback_answers),
        )
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        llm.complete([ChatMessage(role="user", content="hi")])

        assert received == []
        assert notifications.calls == []

    def test_healthy_local_tier_never_triggers_detection(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "local answered fine"}}]}
            )

        inner = OpenAICompatibleLLM(
            ladder=_two_tier_ladder_local_always_fails(), transport=httpx.MockTransport(handler)
        )
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=1)
        llm = WedgeDetectingLLM(inner, detector)

        for _ in range(5):
            llm.complete([ChatMessage(role="user", content="hi")])

        assert received == []
        assert notifications.calls == []


@pytest.mark.unit
class TestWedgeDetectingLlmNoFallbackFailsLoudNotSilent:
    def test_exception_still_propagates_unchanged(self):
        """The wrapper observes; it must NEVER swallow LLMLadderExhausted."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("local model wedged, no fallback (simulated)")

        single_tier_ladder = TierLadder(
            tiers=[
                TierConfig(
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.6:27b",
                    context_window=32768,
                )
            ]
        )
        inner = OpenAICompatibleLLM(
            ladder=single_tier_ladder, transport=httpx.MockTransport(handler)
        )
        bus, _ = _collecting_bus()
        detector = LlmWedgeDetector(bus=bus, notifications=_RecordingNotifications(), threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        with pytest.raises(LLMLadderExhausted):
            llm.complete([ChatMessage(role="user", content="hi")])

    def test_no_fallback_wedge_is_recorded_and_alerted_loudly_not_silently(self):
        """AC (S1 gap this closes): before this, a wedge with no fallback was
        just an exception the caller ate somewhere upstream -- nothing was
        typed-audited or alerted. Now it must be both."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("local model wedged, no fallback (simulated)")

        single_tier_ladder = TierLadder(
            tiers=[
                TierConfig(
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.6:27b",
                    context_window=32768,
                )
            ]
        )
        inner = OpenAICompatibleLLM(
            ladder=single_tier_ladder, transport=httpx.MockTransport(handler)
        )
        bus, received = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        for _ in range(3):
            with pytest.raises(LLMLadderExhausted):
                llm.complete([ChatMessage(role="user", content="hi")])

        wedge_events = [e for e in received if isinstance(e, LocalLlmWedgeDetected)]
        assert len(wedge_events) == 1
        assert wedge_events[0].escalated is False
        assert wedge_events[0].fallback_configured is False
        assert wedge_events[0].tier_count == 1
        assert len(notifications.calls) == 1
        assert notifications.calls[0]["dedup_key"] == "llm_wedge:unrecovered"

    def test_alert_deduped_across_repeated_exhaustion_not_once_per_call(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("wedged (simulated)")

        single_tier_ladder = TierLadder(
            tiers=[
                TierConfig(
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.6:27b",
                    context_window=32768,
                )
            ]
        )
        inner = OpenAICompatibleLLM(
            ladder=single_tier_ladder, transport=httpx.MockTransport(handler)
        )
        bus, _ = _collecting_bus()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=2)
        llm = WedgeDetectingLLM(inner, detector)

        for _ in range(8):
            with pytest.raises(LLMLadderExhausted):
                llm.complete([ChatMessage(role="user", content="hi")])

        assert len(notifications.calls) == 1


@pytest.mark.unit
class TestWedgeDetectingLlmPassThrough:
    """The decorator must not break any other LLMPort surface (mirrors the
    same proof `notification_service.py`'s `_RealtimePublishingNotifier`
    already relies on for `NotificationPort`)."""

    def test_is_configured_and_ladder_forward_to_inner(self):
        inner = OpenAICompatibleLLM(ladder=_two_tier_ladder_local_always_fails())
        detector = LlmWedgeDetector(threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        assert llm.is_configured() is True
        assert len(llm.ladder) == 2

    def test_refresh_ladder_forwards_to_inner(self):
        inner = OpenAICompatibleLLM(ladder=_two_tier_ladder_local_always_fails())
        detector = LlmWedgeDetector(threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        # Must not raise -- a no-op on a frozen (non-provider-backed) ladder,
        # exactly like calling it directly on the inner adapter.
        llm.refresh_ladder()

    def test_list_models_forwards_to_inner(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "qwen3.6:27b"}]})

        inner = OpenAICompatibleLLM(
            ladder=TierLadder(
                tiers=[
                    TierConfig(
                        provider="openai",
                        base_url="https://api.openai.com/v1",
                        model="qwen3.6:27b",
                        context_window=32768,
                    )
                ]
            ),
            transport=httpx.MockTransport(handler),
        )
        detector = LlmWedgeDetector(threshold=3)
        llm = WedgeDetectingLLM(inner, detector)

        assert llm.list_models() == ["qwen3.6:27b"]


# ---------------------------------------------------------------------------
# AuditLogService wiring — the typed events land on the SAME audit trail as
# every other domain event (ADR-0008 §5 Auditability), no new store.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuditLogWiring:
    def test_local_llm_wedge_detected_persists_a_detector_fired_action_event(self):
        storage = InMemoryStorage()
        bus = DomainEventBus()
        svc = AuditLogService(storage, bus=bus)
        svc.start()

        bus.emit(
            LocalLlmWedgeDetected(
                consecutive_failures=3,
                tier_count=2,
                fallback_configured=True,
                escalated=True,
                last_error="ConnectTimeout",
            )
        )

        events = list(storage.action_events._d.values())
        assert len(events) == 1
        assert events[0].action == "detector_fired"
        assert "3 consecutive" in events[0].reason
        assert events[0].context == {
            "consecutive_failures": 3,
            "tier_count": 2,
            "fallback_configured": True,
            "escalated": True,
            "last_error": "ConnectTimeout",
        }

    def test_remediation_requested_persists_with_its_reason(self):
        storage = InMemoryStorage()
        bus = DomainEventBus()
        svc = AuditLogService(storage, bus=bus)
        svc.start()

        bus.emit(
            RemediationRequested(
                detector="local_llm_wedge",
                target="local_llm",
                reason="primary LLM tier failed 3 consecutive calls",
            )
        )

        events = list(storage.action_events._d.values())
        assert len(events) == 1
        assert events[0].action == "remediation_requested"
        assert events[0].reason == "primary LLM tier failed 3 consecutive calls"
        assert events[0].context == {"detector": "local_llm_wedge", "target": "local_llm"}

    def test_end_to_end_wedge_detected_via_real_decorator_reaches_the_audit_trail(self):
        """No manually-constructed event: the wedge event must come from the
        REAL detector observing the REAL adapter, exactly as it would in prod."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("wedged (simulated)")

        single_tier_ladder = TierLadder(
            tiers=[
                TierConfig(
                    provider="ollama",
                    base_url="http://127.0.0.1:11434",
                    model="qwen3.6:27b",
                    context_window=32768,
                )
            ]
        )
        inner = OpenAICompatibleLLM(
            ladder=single_tier_ladder, transport=httpx.MockTransport(handler)
        )
        storage = InMemoryStorage()
        bus = DomainEventBus()
        audit = AuditLogService(storage, bus=bus)
        audit.start()
        notifications = _RecordingNotifications()
        detector = LlmWedgeDetector(bus=bus, notifications=notifications, threshold=2)
        llm = WedgeDetectingLLM(inner, detector)

        for _ in range(2):
            with pytest.raises(LLMLadderExhausted):
                llm.complete([ChatMessage(role="user", content="hi")])

        fired = [e for e in storage.action_events._d.values() if e.action == "detector_fired"]
        assert len(fired) == 1
        assert notifications.calls  # loud alert also fired
