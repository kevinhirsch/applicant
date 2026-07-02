"""Regression: the automated-work gate's 409 detail is white-labeled (no FR- code).

``require_automated_work`` (src/applicant/app/deps.py) used to append a parenthetical
requirement-code reference — ``(FR-ONBOARD-2, FR-OOBE-3)`` — to the user-facing 409
detail string. Per CLAUDE.md working principle #3 ("White-label, always: Zero ...
FR-/NFR- jargon in user-facing strings ... The CI white-label check ... fails the
build on any match"), that leak has been stripped from the message. This guards
against ANY future regression of the same class (a general ``FR-<LETTERS>-<N>``
pattern), not just the two specific codes that were previously present.

Hermetic: in-memory storage/container (no real DB, no network) — matches the
``llm_client`` pattern used by ``tests/unit/test_cov_digest.py``.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app

#: Matches any FR-XXXX-N style requirement code, e.g. FR-ONBOARD-2, FR-OOBE-3,
#: FR-PREFILL-5 — a general safety net, not just the two codes that were removed.
_FR_CODE_RE = re.compile(r"FR-[A-Z]+-\d+")


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def llm_client(app):
    """LLM gate open only — NOT the full automated-work gate.

    ``require_automated_work`` 409s until the LLM is configured AND onboarding is
    complete; configuring only the LLM (and leaving onboarding incomplete) is
    exactly what keeps the automated-work gate closed so its 409 fires, mirroring
    ``tests/unit/test_cov_digest.py::llm_client``.
    """
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.1",
            },
        )
        assert r.status_code == 204
        yield c


def test_automated_work_gate_409_detail_has_no_fr_code(llm_client):
    """/api/digest/{id} is gated by ``require_automated_work``; LLM-only is not
    enough (onboarding is incomplete), so it 409s. The detail text must be plain
    language for the front-door — no FR-XXXX-N requirement code leaked to the user.
    """
    res = llm_client.get("/api/digest/camp-x")
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert not _FR_CODE_RE.search(detail), f"leaked requirement code in: {detail!r}"
    # Regression pins: the two specific codes that used to be appended are gone.
    assert "FR-ONBOARD-2" not in detail
    assert "FR-OOBE-3" not in detail
    # And the message still says something useful to the user.
    assert "onboarding" in detail.lower()


def test_automated_work_gate_409_detail_clean_across_gated_endpoints(llm_client):
    """The fix lives in the SHARED ``require_automated_work`` dependency, so every
    409 it produces — across every router that applies it — must be clean, not
    just one call site."""
    for method, path in (
        ("GET", "/api/digest/camp-x"),
        ("POST", "/api/digest/camp-x/deliver"),
        ("GET", "/api/digest/camp-x/email"),
    ):
        res = llm_client.request(method, path)
        assert res.status_code == 409
        detail = res.json()["detail"]
        assert not _FR_CODE_RE.search(detail), f"leaked requirement code in: {detail!r}"
