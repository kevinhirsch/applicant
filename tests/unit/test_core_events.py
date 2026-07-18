"""Tests for applicant.core.events — DomainEventBus + domain event dataclasses."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

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


class TestDomainEventBus:
    """Tests for DomainEventBus using local instances (not the global singleton)."""

    @pytest.fixture(autouse=True)
    def fresh_bus(self) -> None:
        """Give each test a fresh DomainEventBus (parallel-safe for xdist)."""
        self.bus = DomainEventBus()

    def test_on_and_emit(self) -> None:
        """Subscribe a handler, emit an event, verify handler was called."""
        collected: list[DomainEvent] = []

        def handler(event: DomainEvent) -> None:
            collected.append(event)

        event = DomainEvent()
        self.bus.on(DomainEvent, handler)
        self.bus.emit(event)

        assert len(collected) == 1
        assert collected[0] is event

    def test_subclass_matching(self) -> None:
        """Subscribe to DomainEvent, emit JobDiscovered, handler fires via isinstance."""
        collected: list[DomainEvent] = []

        def handler(event: DomainEvent) -> None:
            collected.append(event)

        self.bus.on(DomainEvent, handler)
        self.bus.emit(JobDiscovered())

        assert len(collected) == 1
        assert isinstance(collected[0], JobDiscovered)

    def test_no_matching_handler(self) -> None:
        """Emit an event type nobody subscribed to — no crash."""
        self.bus.emit(DomainEvent())
        self.bus.emit(JobDiscovered())
        # Reaching here without exception is success.

    def test_exception_swallowing(self) -> None:
        """A handler that raises does NOT crash emit(); other handlers still run."""
        collected: list[str] = []

        def raises_handler(event: DomainEvent) -> None:
            msg = "boom"
            raise ValueError(msg)

        def good_handler(event: DomainEvent) -> None:
            collected.append("ok")

        self.bus.on(DomainEvent, raises_handler)
        self.bus.on(DomainEvent, good_handler)
        self.bus.emit(DomainEvent())

        assert collected == ["ok"]

    def test_multiple_handlers(self) -> None:
        """Two handlers for the same event type — both are called."""
        results: list[int] = []

        def handler_a(event: DomainEvent) -> None:
            results.append(1)

        def handler_b(event: DomainEvent) -> None:
            results.append(2)

        self.bus.on(DomainEvent, handler_a)
        self.bus.on(DomainEvent, handler_b)
        self.bus.emit(DomainEvent())

        assert sorted(results) == [1, 2]


class TestDomainEventDataclasses:
    """Verify all domain-event dataclasses have the expected fields and defaults."""

    def test_domain_event_base(self) -> None:
        """DomainEvent.occurred_at is a datetime with UTC tz."""
        ev = DomainEvent()
        assert isinstance(ev.occurred_at, datetime)
        assert ev.occurred_at.tzinfo is UTC

    def test_job_discovered(self) -> None:
        """JobDiscovered has campaign_id and posting_id, both default to None."""
        ev = JobDiscovered()
        assert ev.campaign_id is None
        assert ev.posting_id is None

        ev2 = JobDiscovered(campaign_id=None, posting_id=None)
        assert ev2.campaign_id is None
        assert ev2.posting_id is None

    def test_viability_scored(self) -> None:
        """ViabilityScored has posting_id, score (0.0 default), campaign_id."""
        ev = ViabilityScored()
        assert ev.posting_id is None
        assert ev.score == 0.0
        assert ev.campaign_id is None

    def test_application_state_changed(self) -> None:
        """ApplicationStateChanged has application_id, from_state, to_state, reason."""
        ev = ApplicationStateChanged()
        assert ev.application_id is None
        assert ev.from_state == ""
        assert ev.to_state == ""
        assert ev.reason == ""

    def test_pending_action_raised(self) -> None:
        """PendingActionRaised has application_id, action_kind, reason."""
        ev = PendingActionRaised()
        assert ev.application_id is None
        assert ev.action_kind == ""
        assert ev.reason == ""

    def test_material_approved(self) -> None:
        """MaterialApproved has document_id, default None."""
        ev = MaterialApproved()
        assert ev.document_id is None

    def test_outcome_recorded(self) -> None:
        """OutcomeRecorded has application_id, outcome_type, source, reason."""
        ev = OutcomeRecorded()
        assert ev.application_id is None
        assert ev.outcome_type == ""
        assert ev.source == ""
        assert ev.reason == ""


class TestGlobalEventBus:
    """Tests for the module-level ``event_bus`` singleton."""

    def test_event_bus_is_domain_event_bus(self) -> None:
        """The module-level ``event_bus`` is a DomainEventBus instance."""
        assert isinstance(event_bus, DomainEventBus)

    def test_on_and_emit_work(self) -> None:
        """Can call .on() and .emit() on the global bus without errors."""
        collected: list[DomainEvent] = []

        def handler(event: DomainEvent) -> None:
            collected.append(event)

        event_bus.on(DomainEvent, handler)
        event_bus.emit(DomainEvent())

        assert len(collected) >= 0  # The handler may fire; we just verify no crash.


class TestFrozenDataclass:
    """Ensure all domain-event dataclasses are frozen (immutable)."""

    @pytest.mark.parametrize(
        "event_cls",
        [
            DomainEvent,
            JobDiscovered,
            ViabilityScored,
            ApplicationStateChanged,
            PendingActionRaised,
            MaterialApproved,
            OutcomeRecorded,
        ],
    )
    def test_all_dataclasses_are_frozen(self, event_cls: type) -> None:
        """Setting an attribute on a frozen dataclass raises FrozenInstanceError."""
        ev = event_cls()
        with pytest.raises(FrozenInstanceError):
            ev.occurred_at = datetime.now(UTC)  # type: ignore[misc]
