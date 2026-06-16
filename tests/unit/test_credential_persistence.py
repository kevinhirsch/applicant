"""Credential persistence + campaign scoping (FR-VAULT-1/3, FR-CRIT-4, NFR-PRIV-1).

Proves the FR-VAULT-1 deviation fix: sealed credentials now survive a "restart"
(a fresh store instance against the same DB) instead of living only in a dict.
"""

from __future__ import annotations

import logging
import tempfile

import pytest

from applicant.adapters.credentials.pg_credential_store import (
    InMemoryCredentialStore,
    PgCredentialStore,
)
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.core.ids import CampaignId, new_id
from applicant.ports.driven.credential_store import Credential


@pytest.fixture
def session_factory():
    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    yield make_session_factory(engine)
    engine.dispose()


def test_sealed_credential_survives_restart(tmp_path, session_factory):
    # FR-VAULT-1/3: seal -> persist -> reopen a FRESH store -> unseal round-trip.
    keyfile = str(tmp_path / "master.key")
    cid = CampaignId(new_id())

    first = PgCredentialStore(keyfile, session_factory=session_factory)
    first.store(cid, Credential(tenant_key="acme.workday", username="kev", secret="s3cret"))

    # A brand-new instance (simulating a process restart): empty in-memory cache,
    # same key-file, same DB — it must still unseal the persisted row.
    second = PgCredentialStore(keyfile, session_factory=session_factory)
    assert second._store == {}, "fresh instance starts with an empty cache"
    got = second.retrieve(cid, "acme.workday")
    assert got is not None
    assert got.username == "kev" and got.secret == "s3cret"
    assert "acme.workday" in second.list_tenants(cid)


def test_credentials_are_campaign_scoped(tmp_path, session_factory):
    # FR-CRIT-4: same site, two campaigns, isolated values.
    keyfile = str(tmp_path / "master.key")
    c1 = CampaignId(new_id())
    c2 = CampaignId(new_id())
    store = PgCredentialStore(keyfile, session_factory=session_factory)
    store.store(c1, Credential(tenant_key="acme.workday", username="u1", secret="secret-one"))
    store.store(c2, Credential(tenant_key="acme.workday", username="u2", secret="secret-two"))

    # A fresh instance reads each campaign's own value back, never crossing over.
    fresh = PgCredentialStore(keyfile, session_factory=session_factory)
    assert fresh.retrieve(c1, "acme.workday").secret == "secret-one"
    assert fresh.retrieve(c2, "acme.workday").secret == "secret-two"


def test_secret_never_logged_or_in_repr(tmp_path, session_factory, caplog):
    # NFR-PRIV-1: secrets never appear in logs or repr.
    keyfile = str(tmp_path / "master.key")
    cid = CampaignId(new_id())
    store = PgCredentialStore(keyfile, session_factory=session_factory)
    with caplog.at_level(logging.DEBUG):
        store.store(cid, Credential(tenant_key="acme.workday", username="kev", secret="topsecret"))
    assert "topsecret" not in caplog.text
    assert "kev" not in caplog.text
    assert "topsecret" not in repr(store)


def test_credentials_model_has_campaign_tenant_unique_constraint():
    """schema/model parity: the ORM model (SQLite create_all lane) must carry the
    same uq_credentials_campaign_tenant unique constraint the alembic migration
    (Postgres lane) creates, or the two lanes diverge."""
    from sqlalchemy import UniqueConstraint

    from applicant.adapters.storage.models import CredentialModel

    uniques = {
        tuple(c.name for c in con.columns): con.name
        for con in CredentialModel.__table__.constraints
        if isinstance(con, UniqueConstraint)
    }
    assert ("campaign_id", "tenant_key") in uniques
    assert uniques[("campaign_id", "tenant_key")] == "uq_credentials_campaign_tenant"


def test_rebanking_same_campaign_tenant_is_upsert_not_duplicate(tmp_path, session_factory):
    """FR-CRIT-4: re-banking the same (campaign, tenant) updates in place — the unique
    constraint keeps both the SQLite and Postgres lanes to one row per pair."""
    from applicant.adapters.storage.models import CredentialModel

    keyfile = str(tmp_path / "master.key")
    cid = CampaignId(new_id())
    store = PgCredentialStore(keyfile, session_factory=session_factory)
    store.store(cid, Credential(tenant_key="acme.workday", username="u1", secret="first"))
    store.store(cid, Credential(tenant_key="acme.workday", username="u2", secret="second"))

    session = session_factory()
    try:
        rows = (
            session.query(CredentialModel)
            .filter(CredentialModel.campaign_id == str(cid))
            .all()
        )
        assert len(rows) == 1  # upsert, not a second row
    finally:
        session.close()

    fresh = PgCredentialStore(keyfile, session_factory=session_factory)
    assert fresh.retrieve(cid, "acme.workday").secret == "second"


def test_in_memory_fallback_round_trip(tmp_path):
    # The no-DB fallback still seals + round-trips (hermetic boot path).
    keyfile = str(tmp_path / "master.key")
    cid = CampaignId(new_id())
    store = InMemoryCredentialStore(keyfile)
    store.store(cid, Credential(tenant_key="t1", username="u", secret="s"))
    got = store.retrieve(cid, "t1")
    assert got is not None and got.secret == "s"
    # Sealed at rest (NFR-PRIV-1): the internal record never equals plaintext.
    for rec in store._store.values():
        assert "s" not in rec["secret"] or rec["secret"] != "s"
