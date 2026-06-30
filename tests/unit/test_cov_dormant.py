"""Dormant-surface registry + seeding coverage (FR-UI-2).

Two halves:

* **Registry invariants** — every entry is well-formed, keys are unique, statuses
  are one of the two allowed values, and the live/dormant split matches the spec
  (only ``multi_campaign_switcher`` ships grayed).
* **Seeding** — ``seed_dormant_surfaces`` tolerates no-DB (returns the count) AND,
  when given a real session, upserts one row per surface idempotently. The DB path
  is hermetic on SQLite (no Postgres).
"""

from __future__ import annotations

import tempfile

import pytest

from applicant.dormant import (
    DORMANT_SURFACES,
    STATUS_DORMANT,
    STATUS_LIVE,
    DormantSurface,
    seed_dormant_surfaces,
)


# === registry invariants ===================================================
def test_every_surface_is_wellformed():
    for s in DORMANT_SURFACES:
        assert isinstance(s, DormantSurface)
        assert s.key and isinstance(s.key, str)
        assert s.surface_name
        assert isinstance(s.requirement_ids, tuple) and s.requirement_ids
        assert all(rid.startswith(("FR-", "NFR-")) for rid in s.requirement_ids)
        assert s.wiring_notes
        assert isinstance(s.live_phase, int) and s.live_phase >= 1
        assert s.status in (STATUS_LIVE, STATUS_DORMANT)


def test_surface_keys_are_unique():
    keys = [s.key for s in DORMANT_SURFACES]
    assert len(keys) == len(set(keys))


def test_only_expected_surfaces_remain_genuinely_dormant():
    # The only genuinely-grayed surface is the multi-campaign switcher (MVP-1 runs a
    # single campaign). resume_aggressiveness was promoted to live in #187.
    # FR-MIND's agent-learning surfaces and FR-CUA's desktop assist are wired end-to-end
    # and registered LIVE; desktop assist is additionally CAPABILITY-gated at runtime
    # (it shows locked until COMPUTER_USE_BACKEND=cua and the desktop driver is baked
    # into the sandbox image so the health preflight passes), which is a runtime gate,
    # not a dormant-registry flag.
    dormant_keys = {s.key for s in DORMANT_SURFACES if s.status == STATUS_DORMANT}
    assert dormant_keys == {
        "multi_campaign_switcher",
    }


def test_dormant_surface_is_frozen():
    import dataclasses

    s = DORMANT_SURFACES[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.status = "mutated"  # type: ignore[misc]


def test_default_status_is_dormant():
    # A surface constructed without an explicit status defaults to dormant
    # (no dead UI ever ships as if live).
    s = DormantSurface(
        key="k", surface_name="n", requirement_ids=("FR-X-1",), wiring_notes="w", live_phase=1
    )
    assert s.status == STATUS_DORMANT


# === seeding: no-DB tolerance ==============================================
def test_seed_without_session_returns_count_without_persisting():
    # App boot in tests has no DB; seeding must still report the registered count.
    assert seed_dormant_surfaces(None) == len(DORMANT_SURFACES)


# === seeding: real DB upsert (hermetic SQLite) =============================
@pytest.fixture
def db_session():
    from applicant.adapters.storage.models import Base
    from applicant.adapters.storage.session import make_engine, make_session_factory

    db = tempfile.mktemp(suffix=".db")
    engine = make_engine(f"sqlite:///{db}")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_seed_persists_one_row_per_surface(db_session):
    from applicant.adapters.storage.models import DormantSurfaceBacklogModel

    count = seed_dormant_surfaces(db_session)
    db_session.commit()

    assert count == len(DORMANT_SURFACES)
    rows = db_session.query(DormantSurfaceBacklogModel).all()
    assert len(rows) == len(DORMANT_SURFACES)

    by_id = {r.id: r for r in rows}
    # Spot-check a known dormant surface and a known live one are persisted faithfully.
    aggro = by_id["resume_aggressiveness"]
    assert aggro.status == STATUS_LIVE, "resume_aggressiveness promoted to live in #187"
    assert "FR-RESUME-9" in aggro.requirement_ids
    assert aggro.wiring_notes["live_phase"] == 3
    assert "notes" in aggro.wiring_notes

    digest = by_id["digest_in_app"]
    assert digest.status == STATUS_LIVE


def test_seed_is_idempotent_upsert(db_session):
    from applicant.adapters.storage.models import DormantSurfaceBacklogModel

    seed_dormant_surfaces(db_session)
    db_session.commit()
    # Seeding again merges (upserts) rather than duplicating rows.
    seed_dormant_surfaces(db_session)
    db_session.commit()

    rows = db_session.query(DormantSurfaceBacklogModel).all()
    assert len(rows) == len(DORMANT_SURFACES)  # no duplicates after a re-seed
