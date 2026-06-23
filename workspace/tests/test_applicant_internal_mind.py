"""Hermetic tests for the FR-MIND agent-memory bridge endpoints
(routes/applicant_internal_routes.py) the ENGINE calls.

The engine reaches the front-door memory/skills substrate over the token-gated
/api/applicant/internal/* channel (§10). These tests mount only the internal
router on a bare app, inject fake MemoryManager / SkillsManager via app.state
(mirroring how app.py wires the real ones), and exercise:

* token gating (no token -> 403, correct token -> 200);
* owner-scoped memory snapshot / add / replace / remove round-trips;
* skills list / create / delete;
* recall over stored memories;
* graceful degradation when a manager is absent (empty, never 500).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.applicant_internal_routes import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    setup_applicant_internal_routes,
)

TOKEN = "s" * 64
PREFIX = "/api/applicant/internal"


class FakeMemoryManager:
    def __init__(self):
        self.entries = []

    def load_all(self):
        return self.entries

    def load(self, owner=None):
        if owner is None:
            return self.entries
        return [e for e in self.entries if e.get("owner") == owner]

    def add_entry(self, text, source="user", category="fact", owner=None):
        e = {"id": f"m{len(self.entries)}", "text": text, "source": source, "category": category}
        if owner:
            e["owner"] = owner
        return e

    def save(self, entries):
        self.entries = entries

    def get_relevant_memories(self, query, memories, threshold=0.05, max_items=8):
        q = query.lower()
        return [m for m in memories if q in (m.get("text") or "").lower()][:max_items]


class FakeSkillsManager:
    def __init__(self):
        self.skills = []

    def load(self, owner=None):
        if owner is None:
            return self.skills
        return [s for s in self.skills if s.get("owner") == owner]

    def add_skill(self, **kw):
        sk = {
            "name": kw.get("name") or "skill",
            "description": kw.get("description") or "",
            "when_to_use": kw.get("when_to_use") or "",
            "procedure": list(kw.get("procedure") or []),
            "source": kw.get("source") or "learned",
            "owner": kw.get("owner"),
        }
        self.skills.append(sk)
        return sk

    def update_skill(self, name, updates, owner=None):
        for s in self.skills:
            if s.get("name") == name and (s.get("owner") or "") == (owner or ""):
                s.update(updates)
                return True
        return False

    def delete_skill(self, name, owner=None):
        before = len(self.skills)
        self.skills = [
            s for s in self.skills
            if not (s.get("name") == name and (s.get("owner") or "") == (owner or ""))
        ]
        return len(self.skills) < before


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    app = FastAPI()
    app.state.memory_manager = FakeMemoryManager()
    app.state.skills_manager = FakeSkillsManager()
    app.include_router(setup_applicant_internal_routes())
    return TestClient(app)


def _h(owner=None):
    h = {INTERNAL_TOKEN_HEADER: TOKEN}
    if owner:
        h[INTERNAL_OWNER_HEADER] = owner
    return h


def test_memory_endpoints_require_token(app_client):
    assert app_client.get(f"{PREFIX}/memory/snapshot").status_code == 403


def test_memory_add_snapshot_replace_remove(app_client):
    # add (user kind -> user tier)
    r = app_client.post(f"{PREFIX}/memory/add",
                        json={"text": "Prefers concise notes", "kind": "user"}, headers=_h("kev"))
    assert r.status_code == 200 and r.json()["ok"] is True
    app_client.post(f"{PREFIX}/memory/add",
                   json={"text": "Acme uses Workday", "kind": "environment"}, headers=_h("kev"))

    snap = app_client.get(f"{PREFIX}/memory/snapshot", headers=_h("kev")).json()
    assert any("Workday" in e["text"] for e in snap["environment"])
    assert any("concise" in e["text"] for e in snap["user"])

    rep = app_client.post(f"{PREFIX}/memory/replace",
                         json={"find": "Workday", "entry": {"text": "Acme uses Greenhouse"}},
                         headers=_h("kev")).json()
    assert rep["replaced"] is True

    rem = app_client.post(f"{PREFIX}/memory/remove",
                         json={"find": "Greenhouse"}, headers=_h("kev")).json()
    assert rem["removed"] == 1


def test_memory_scoped_by_owner(app_client):
    app_client.post(f"{PREFIX}/memory/add", json={"text": "kev secret"}, headers=_h("kev"))
    other = app_client.get(f"{PREFIX}/memory/snapshot", headers=_h("mallory")).json()
    assert other["environment"] == [] and other["user"] == []


def test_skills_create_list_delete(app_client):
    created = app_client.post(f"{PREFIX}/skills",
                             json={"name": "acme-flow", "description": "Acme tenant",
                                   "procedure": ["log in"]}, headers=_h("kev")).json()
    assert created["name"] == "acme-flow"
    listed = app_client.get(f"{PREFIX}/skills", headers=_h("kev")).json()
    assert listed["skills"][0]["name"] == "acme-flow"
    got = app_client.get(f"{PREFIX}/skills/acme-flow", headers=_h("kev")).json()
    assert got["procedure"] == ["log in"]
    deleted = app_client.delete(f"{PREFIX}/skills/acme-flow", headers=_h("kev")).json()
    assert deleted["deleted"] is True


def test_recall_over_memories(app_client):
    app_client.post(f"{PREFIX}/memory/add", json={"text": "Acme uses Workday"}, headers=_h("kev"))
    hits = app_client.get(f"{PREFIX}/recall", params={"q": "workday"}, headers=_h("kev")).json()
    assert hits["hits"] and "Workday" in hits["hits"][0]["text"]


def test_degrades_when_manager_absent(monkeypatch):
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    app = FastAPI()  # no memory_manager / skills_manager on state
    app.include_router(setup_applicant_internal_routes())
    c = TestClient(app)
    assert c.get(f"{PREFIX}/memory/snapshot", headers=_h()).json() == {
        "environment": [], "user": [], "truncated": False}
    assert c.get(f"{PREFIX}/skills", headers=_h()).json() == {"skills": []}
