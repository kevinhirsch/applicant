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
    resp = client.get(
        "/api/applicant/internal/calendar/interviews",
        headers={INTERNAL_TOKEN_HEADER: TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"interviews": []}
