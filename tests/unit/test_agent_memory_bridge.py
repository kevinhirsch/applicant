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
        self.calls.append(("snapshot", {"scope": scope, "campaign_id": campaign_id}))
        self._maybe_raise()
        return {
            "environment": [{"text": "Acme uses Workday", "kind": "environment"}],
            "user": [{"text": "Concise notes", "kind": "user"}],
            "truncated": True,
        }

    def memory_add(self, *, owner=None, body):
        self.calls.append(("add", body))
        self._maybe_raise()
        return {"ok": True}

    def memory_replace(self, *, owner=None, body):
        self.calls.append(("replace", body))
        self._maybe_raise()
        return {"replaced": True}

    def memory_remove(self, *, owner=None, body):
        self.calls.append(("remove", body))
        self._maybe_raise()
        return {"removed": 3}

    def skills_list(self, *, owner=None, scope=None, campaign_id=None):
        self.calls.append(("skills_list", {"scope": scope, "campaign_id": campaign_id}))
        self._maybe_raise()
        return {"skills": [{"name": "acme", "description": "tenant flow"}]}

    def skill_load(self, name, *, owner=None):
        self.calls.append(("skill_load", name))
        self._maybe_raise()
        return {"name": name, "procedure": ["one", "two"]}

    def skill_create(self, *, owner=None, body):
        self.calls.append(("create", body))
        self._maybe_raise()
        return body

    def skill_patch(self, name, *, owner=None, body):
        self.calls.append(("patch", (name, body)))
        self._maybe_raise()
        return {"name": name, **body}

    def skill_edit(self, name, *, owner=None, body):
        self.calls.append(("edit", (name, body)))
        self._maybe_raise()
        return {"name": name, **body}

    def skill_delete(self, name, *, owner=None):
        self.calls.append(("delete", name))
        self._maybe_raise()
        return {"deleted": True}

    def recall(self, *, query, owner=None, limit=5, scope=None, campaign_id=None):
        self.calls.append(
            ("recall", {"query": query, "limit": limit, "scope": scope, "campaign_id": campaign_id})
        )
        self._maybe_raise()
        return {"hits": [{"run_id": "r1", "text": "Acme uses Workday", "score": 0.9}]}


class MalformedClient(FakeClient):
    """Up, but returns shapes the bridge must defensively reject (non-dict / wrong keys)."""

    def memory_snapshot(self, *, owner=None, scope=None, campaign_id=None):
        return ["not", "a", "dict"]

    def memory_replace(self, *, owner=None, body):
        return None  # not a dict -> replaced False

    def memory_remove(self, *, owner=None, body):
        return {"removed": "not-an-int"}  # non-numeric -> 0

    def skills_list(self, *, owner=None, scope=None, campaign_id=None):
        return {"skills": "not-a-list"}

    def skill_load(self, name, *, owner=None):
        return {}  # no "name" -> None

    def recall(self, *, query, owner=None, limit=5, scope=None, campaign_id=None):
        return {
            "hits": [
                "junk",  # non-dict hit -> skipped
                {"run_id": "r1", "text": "ok", "score": "NaN-ish"},  # bad score -> 0.0
                {"run_id": "r2", "text": "two", "score": 0.5},
                {"run_id": "r3", "text": "three", "score": 0.4},
            ]
        }


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


# --- request mapping: the bridge forwards engine args to the workspace -------

def test_snapshot_forwards_scope_and_campaign():
    """snapshot(scope, campaign_id) must reach the workspace as the same kwargs."""
    client = FakeClient()
    WorkspaceBridgeMemoryStore(client).snapshot(scope="campaign", campaign_id="c7")
    assert client.calls[-1] == ("snapshot", {"scope": "campaign", "campaign_id": "c7"})


def test_memory_add_maps_full_entry_body():
    """The whole MemoryEntry (text/kind/scope/campaign_id) is serialized into the POST body."""
    client = FakeClient()
    WorkspaceBridgeMemoryStore(client).add(
        MemoryEntry(text="hi", kind=KIND_USER, scope="campaign", campaign_id="c7")
    )
    _, body = client.calls[-1]
    assert body == {"text": "hi", "kind": KIND_USER, "scope": "campaign", "campaign_id": "c7"}


def test_memory_replace_maps_find_and_nested_entry():
    """replace() wraps the new entry under 'entry' alongside the 'find' selector."""
    client = FakeClient()
    WorkspaceBridgeMemoryStore(client).replace("old", MemoryEntry(text="new", kind=KIND_USER))
    op, body = client.calls[-1]
    assert op == "replace"
    assert body["find"] == "old"
    assert body["entry"]["text"] == "new" and body["entry"]["kind"] == KIND_USER


def test_memory_remove_maps_find_body():
    client = FakeClient()
    WorkspaceBridgeMemoryStore(client).remove("stale")
    assert client.calls[-1] == ("remove", {"find": "stale"})


def test_skills_list_forwards_scope_and_campaign():
    client = FakeClient()
    WorkspaceBridgeSkillStore(client).list_skills(scope="campaign", campaign_id="c7")
    assert client.calls[-1] == ("skills_list", {"scope": "campaign", "campaign_id": "c7"})


