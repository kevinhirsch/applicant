"""Coverage: composition root factories (src/applicant/app/container.py).

The default test lane uses in-memory storage, so the DB-only closures — the per-request
service factory (CONC-REQ-1) and the per-tick service factory (CONC-2) — are never built
or invoked and stay uncovered. Here we build a container against a real (SQLite) DB so
``session_factory`` is non-None, then invoke both factories and assert they return
fully-wired, SESSION-ISOLATED storage-bound service bundles (a fresh Session per
call/tick, distinct from the container singleton's storage).
"""

from __future__ import annotations

import tempfile

import pytest

from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine
from applicant.app.config import Settings
from applicant.app.container import build_container


@pytest.fixture
def sqlite_container():
    """A container wired against a real SQLite DB (so the DB-only factories exist)."""
    db = tempfile.mktemp(suffix=".db")
    url = f"sqlite:///{db}"
    # Create the schema so the chosen SqlAlchemyStorage is genuinely usable.
    engine = make_engine(url)
    Base.metadata.create_all(engine)
    engine.dispose()
    settings = Settings(DATABASE_URL=url)
    return build_container(settings)


def test_db_container_selects_sqlalchemy_storage(sqlite_container):
    # A reachable DB means SqlAlchemyStorage (not the in-memory fallback) + a factory.
    from applicant.adapters.storage.repositories import SqlAlchemyStorage

    assert isinstance(sqlite_container.storage, SqlAlchemyStorage)
    assert sqlite_container.session_factory is not None
    assert sqlite_container.request_services_factory is not None


def test_request_services_factory_builds_isolated_bundle(sqlite_container):
    services = sqlite_container.request_services_factory()
    try:
        # The bundle exposes every per-request storage-bound service the deps resolve.
        expected = {
            "storage",
            "pending_actions_service",
            "digest_service",
            "attribute_cloud_service",
            "feedback_service",
            "chat_service",
            "admin_query_service",
            "submission_service",
            "prefill_service",
            "material_service",
            "criteria_service",
            "campaign_service",
            "conversion_service",
            "scoring_service",
            "learning_service",
        }
        assert expected.issubset(services.keys())
        # Session isolation: the per-request storage is a DISTINCT object bound to a
        # fresh Session, not the container singleton's storage (CONC-REQ-1).
        assert services["storage"] is not sqlite_container.storage
        assert services["_session"] is not None
    finally:
        services["_session"].close()


def test_request_services_each_call_gets_a_fresh_session(sqlite_container):
    a = sqlite_container.request_services_factory()
    b = sqlite_container.request_services_factory()
    try:
        # Two requests -> two distinct Sessions + storages (no interleaving, CONC-REQ-1).
        assert a["_session"] is not b["_session"]
        assert a["storage"] is not b["storage"]
    finally:
        a["_session"].close()
        b["_session"].close()


def test_request_services_bundle_is_functional(sqlite_container):
    """The per-request campaign service actually works against its own Session
    (proves the bundle is wired, not just constructed)."""
    services = sqlite_container.request_services_factory()
    try:
        created = services["campaign_service"].create_campaign("Backend roles")
        # The campaign persisted through the request-scoped storage.
        listed = services["campaign_service"].list_campaigns()
        assert any(c.id == created.id for c in listed)
    finally:
        services["_session"].close()


def test_scheduler_tick_factory_builds_isolated_bundle(sqlite_container):
    """CONC-2: the scheduler's per-tick factory builds a fresh Session-backed bundle
    (the 24/7 thread must never share the request Session)."""
    scheduler = sqlite_container.scheduler
    factory = scheduler._tick_services_factory
    assert factory is not None
    services = factory()
    try:
        assert "agent_loop" in services
        assert services["storage"] is not sqlite_container.storage
        assert services["_session"] is not None
    finally:
        services["_session"].close()
