"""Hermetic tests for Stage 2.5 lane A — calendar interview detection
(routes/applicant_internal_routes.py::calendar_interviews + helpers).

Two layers, both DB-free:

1. The pure heuristic (``detect_interviews`` / ``_detect_interview`` /
   ``_detect_company``) over raw event dicts, incl. NEGATIVE cases so generic
   meetings ("screen share", "standup call") are NOT flagged.
2. The token-gated, owner-scoped route with the calendar layer FAKED — the
   handler's ``_read_owner_calendar_events`` is monkeypatched so no DB/network
   is touched and we can assert owner scoping is honored.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes import applicant_internal_routes as ir
from routes.applicant_internal_routes import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    detect_interviews,
    setup_applicant_internal_routes,
)

TOKEN = "s" * 64


# ── 1. Pure heuristic ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "title,notes",
    [
        ("Interview with Acme Corp", ""),
        ("Phone screen", ""),
        ("Technical Interview — Data Eng", ""),
        ("Onsite", ""),
        ("Panel interview", ""),
        ("Recruiter call", ""),
        ("Coffee chat", "Recruiter screen for the backend role"),  # notes match
        ("Final round", ""),
    ],
)
def test_detects_interview_positive(title, notes):
    out = detect_interviews([{"title": title, "notes": notes, "start": "2026-07-01T10:00:00"}])
    assert len(out) == 1
    assert out[0]["detected_kind"]


@pytest.mark.parametrize(
    "title,notes",
    [
        ("Screen share with design", ""),          # "screen" w/o hiring context
        ("Standup call", ""),                       # "call" w/o hiring context
        ("Winterview planning", ""),                # substring, not whole-word
        ("Take a screenshot for the deck", ""),     # "screen" substring
        ("Sprint round-up", ""),                    # "round" w/o hiring context
        ("Lunch with Sara", ""),
        ("Dentist appointment", ""),
        ("", ""),
    ],
)
def test_does_not_flag_non_interviews(title, notes):
    out = detect_interviews([{"title": title, "notes": notes, "start": "2026-07-01T10:00:00"}])
    assert out == []


def test_weak_signal_needs_hiring_context():
    # "screen" alone -> no; "screen" + a hiring word -> yes.
    assert detect_interviews([{"title": "Screen share", "start": "x"}]) == []
    hit = detect_interviews([{"title": "Candidate screen", "start": "x"}])
    assert len(hit) == 1 and hit[0]["detected_kind"] == "screen"


def test_company_extraction():
    out = detect_interviews([{"title": "Interview with Acme Corp", "start": "x"}])
    assert out[0]["detected_company"] == "Acme Corp"
    out2 = detect_interviews([{"title": "Globex Inc onsite", "start": "x"}])
    assert out2[0]["detected_company"] == "Globex Inc"
    # No discernible company -> None (never invents one).
    out3 = detect_interviews([{"title": "Phone screen", "start": "x"}])
    assert out3[0]["detected_company"] is None


def test_link_extraction_from_location_and_notes():
    out = detect_interviews(
        [{"title": "Interview", "location": "https://zoom.us/j/123", "start": "x"}]
    )
    assert out[0]["link"] == "https://zoom.us/j/123"
    out2 = detect_interviews(
        [{"title": "Interview", "notes": "join: https://meet.google.com/abc-def.", "start": "x"}]
    )
    assert out2[0]["link"] == "https://meet.google.com/abc-def"


def test_output_shape_and_cap():
    raw = [
        {"title": f"Interview {i}", "start": f"2026-07-{i:02d}T10:00:00", "end": "x",
         "location": "Office", "calendar": "Personal"}
        for i in range(1, 40)
    ]
    out = detect_interviews(raw)
    assert len(out) == ir.CALENDAR_INTERVIEW_MAX  # bounded
    ev = out[0]
    assert set(ev) == {
        "title", "start", "end", "all_day", "location", "link",
        "detected_company", "detected_kind", "calendar",
    }


# ── 2. Route (token-gated, owner-scoped, calendar layer faked) ────────────

@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup_applicant_internal_routes())
    return TestClient(app)


@pytest.fixture
def fake_calendar(monkeypatch):
    """Replace the DB reader with an owner-keyed in-memory fake."""
    by_owner = {
        "kevin": [
            {"title": "Interview with Acme", "start": "2026-07-01T10:00:00",
             "notes": "", "location": "https://zoom.us/j/9", "calendar": "Personal"},
            {"title": "Dentist", "start": "2026-07-02T09:00:00"},  # not an interview
        ],
        "other": [
            {"title": "Onsite at Globex", "start": "2026-07-03T10:00:00"},
        ],
    }
    seen = {}

    def _fake(owner):
        seen["owner"] = owner
        return by_owner.get(owner, [])

    monkeypatch.setattr(ir, "_read_owner_calendar_events", _fake)
    return seen


def test_calendar_interviews_requires_token(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    assert client.get("/api/applicant/internal/calendar/interviews").status_code == 403
    bad = client.get(
        "/api/applicant/internal/calendar/interviews",
        headers={INTERNAL_TOKEN_HEADER: "wrong"},
    )
    assert bad.status_code == 403


def test_calendar_interviews_disabled_without_secret(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_INTERNAL_TOKEN", raising=False)
    resp = client.get(
        "/api/applicant/internal/calendar/interviews",
        headers={INTERNAL_TOKEN_HEADER: TOKEN},
    )
    assert resp.status_code == 403


def test_calendar_interviews_owner_scoped(client, monkeypatch, fake_calendar):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    resp = client.get(
        "/api/applicant/internal/calendar/interviews",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # Only the interview-like event survives detection; dentist is dropped.
    assert [iv["title"] for iv in body["interviews"]] == ["Interview with Acme"]
    assert body["interviews"][0]["detected_company"] == "Acme"
    assert body["interviews"][0]["link"] == "https://zoom.us/j/9"
    # The reader was scoped to the attributed owner — never the body.
    assert fake_calendar["owner"] == "kevin"


def test_calendar_interviews_db_failure_degrades(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)

    def _boom(owner):
        raise RuntimeError("db down")

    monkeypatch.setattr(ir, "_read_owner_calendar_events", _boom)
    # Owner attribution is now required (#230); test with valid owner so
    # we exercise the DB-failure degradation path, not the auth gate.
    resp = client.get(
        "/api/applicant/internal/calendar/interviews",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "someone"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"interviews": []}


# ── 3. POST /calendar/events — write-back (dark-engine audit item 69) ────
#
# Real SQLAlchemy models (``core.database.CalendarEvent``/``CalendarCal``)
# against an in-memory sqlite DB shared across the ``SessionLocal()`` calls the
# route makes (StaticPool keeps one connection alive so writes from one request
# are visible to the next -- required to exercise the dedupe/update path).
# Never touches the real file-based DB the app is configured with.

sqlalchemy = pytest.importorskip("sqlalchemy")


@pytest.fixture
def db_engine(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    # ``core.database`` runs ``init_db()`` (creates all tables) at MODULE IMPORT
    # time against ``DATABASE_URL`` (default ``sqlite:///./data/app.db``,
    # relative to cwd). None of the ``test_applicant_*`` tests import it before
    # this one, so this is the first real import in this process — set an
    # in-memory URL first so that one-time init never touches (or requires) a
    # real ``data/`` directory on disk. Harmless if the module was already
    # imported (module caching means the env var is simply unused then).
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    import core.database as core_db

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    core_db.Base.metadata.create_all(engine)
    monkeypatch.setattr(core_db, "SessionLocal", sessionmaker(bind=engine))
    return engine


def _events(engine):
    import core.database as core_db
    from sqlalchemy.orm import sessionmaker

    db = sessionmaker(bind=engine)()
    try:
        return list(db.query(core_db.CalendarEvent).all())
    finally:
        db.close()


def _calendar(engine, calendar_id):
    import core.database as core_db
    from sqlalchemy.orm import sessionmaker

    db = sessionmaker(bind=engine)()
    try:
        return db.query(core_db.CalendarCal).filter(core_db.CalendarCal.id == calendar_id).first()
    finally:
        db.close()


def test_calendar_create_event_requires_token(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    resp = client.post(
        "/api/applicant/internal/calendar/events",
        json={"title": "Interview", "start": "2026-07-10T09:00:00"},
    )
    assert resp.status_code == 403


def test_calendar_create_event_disabled_without_secret(client, monkeypatch):
    monkeypatch.delenv("APPLICANT_INTERNAL_TOKEN", raising=False)
    resp = client.post(
        "/api/applicant/internal/calendar/events",
        headers={INTERNAL_TOKEN_HEADER: TOKEN},
        json={"title": "Interview", "start": "2026-07-10T09:00:00"},
    )
    assert resp.status_code == 403


def test_calendar_create_event_requires_title_and_start(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    h = {INTERNAL_TOKEN_HEADER: TOKEN}
    assert client.post(
        "/api/applicant/internal/calendar/events", headers=h, json={"start": "x"}
    ).status_code == 400
    assert client.post(
        "/api/applicant/internal/calendar/events", headers=h, json={"title": "Interview"}
    ).status_code == 400


def test_calendar_create_event_creates_a_real_row(client, monkeypatch, db_engine):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    resp = client.post(
        "/api/applicant/internal/calendar/events",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
        json={
            "title": "Interview invite: Acme Corp",
            "start": "2026-07-10T00:00:00",
            "all_day": True,
            "notes": "Detected from an email",
            "location": "https://example.com/job",
            "dedupe_key": "app-1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["created"] is True
    uid = body["uid"]

    rows = _events(db_engine)
    assert len(rows) == 1
    ev = rows[0]
    assert ev.uid == uid
    assert ev.summary == "Interview invite: Acme Corp"
    assert ev.description == "Detected from an email"
    assert ev.location == "https://example.com/job"
    assert ev.all_day is True
    # It landed on the owner's default calendar — reused from the native
    # calendar create path (calendar_routes._ensure_default_calendar), not a
    # hand-rolled "Applicant" calendar.
    cal = _calendar(db_engine, ev.calendar_id)
    assert cal.owner == "kevin"
    assert cal.name == "Personal"


def test_calendar_create_event_is_idempotent_on_dedupe_key(client, monkeypatch, db_engine):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    h = {INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"}
    first = client.post(
        "/api/applicant/internal/calendar/events",
        headers=h,
        json={
            "title": "Interview invite: Acme Corp",
            "start": "2026-07-10T00:00:00",
            "all_day": True,
            "dedupe_key": "app-1",
        },
    )
    assert first.json()["created"] is True
    uid1 = first.json()["uid"]

    # Re-detection of the SAME application updates the one event instead of
    # creating a second — no duplicate lands on the calendar.
    second = client.post(
        "/api/applicant/internal/calendar/events",
        headers=h,
        json={
            "title": "Interview invite: Acme Corp (updated)",
            "start": "2026-07-11T00:00:00",
            "all_day": True,
            "dedupe_key": "app-1",
        },
    )
    assert second.status_code == 200
    assert second.json()["created"] is False
    assert second.json()["uid"] == uid1

    rows = _events(db_engine)
    assert len(rows) == 1
    assert rows[0].summary == "Interview invite: Acme Corp (updated)"

    # A DIFFERENT dedupe_key creates a second, independent event.
    third = client.post(
        "/api/applicant/internal/calendar/events",
        headers=h,
        json={"title": "Interview invite: Globex", "start": "2026-07-12T00:00:00", "dedupe_key": "app-2"},
    )
    assert third.json()["created"] is True
    assert len(_events(db_engine)) == 2


def test_calendar_create_event_without_dedupe_key_always_creates(client, monkeypatch, db_engine):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    h = {INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"}
    for _ in range(2):
        resp = client.post(
            "/api/applicant/internal/calendar/events",
            headers=h,
            json={"title": "Interview", "start": "2026-07-10T09:00:00"},
        )
        assert resp.json()["created"] is True
    assert len(_events(db_engine)) == 2


def test_calendar_create_event_db_failure_degrades_to_502(client, monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")  # see db_engine fixture

    def _boom():
        raise RuntimeError("db down")

    import core.database as core_db

    monkeypatch.setattr(core_db, "SessionLocal", _boom)
    resp = client.post(
        "/api/applicant/internal/calendar/events",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
        json={"title": "Interview", "start": "2026-07-10T09:00:00"},
    )
    assert resp.status_code == 502
