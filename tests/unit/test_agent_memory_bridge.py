"""Unit tests for the workspace-bridge agent-memory adapters (FR-MIND §10).

The bridge adapters are a thin client over the engine->workspace callback channel.
These tests use a fake client (no httpx, no network) to verify:

* JSON is mapped onto the port dataclasses both ways (memory/skills/recall);
* an OFF channel (``available()`` False) degrades to empty/no-op;
* a ``WorkspaceError`` from the client degrades to the same empty result and never
  escapes into the engine loop.
"""

from __future__ import annotations

import pytest

from applicant.adapters.memory.bridge import (
    WorkspaceBridgeMemoryStore,
    WorkspaceBridgeRecallIndex,
    WorkspaceBridgeSkillStore,
)
from applicant.ports.driven.memory_store import KIND_USER, MemoryEntry
from applicant.ports.driven.skill_store import Skill
from applicant.ports.driven.workspace import WorkspaceError


class FakeClient:
    """A WorkspacePort-shaped fake exposing the FR-MIND bridge methods."""

    def __init__(self, *, up=True, raise_error=False):
        self._up = up
        self._raise = raise_error
        self.calls = []

    def available(self):
        return self._up

    def _maybe_raise(self):
        if self._raise:
            raise WorkspaceError("down", status=502)

    def memory_snapshot(self, *, owner=None, scope=None, campaign_id=None):
        self._maybe_raise()
        return {
            "environment": [{"text": "Acme uses Workday", "kind": "environment"}],
            "user": [{"text": "Concise notes", "kind": "user"}],
            "truncated": True,
        }

    def memory_add(self, *, owner=None, body):
        self._maybe_raise()
        self.calls.append(("add", body))
        return {"ok": True}

    def memory_replace(self, *, owner=None, body):
        self._maybe_raise()
        return {"replaced": True}

    def memory_remove(self, *, owner=None, body):
        self._maybe_raise()
        return {"removed": 3}

    def skills_list(self, *, owner=None, scope=None, campaign_id=None):
        self._maybe_raise()
        return {"skills": [{"name": "acme", "description": "tenant flow"}]}

    def skill_load(self, name, *, owner=None):
        self._maybe_raise()
        return {"name": name, "procedure": ["one", "two"]}

    def skill_create(self, *, owner=None, body):
        self._maybe_raise()
        self.calls.append(("create", body))
        return body

    def skill_patch(self, name, *, owner=None, body):
        self._maybe_raise()
        return {"name": name, **body}

    def skill_edit(self, name, *, owner=None, body):
        self._maybe_raise()
        return {"name": name, **body}

    def skill_delete(self, name, *, owner=None):
        self._maybe_raise()
        return {"deleted": True}

    def recall(self, *, query, owner=None, limit=5, scope=None, campaign_id=None):
        self._maybe_raise()
        return {"hits": [{"run_id": "r1", "text": "Acme uses Workday", "score": 0.9}]}


# --- memory ---------------------------------------------------------------

def test_memory_snapshot_maps_json():
    store = WorkspaceBridgeMemoryStore(FakeClient())
    snap = store.snapshot()
    assert snap.environment[0].text == "Acme uses Workday"
    assert snap.user[0].kind == KIND_USER
    assert snap.truncated is True


def test_memory_writes_round_trip():
    client = FakeClient()
    store = WorkspaceBridgeMemoryStore(client)
    store.add(MemoryEntry(text="hi", kind="user"))
    assert client.calls[0][1]["kind"] == "user"
    assert store.replace("hi", MemoryEntry(text="bye")) is True
    assert store.remove("bye") == 3


def test_memory_offline_degrades_to_empty():
    store = WorkspaceBridgeMemoryStore(FakeClient(up=False))
    assert store.snapshot().all() == ()
    assert store.replace("x", MemoryEntry(text="y")) is False
    assert store.remove("x") == 0


def test_memory_workspace_error_degrades_not_raises():
    store = WorkspaceBridgeMemoryStore(FakeClient(raise_error=True))
    # Must NOT raise WorkspaceError into the engine loop.
    assert store.snapshot().all() == ()
    assert store.remove("x") == 0


# --- skills ---------------------------------------------------------------

def test_skills_list_load_and_writes():
    store = WorkspaceBridgeSkillStore(FakeClient())
    metas = store.list_skills()
    assert metas[0].name == "acme"
    skill = store.load("acme")
    assert skill is not None and skill.procedure == ("one", "two")
    assert store.delete("acme") is True


def test_skills_offline_degrades():
    store = WorkspaceBridgeSkillStore(FakeClient(up=False))
    assert store.list_skills() == ()
    assert store.load("acme") is None
    assert store.delete("acme") is False


def test_skill_create_returns_input_skill():
    store = WorkspaceBridgeSkillStore(FakeClient())
    s = Skill(name="acme", procedure=("log in",))
    assert store.create(s) is s  # the adapter returns the authored skill


# --- recall ----------------------------------------------------------------

def test_recall_maps_hits_and_bounds():
    idx = WorkspaceBridgeRecallIndex(FakeClient())
    hits = idx.search("workday", limit=5)
    assert hits[0].run_id == "r1"
    assert hits[0].score == pytest.approx(0.9)


def test_recall_offline_and_error_degrade():
    assert WorkspaceBridgeRecallIndex(FakeClient(up=False)).search("q") == ()
    assert WorkspaceBridgeRecallIndex(FakeClient(raise_error=True)).search("q") == ()
