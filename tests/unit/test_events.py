"""Unit tests for applicant.core.events — DomainEventBus + domain event dataclasses.

Parallel-safe: a module-level autouse fixture creates a fresh DomainEventBus per test
so xdist workers never share the module-level singleton's handler registry.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest

from applicant.core.events import (
    ApplicationStateChanged,
    DomainEvent,
    DomainEventBus,
    JobDiscovered,
    MaterialApproved,
    OutcomeRecorded,
    PendingActionRaised,
    ViabilityScored,
    event_bus,
)
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    GeneratedDocumentId,
    JobPostingId,
)


# ---------------------------------------------------------------------------
# Parallel-safety fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_event_bus() -> DomainEventBus:
    """Return a brand-new DomainEventBus every test.

    Without this each test would mutate the module-level ``event_bus`` singleton,
    leaking handlers across xdist workers or across tests within the same worker.
    """
    return DomainEventBus()


# ===================================================================
# DomainEventBus
# ===================================================================


@pytest.mark.unit
class TestEventBusSubscribeEmit:
    """subscribe and emit flow."""

    def test_subscribe_and_emit(self, _fresh_event_bus: DomainEventBus) -> None:
        bus = _fresh_event_bus
        handler = Mock()
        event = DomainEvent()

        bus.on(DomainEvent, handler)
        bus.emit(event)

        handler.assert_called_once_with(event)

    def test_handler_not_called_wrong_event_type(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        handler = Mock()
        bus.on(ApplicationStateChanged, handler)

        # JobDiscovered is not an ApplicationStateChanged
        bus.emit(JobDiscovered(campaign_id=CampaignId("c1")))

        handler.assert_not_called()

    def test_emit_no_subscribers(self, _fresh_event_bus: DomainEventBus) -> None:
        bus = _fresh_event_bus
        # Should not raise
        bus.emit(DomainEvent())


@pytest.mark.unit
class TestEventBusSubclassMatching:
    """Subscriber for a parent event type receives subclass events."""

    def test_handler_on_base_receives_subclass(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        handler = Mock()
        bus.on(DomainEvent, handler)

        subclass_event = JobDiscovered(campaign_id=CampaignId("c1"))
        bus.emit(subclass_event)

        handler.assert_called_once_with(subclass_event)

    def test_sibling_not_received_by_other_branch(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        handler = Mock()
        bus.on(JobDiscovered, handler)

        bus.emit(ViabilityScored(posting_id=JobPostingId("j1")))

        handler.assert_not_called()

    def test_both_base_and_specific_handlers_fired(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        base_handler = Mock()
        specific_handler = Mock()
        bus.on(DomainEvent, base_handler)
        bus.on(JobDiscovered, specific_handler)

        event = JobDiscovered(campaign_id=CampaignId("c1"))
        bus.emit(event)

        base_handler.assert_called_once_with(event)
        specific_handler.assert_called_once_with(event)


@pytest.mark.unit
class TestEventBusExceptionSwallowing:
    """Exception in one handler does not break other handlers."""

    def test_exception_swallowed_other_handlers_still_run(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        failing_handler = Mock(side_effect=ValueError("oops"))
        good_handler = Mock()
        event = DomainEvent()

        bus.on(DomainEvent, failing_handler)
        bus.on(DomainEvent, good_handler)
        bus.emit(event)

        # The exception was swallowed so the good handler still ran
        good_handler.assert_called_once_with(event)

    def test_emit_does_not_raise_on_handler_failure(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        bus.on(DomainEvent, Mock(side_effect=RuntimeError("fail")))

        # Should not raise
        bus.emit(DomainEvent())

    def test_only_failing_handler_swallowed_other_specific_handlers_run(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        fail = Mock(side_effect=TypeError("bad type"))
        ok = Mock()

        bus.on(ViabilityScored, fail)
        bus.on(ApplicationStateChanged, ok)

        event = ApplicationStateChanged(
            application_id=ApplicationId("a1"),
            from_state="new",
            to_state="scored",
            reason="auto",
        )
        bus.emit(event)

        # fail is not subscribed to ApplicationStateChanged, so only ok runs
        ok.assert_called_once_with(event)


@pytest.mark.unit
class TestEventBusMultipleHandlers:
    """Multiple handlers can subscribe to the same event type."""

    def test_two_handlers_both_called(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        h1 = Mock()
        h2 = Mock()
        event = DomainEvent()

        bus.on(DomainEvent, h1)
        bus.on(DomainEvent, h2)
        bus.emit(event)

        h1.assert_called_once_with(event)
        h2.assert_called_once_with(event)

    def test_three_handlers_called_in_registration_order(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        calls: list[int] = []

        def h1(_e: DomainEvent) -> None:
            calls.append(1)

        def h2(_e: DomainEvent) -> None:
            calls.append(2)

        def h3(_e: DomainEvent) -> None:
            calls.append(3)

        bus.on(DomainEvent, h1)
        bus.on(DomainEvent, h2)
        bus.on(DomainEvent, h3)
        bus.emit(DomainEvent())

        assert calls == [1, 2, 3]

    def test_separate_subscriptions_different_types(
        self, _fresh_event_bus: DomainEventBus
    ) -> None:
        bus = _fresh_event_bus
        dh = Mock()
        jh = Mock()

        bus.on(DomainEvent, dh)
        bus.on(JobDiscovered, jh)

        j_event = JobDiscovered(campaign_id=CampaignId("c1"))
        bus.emit(j_event)

        dh.assert_called_once_with(j_event)
        jh.assert_called_once_with(j_event)


# ===================================================================
# Module-level singleton
# ===================================================================


@pytest.mark.unit
class TestEventBusModuleSingleton:
    """The module exports a singleton ``event_bus``."""

    def test_event_bus_exists(self) -> None:
        assert isinstance(event_bus, DomainEventBus)

    def test_event_bus_is_singleton(self) -> None:
        # Re-importing gives the same object
        from applicant.core import events as events_mod  # type: ignore[import-untyped]

        assert events_mod.event_bus is event_bus


# ===================================================================
# Domain event dataclasses
# ===================================================================


@pytest.mark.unit
class TestDomainEventDefaults:
    """DomainEvent base class."""

    def test_construct_without_args(self) -> None:
        ev = DomainEvent()
        assert isinstance(ev.occurred_at, datetime)

    def test_occurred_at_is_populated(self) -> None:
        before = datetime.now(UTC)
        ev = DomainEvent()
        after = datetime.now(UTC)
        assert before <= ev.occurred_at <= after

    def test_occurred_at_custom_value(self) -> None:
        dt = datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
        ev = DomainEvent(occurred_at=dt)
        assert ev.occurred_at == dt

    def test_frozen_prevents_mutation(self) -> None:
        ev = DomainEvent()
        with pytest.raises(FrozenInstanceError):
            ev.occurred_at = datetime.now(UTC)  # type: ignore[misc]

    def test_frozen_prevents_new_attr(self) -> None:
        ev = DomainEvent()
        with pytest.raises(FrozenInstanceError):
            ev.new_field = "x"  # type: ignore[attr-defined]


@pytest.mark.unit
class TestJobDiscoveredDefaults:
    """JobDiscovered field defaults."""

    def test_minimal_construction(self) -> None:
        ev = JobDiscovered()
        assert ev.campaign_id is None
        assert ev.posting_id is None

    def test_full_construction(self) -> None:
        ev = JobDiscovered(
            occurred_at=datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
            campaign_id=CampaignId("camp-1"),
            posting_id=JobPostingId("post-1"),
        )
        assert ev.occurred_at == datetime(2025, 6, 1, 12, 0, tzinfo=UTC)
        assert ev.campaign_id == "camp-1"
        assert ev.posting_id == "post-1"

    def test_occurred_at_defaults_to_now(self) -> None:
        ev = JobDiscovered(campaign_id=CampaignId("c1"))
        assert ev.occurred_at.tzinfo is not None
        assert ev.occurred_at > datetime(2025, 1, 1, tzinfo=UTC)

    def test_default_campaign_id_is_none(self) -> None:
        ev = JobDiscovered(posting_id=JobPostingId("p1"))
        assert ev.campaign_id is None

    def test_frozen(self) -> None:
        ev = JobDiscovered(campaign_id=CampaignId("c1"))
        with pytest.raises(FrozenInstanceError):
            ev.campaign_id = CampaignId("c2")  # type: ignore[misc]


@pytest.mark.unit
class TestViabilityScoredDefaults:
    """ViabilityScored field defaults."""

    def test_minimal_construction(self) -> None:
        ev = ViabilityScored()
        assert ev.posting_id is None
        assert ev.score == 0.0
        assert ev.campaign_id is None

    def test_full_construction(self) -> None:
        ev = ViabilityScored(
            posting_id=JobPostingId("post-1"),
            score=0.85,
            campaign_id=CampaignId("camp-1"),
        )
        assert ev.posting_id == "post-1"
        assert ev.score == 0.85
        assert ev.campaign_id == "camp-1"

    def test_score_defaults_to_zero(self) -> None:
        ev = ViabilityScored(posting_id=JobPostingId("p1"))
        assert ev.score == 0.0

    def test_score_float_type(self) -> None:
        ev = ViabilityScored(posting_id=JobPostingId("p1"), score=0.5)
        assert isinstance(ev.score, float)


@pytest.mark.unit
class TestApplicationStateChangedDefaults:
    """ApplicationStateChanged field defaults."""

    def test_minimal_construction(self) -> None:
        ev = ApplicationStateChanged()
        assert ev.application_id is None
        assert ev.from_state == ""
        assert ev.to_state == ""
        assert ev.reason == ""

    def test_full_construction(self) -> None:
        ev = ApplicationStateChanged(
            application_id=ApplicationId("app-1"),
            from_state="new",
            to_state="scored",
            reason="auto-scored",
        )
        assert ev.application_id == "app-1"
        assert ev.from_state == "new"
        assert ev.to_state == "scored"
        assert ev.reason == "auto-scored"

    def test_application_id_defaults_to_none(self) -> None:
        ev = ApplicationStateChanged(from_state="a", to_state="b")
        assert ev.application_id is None

    def test_string_fields_default_to_empty(self) -> None:
        ev = ApplicationStateChanged(
            application_id=ApplicationId("a1"),
            from_state="old",
            to_state="new",
        )
        assert ev.reason == ""


@pytest.mark.unit
class TestPendingActionRaisedDefaults:
    """PendingActionRaised field defaults."""

    def test_minimal_construction(self) -> None:
        ev = PendingActionRaised()
        assert ev.application_id is None
        assert ev.action_kind == ""
        assert ev.reason == ""

    def test_full_construction(self) -> None:
        ev = PendingActionRaised(
            application_id=ApplicationId("app-1"),
            action_kind="review_material",
            reason="needs human review",
        )
        assert ev.application_id == "app-1"
        assert ev.action_kind == "review_material"
        assert ev.reason == "needs human review"

    def test_default_application_id_is_none(self) -> None:
        ev = PendingActionRaised(action_kind="sign")
        assert ev.application_id is None


@pytest.mark.unit
class TestMaterialApprovedDefaults:
    """MaterialApproved field defaults."""

    def test_minimal_construction(self) -> None:
        ev = MaterialApproved()
        assert ev.document_id is None

    def test_full_construction(self) -> None:
        ev = MaterialApproved(
            document_id=GeneratedDocumentId("doc-1"),
        )
        assert ev.document_id == "doc-1"


@pytest.mark.unit
class TestOutcomeRecordedDefaults:
    """OutcomeRecorded field defaults."""

    def test_minimal_construction(self) -> None:
        ev = OutcomeRecorded()
        assert ev.application_id is None
        assert ev.outcome_type == ""
        assert ev.source == ""
        assert ev.reason == ""

    def test_full_construction(self) -> None:
        ev = OutcomeRecorded(
            application_id=ApplicationId("app-1"),
            outcome_type="submitted",
            source="engine",
            reason="auto-submit success",
        )
        assert ev.application_id == "app-1"
        assert ev.outcome_type == "submitted"
        assert ev.source == "engine"
        assert ev.reason == "auto-submit success"

    def test_application_id_defaults_to_none(self) -> None:
        ev = OutcomeRecorded(outcome_type="rejected")
        assert ev.application_id is None

    def test_all_string_fields_default_to_empty(self) -> None:
        ev = OutcomeRecorded(application_id=ApplicationId("a1"))
        assert ev.outcome_type == ""
        assert ev.source == ""
        assert ev.reason == ""


# ===================================================================
# Inheritance
# ===================================================================


@pytest.mark.unit
class TestEventInheritance:
    """All concrete event types are instances of DomainEvent."""

    @pytest.mark.parametrize(
        "event",
        [
            DomainEvent(),
            JobDiscovered(),
            ViabilityScored(),
            ApplicationStateChanged(),
            PendingActionRaised(),
            MaterialApproved(),
            OutcomeRecorded(),
        ],
    )
    def test_is_domain_event(self, event: object) -> None:
        assert isinstance(event, DomainEvent)

    def test_event_bus_accepts_any_subclass(self, _fresh_event_bus: DomainEventBus) -> None:
        bus = _fresh_event_bus
        handler = Mock()
        bus.on(DomainEvent, handler)

        events = [
            JobDiscovered(campaign_id=CampaignId("c1")),
            ViabilityScored(posting_id=JobPostingId("j1")),
            ApplicationStateChanged(application_id=ApplicationId("a1"), from_state="x", to_state="y"),
            PendingActionRaised(application_id=ApplicationId("a2"), action_kind="sign"),
            MaterialApproved(document_id=GeneratedDocumentId("d1")),
            OutcomeRecorded(application_id=ApplicationId("a3"), outcome_type="done"),
        ]
        for ev in events:
            bus.emit(ev)

        assert handler.call_count == len(events)
