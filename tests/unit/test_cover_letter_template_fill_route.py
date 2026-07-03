"""Regression coverage: cover-letter template merge-fill (dark-engine audit item 41).

``POST /api/documents/cover-letter/fill`` wraps
``MaterialService.fill_cover_letter_template`` — pure, deterministic ``{{field}}``
substitution, no LLM call. Complementary to the on-demand LLM draft at
``POST /api/documents/cover-letter``: a user reusing their OWN saved template
instead of generating one fresh. Hermetic: in-memory storage, no TeX/LLM.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        # Open the LLM gate (FR-UI-5) so the documents router is reachable.
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_fill_substitutes_known_merge_fields(client):
    res = client.post(
        "/api/documents/cover-letter/fill",
        json={
            "template": "Dear {{company}}, I am applying for {{role}}.",
            "context": {"company": "Acme", "role": "Engineer"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["filled"] == "Dear Acme, I am applying for Engineer."
    # Pure substitution: no placeholder braces leak through.
    assert "{{" not in body["filled"]


def test_fill_blanks_unknown_placeholders_instead_of_leaking(client):
    """A partial context never produces broken output: an unmatched field is
    replaced with an empty string, not the raw ``{{...}}`` token."""
    res = client.post(
        "/api/documents/cover-letter/fill",
        json={"template": "Dear {{company}}, re: {{missing_field}}.", "context": {"company": "Acme"}},
    )
    assert res.status_code == 200
    filled = res.json()["filled"]
    assert filled == "Dear Acme, re: ."
    assert "{{" not in filled and "}}" not in filled


def test_fill_tolerates_whitespace_inside_braces(client):
    res = client.post(
        "/api/documents/cover-letter/fill",
        json={"template": "Hello {{ name }}!", "context": {"name": "Jordan"}},
    )
    assert res.status_code == 200
    assert res.json()["filled"] == "Hello Jordan!"


def test_fill_defaults_context_to_empty(client):
    """``context`` is optional; an omitted context blanks every placeholder rather
    than 400ing (a template with no context is a valid, if unhelpful, request)."""
    res = client.post(
        "/api/documents/cover-letter/fill",
        json={"template": "Dear {{company}},"},
    )
    assert res.status_code == 200
    assert res.json()["filled"] == "Dear ,"


def test_fill_never_creates_a_document(client):
    """No LLM call, no fabrication path -- the fill is a pure computation, not
    routed through the review-gated document library (unlike /cover-letter)."""
    aid = "app-fill-noop"
    before = client.get(f"/api/documents/applications/{aid}/").json()
    client.post(
        "/api/documents/cover-letter/fill",
        json={"template": "Dear {{company}},", "context": {"company": "Acme"}},
    )
    after = client.get(f"/api/documents/applications/{aid}/").json()
    assert before["items"] == after["items"] == []
