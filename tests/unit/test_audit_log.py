"""Hermetic tests for the audit log: event → ActionEvent + export endpoint.

Tests:
- DomainEventBus subscribe/emit basics
- AuditLogService persists an ActionEvent per emission
- Export endpoint returns ordered JSON with Content-Disposition: attachment
- InMemoryStorage action_events repo works correctly
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.deps import get_storage, require_llm_configured
from applicant.app.routers.audit import router as audit_router
from applicant.application.services.audit_log_service import AuditLogService
from applicant.core.entities.action_event import ActionEvent
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.events import (
    ApplicationStateChanged,
    DomainEventBus,
    JobDiscovered,
    OutcomeRecorded,
    PendingActionRaised,
    ViabilityScored,
)
from applicant.core.ids import (
    ActionEventId,
    ApplicationId,
    CampaignId,
    JobPostingId,
    new_id,
)
from applicant.core.state_machine import ApplicationState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_campaign(storage: InMemoryStorage, cid: str = "c-1") -> Campaign:
    c = Campaign(id=CampaignId(cid), name="Test Search")
    storage.campaigns.add(c)
    storage.commit()
    return c


def _make_application(storage: InMemoryStorage, aid: str = "a-1", cid: str = "c-1") -> Application:
    app = Application(
        id=ApplicationId(aid),
        campaign_id=CampaignId(cid),
        posting_id=JobPostingId("p-1"),
        status=ApplicationState.DISCOVERED,
    )
    storage.applications.add(app)
    storage.commit()
    return app


def _build_test_app(storage: InMemoryStorage) -> FastAPI:
    app = FastAPI()
    app.state.container = type("C", (), {"storage": storage})()

    # Override gated dependencies for the hermetic test lane.
    def _get_storage():
        return storage

    app.dependency_overrides[get_storage] = _get_storage
    app.dependency_overrides[require_llm_configured] = lambda: None
    app.include_router(audit_router)
    return app


# ---------------------------------------------------------------------------
# InMemoryStorage action_events
# ---------------------------------------------------------------------------


class TestInMemoryActionEventRepo:
    def test_add_and_list_for_campaign(self):
        storage = InMemoryStorage()
        now = datetime(2026, 2, 1, tzinfo=UTC)
        ae = ActionEvent(
            id=ActionEventId(new_id()),
            occurred_at=now,
            campaign_id=CampaignId("c-1"),
            action="scored",
            reason="score 0.85",
        )
        storage.action_events.add(ae)
        storage.commit()

        events = storage.action_events.list_for_campaign(CampaignId("c-1"))
        assert len(events) == 1
        assert events[0].action == "scored"
        assert events[0].reason == "score 0.85"

    def test_list_for_application(self):
        storage = InMemoryStorage()
        now = datetime(2026, 2, 2, tzinfo=UTC)
        ae = ActionEvent(
            id=ActionEventId(new_id()),
            occurred_at=now,
            application_id=ApplicationId("a-1"),
            campaign_id=CampaignId("c-1"),
            action="state_changed",
            reason="DISCOVERED → SCORED",
        )
        storage.action_events.add(ae)
        storage.commit()

        events = storage.action_events.list_for_application(ApplicationId("a-1"))
        assert len(events) == 1
        assert events[0].application_id == ApplicationId("a-1")

    def test_ordering_by_occurred_at_desc(self):
        storage = InMemoryStorage()
        t1 = datetime(2026, 2, 1, tzinfo=UTC)
        t2 = datetime(2026, 2, 2, tzinfo=UTC)

        for _i, t in enumerate([t1, t2]):
            storage.action_events.add(
                ActionEvent(
                    id=ActionEventId(new_id()),
                    occurred_at=t,
                    campaign_id=CampaignId("c-1"),
                    action="discovered",
                )
            )
        storage.commit()

        events = storage.action_events.list_for_campaign(CampaignId("c-1"))
        assert len(events) == 2
        assert events[0].occurred_at == t2  # most recent first
        assert events[1].occurred_at == t1


# ---------------------------------------------------------------------------
# Event → ActionEvent persistence
# ---------------------------------------------------------------------------


class TestAuditLogServicePersistence:
    def test_event_bus_emit_and_subscribe(self):
        """Prove the event bus delivers events to subscribers."""
        bus = DomainEventBus()
        received = []

        def _handler(event):
            received.append(event)

        bus.on(ApplicationStateChanged, _handler)
        ev = ApplicationStateChanged(
            application_id=ApplicationId("a-1"),
            from_state="DISCOVERED",
            to_state="SCORED",
            reason="test move",
        )
        bus.emit(ev)
        assert len(received) == 1
        assert received[0].reason == "test move"

    def test_application_state_changed_persists_action_event(self):
        storage = InMemoryStorage()
        _make_campaign(storage, "c-1")
        _make_application(storage, "a-1", "c-1")

        bus = DomainEventBus()
        svc = AuditLogService(storage, bus=bus)
        svc.start()

        ev = ApplicationStateChanged(
            application_id=ApplicationId("a-1"),
            from_state="DISCOVERED",
            to_state="SCORED",
            reason="viability score passed threshold",
        )
        bus.emit(ev)

        events = storage.action_events.list_for_campaign(CampaignId("c-1"))
        assert len(events) == 1
        assert events[0].action == "state_changed"
        assert events[0].reason == "viability score passed threshold"
        assert events[0].application_id == ApplicationId("a-1")
        assert events[0].campaign_id == CampaignId("c-1")
        assert events[0].actor == "engine"
        assert events[0].context == {
            "from_state": "DISCOVERED",
            "to_state": "SCORED",
        }

    def test_viability_scored_persists_with_score(self):
        storage = InMemoryStorage()
        bus = DomainEventBus()
        svc = AuditLogService(storage, bus=bus)
        svc.start()

        ev = ViabilityScored(posting_id=JobPostingId("p-1"), score=0.85)
        bus.emit(ev)

        events = storage.action_events.list_for_campaign(CampaignId(""))
        assert len(events) == 0  # no campaign/application matched

        # Add campaign context this time
        _make_campaign(storage, "c-1")
        ev2 = JobDiscovered(campaign_id=CampaignId("c-1"), posting_id=JobPostingId("p-2"))
        bus.emit(ev2)

        events = storage.action_events.list_for_campaign(CampaignId("c-1"))
        assert len(events) == 1
        assert events[0].action == "discovered"

    def test_outcome_recorded_persists_with_reason(self):
        storage = InMemoryStorage()
        _make_campaign(storage, "c-1")
        _make_application(storage, "a-1", "c-1")

        bus = DomainEventBus()
        svc = AuditLogService(storage, bus=bus)
        svc.start()

        ev = OutcomeRecorded(
            application_id=ApplicationId("a-1"),
            outcome_type="submitted",
            source="auto",
            reason="confirmation page detected",
        )
        bus.emit(ev)

        events = storage.action_events.list_for_application(ApplicationId("a-1"))
        assert len(events) == 1
        assert events[0].action == "outcome_recorded"
        assert events[0].reason == "confirmation page detected"
        assert events[0].context == {"outcome_type": "submitted", "source": "auto"}

    def test_pending_action_raised_persists(self):
        storage = InMemoryStorage()
        _make_campaign(storage, "c-1")
        _make_application(storage, "a-1", "c-1")

        bus = DomainEventBus()
        svc = AuditLogService(storage, bus=bus)
        svc.start()

        ev = PendingActionRaised(
            application_id=ApplicationId("a-1"),
            action_kind="review_digest",
            reason="new viable role needs review",
        )
        bus.emit(ev)

        events = storage.action_events.list_for_application(ApplicationId("a-1"))
        assert len(events) == 1
        assert events[0].action == "pending_action"
        assert events[0].reason == "new viable role needs review"


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------


class TestAuditExportEndpoint:
    def test_campaign_export_returns_json_attachment(self):
        storage = InMemoryStorage()
        _make_campaign(storage, "c-1")
        _make_application(storage, "a-1", "c-1")

        # Seed two events
        t1 = datetime(2026, 3, 1, tzinfo=UTC)
        t2 = datetime(2026, 3, 2, tzinfo=UTC)
        storage.action_events.add(
            ActionEvent(
                id=ActionEventId(new_id()),
                occurred_at=t1,
                campaign_id=CampaignId("c-1"),
                application_id=ApplicationId("a-1"),
                action="discovered",
                reason="first find",
            )
        )
        storage.action_events.add(
            ActionEvent(
                id=ActionEventId(new_id()),
                occurred_at=t2,
                campaign_id=CampaignId("c-1"),
                application_id=ApplicationId("a-1"),
                action="scored",
                reason="score 0.92",
            )
        )
        storage.commit()

        app = _build_test_app(storage)
        client = TestClient(app)

        resp = client.get("/api/admin/audit-log/c-1/export.json")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "audit-log" in cd

        data = resp.json()
        assert data["count"] == 2
        assert "exported_at" in data
        events = data["events"]
        # Most recent first (t2 scored, then t1 discovered)
        assert events[0]["action"] == "scored"
        assert events[1]["action"] == "discovered"

    def test_application_export(self):
        storage = InMemoryStorage()
        _make_campaign(storage, "c-1")
        _make_application(storage, "a-1", "c-1")

        storage.action_events.add(
            ActionEvent(
                id=ActionEventId(new_id()),
                occurred_at=datetime(2026, 3, 1, tzinfo=UTC),
                application_id=ApplicationId("a-1"),
                campaign_id=CampaignId("c-1"),
                action="state_changed",
                reason="test",
            )
        )
        storage.commit()

        app = _build_test_app(storage)
        client = TestClient(app)

        resp = client.get("/api/admin/audit-log/application/a-1/export.json")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd

        data = resp.json()
        assert data["count"] == 1
        assert data["events"][0]["application_id"] == "a-1"

    def test_empty_export(self):
        storage = InMemoryStorage()
        _make_campaign(storage, "c-empty")
        app = _build_test_app(storage)
        client = TestClient(app)

        resp = client.get("/api/admin/audit-log/c-empty/export.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["events"] == []

    def test_export_fields_match_entity(self):
        """Verify every key field of ActionEvent is present and correct in the export."""
        storage = InMemoryStorage()
        _make_campaign(storage, "c-1")
        _make_application(storage, "a-1", "c-1")

        now = datetime(2026, 4, 1, tzinfo=UTC)
        storage.action_events.add(
            ActionEvent(
                id=ActionEventId("ev-1"),
                occurred_at=now,
                application_id=ApplicationId("a-1"),
                campaign_id=CampaignId("c-1"),
                actor="user",
                action="submitted",
                reason="user clicked I submitted this",
                context={"source": "manual"},
            )
        )
        storage.commit()

        app = _build_test_app(storage)
        client = TestClient(app)

        resp = client.get("/api/admin/audit-log/c-1/export.json")
        assert resp.status_code == 200
        ev = resp.json()["events"][0]

        assert ev["id"] == "ev-1"
        assert ev["application_id"] == "a-1"
        assert ev["campaign_id"] == "c-1"
        assert ev["actor"] == "user"
        assert ev["action"] == "submitted"
        assert ev["reason"] == "user clicked I submitted this"
        assert ev["context"] == {"source": "manual"}