def test_recall_forwards_query_limit_scope_campaign():
    client = FakeClient()
    WorkspaceBridgeRecallIndex(client).search("workday", limit=3, scope="campaign", campaign_id="c7")
    assert client.calls[-1] == (
        "recall",
        {"query": "workday", "limit": 3, "scope": "campaign", "campaign_id": "c7"},
    )


# --- skills create/patch/edit round-trip + response mapping ------------------

def test_skill_create_sends_full_skill_body():
    """create() serializes every Skill field (incl. list fields as lists) into the body."""
    client = FakeClient()
    s = Skill(name="acme", description="d", procedure=("a", "b"), tags=("t",))
    WorkspaceBridgeSkillStore(client).create(s)
    _, body = client.calls[-1]
    assert body["name"] == "acme"
    assert body["procedure"] == ["a", "b"] and body["tags"] == ["t"]


def test_skill_patch_maps_response_to_skill():
    client = FakeClient()
    out = WorkspaceBridgeSkillStore(client).patch("acme", description="updated")
    assert client.calls[-1] == ("patch", ("acme", {"description": "updated"}))
    assert out is not None and out.name == "acme" and out.description == "updated"


def test_skill_edit_maps_response_to_skill():
    client = FakeClient()
    s = Skill(name="acme", description="rewritten", procedure=("x",))
    out = WorkspaceBridgeSkillStore(client).edit("acme", s)
    op, (name, body) = client.calls[-1]
    assert op == "edit" and name == "acme" and body["description"] == "rewritten"
    assert out is not None and out.procedure == ("x",)


def test_skill_load_returns_none_for_missing_name():
    """A workspace 404-style empty body (no 'name') maps to None, not a blank Skill."""
    assert WorkspaceBridgeSkillStore(MalformedClient()).load("ghost") is None


# --- write paths degrade on WorkspaceError (not just reads) ------------------

def test_memory_add_swallows_error():
    store = WorkspaceBridgeMemoryStore(FakeClient(raise_error=True))
    entry = MemoryEntry(text="hi", kind=KIND_USER)
    assert store.add(entry) is entry  # returns the authored entry, no raise


def test_memory_replace_swallows_error():
    assert WorkspaceBridgeMemoryStore(FakeClient(raise_error=True)).replace(
        "x", MemoryEntry(text="y")
    ) is False


def test_skill_write_paths_swallow_error():
    store = WorkspaceBridgeSkillStore(FakeClient(raise_error=True))
    s = Skill(name="acme")
    assert store.create(s) is s
    assert store.patch("acme", description="d") is None
    assert store.edit("acme", s) is None
    assert store.delete("acme") is False


# --- malformed / non-dict responses degrade defensively ---------------------

def test_malformed_responses_degrade():
    mem = WorkspaceBridgeMemoryStore(MalformedClient())
    assert mem.snapshot().all() == ()              # list response -> empty snapshot
    assert mem.replace("a", MemoryEntry(text="b")) is False  # None response
    assert mem.remove("a") == 0                     # non-numeric 'removed'
    assert WorkspaceBridgeSkillStore(MalformedClient()).list_skills() == ()  # non-list 'skills'


def test_recall_skips_junk_hits_and_truncates_to_limit():
    """Non-dict hits are dropped, a bad score coerces to 0.0, and output honors limit."""
    hits = WorkspaceBridgeRecallIndex(MalformedClient()).search("q", limit=2)
    assert len(hits) == 2                       # 3 dict hits, capped at limit=2
    assert hits[0].run_id == "r1" and hits[0].score == 0.0  # unparsable score -> 0.0
    assert hits[1].run_id == "r2"


# --- constructor None vs available()-False; index no-op ----------------------

def test_workspace_none_degrades_like_off_channel():
    """A bridge built with workspace=None must degrade exactly like available() False."""
    assert WorkspaceBridgeMemoryStore(None).snapshot().all() == ()
    assert WorkspaceBridgeMemoryStore(None).remove("x") == 0
    assert WorkspaceBridgeSkillStore(None).list_skills() == ()
    assert WorkspaceBridgeSkillStore(None).load("x") is None
    assert WorkspaceBridgeRecallIndex(None).search("q") == ()


def test_recall_index_is_noop_and_never_raises():
    """The engine READS recall over the bridge; index() is a deliberate no-op."""
    idx = WorkspaceBridgeRecallIndex(FakeClient())
    assert idx.index("run-1", "some text", campaign_id="c7") is None
    # Even with a down client it must not reach out or raise.
    assert WorkspaceBridgeRecallIndex(FakeClient(raise_error=True)).index("r", "t") is None


def test_campaign_id_blank_maps_to_none():
    """An empty-string campaign_id from the workspace normalizes to None on the entry."""
    class BlankCampaignClient(FakeClient):
        def memory_snapshot(self, *, owner=None, scope=None, campaign_id=None):
            return {"environment": [{"text": "x", "kind": "environment", "campaign_id": ""}],
                    "user": [], "truncated": False}

    snap = WorkspaceBridgeMemoryStore(BlankCampaignClient()).snapshot()
    assert snap.environment[0].campaign_id is None
