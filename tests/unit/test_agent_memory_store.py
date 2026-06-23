"""Unit tests for the in-memory agent-memory adapters (FR-MIND-1/2/3)."""

from __future__ import annotations

from applicant.adapters.memory.in_memory import (
    InMemoryMemoryStore,
    InMemoryRecallIndex,
    InMemorySkillStore,
)
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    KIND_USER,
    SCOPE_CAMPAIGN,
    SCOPE_GLOBAL,
    MemoryEntry,
)
from applicant.ports.driven.skill_store import Skill


# --- MemoryStore (FR-MIND-1) ---------------------------------------------
def test_memory_add_snapshot_split_by_kind():
    store = InMemoryMemoryStore()
    store.add(MemoryEntry(text="ATS lesson", kind=KIND_ENVIRONMENT))
    store.add(MemoryEntry(text="User likes concise prose", kind=KIND_USER))
    snap = store.snapshot()
    assert [e.text for e in snap.environment] == ["ATS lesson"]
    assert [e.text for e in snap.user] == ["User likes concise prose"]
    assert len(snap.all()) == 2


def test_memory_replace_substring_match():
    store = InMemoryMemoryStore()
    store.add(MemoryEntry(text="Workday needs react-select cleared"))
    assert store.replace("react-select", MemoryEntry(text="Workday tenant flow v2")) is True
    assert [e.text for e in store.snapshot().environment] == ["Workday tenant flow v2"]
    # No match -> False, no change.
    assert store.replace("nonexistent", MemoryEntry(text="x")) is False


def test_memory_remove_substring_match_returns_count():
    store = InMemoryMemoryStore()
    store.add(MemoryEntry(text="tenant alpha note"))
    store.add(MemoryEntry(text="tenant beta note"))
    store.add(MemoryEntry(text="unrelated"))
    assert store.remove("tenant") == 2
    assert [e.text for e in store.snapshot().environment] == ["unrelated"]


def test_memory_snapshot_scopes_campaign_entries():
    store = InMemoryMemoryStore()
    store.add(MemoryEntry(text="global lesson", scope=SCOPE_GLOBAL))
    store.add(
        MemoryEntry(text="campaign-1 lesson", scope=SCOPE_CAMPAIGN, campaign_id="c1")
    )
    store.add(
        MemoryEntry(text="campaign-2 lesson", scope=SCOPE_CAMPAIGN, campaign_id="c2")
    )
    snap = store.snapshot(campaign_id="c1")
    texts = [e.text for e in snap.environment]
    assert "global lesson" in texts
    assert "campaign-1 lesson" in texts
    assert "campaign-2 lesson" not in texts


def test_memory_snapshot_truncates_to_bounds():
    store = InMemoryMemoryStore(memory_max_chars=50)
    store.add(MemoryEntry(text="a" * 40))
    store.add(MemoryEntry(text="b" * 40))  # would exceed 50
    snap = store.snapshot()
    assert snap.truncated is True
    assert len(snap.environment) == 1


# --- SkillStore (FR-MIND-2) ----------------------------------------------
def test_skill_create_load_and_list_is_progressive():
    store = InMemorySkillStore()
    store.create(
        Skill(
            name="workday-location",
            description="Clear react-select for location",
            when_to_use="On Workday location fields",
            procedure=("Click the control", "Clear, then type the city"),
        )
    )
    # L0 list carries metadata, NOT the procedure body.
    metas = store.list_skills()
    assert len(metas) == 1
    assert metas[0].name == "workday-location"
    assert not hasattr(metas[0], "procedure")
    # L1 load carries the full body.
    full = store.load("workday-location")
    assert full is not None
    assert full.procedure == ("Click the control", "Clear, then type the city")


def test_skill_patch_and_edit_and_delete():
    store = InMemorySkillStore()
    store.create(Skill(name="s1", description="orig", version="1.0.0"))
    patched = store.patch("s1", description="updated")
    assert patched is not None and patched.description == "updated"
    assert store.load("s1").description == "updated"

    edited = store.edit("s1", Skill(name="s1", description="rewritten", version="2.0.0"))
    assert edited is not None and edited.version == "2.0.0"

    assert store.delete("s1") is True
    assert store.load("s1") is None
    assert store.patch("missing", description="x") is None


# --- RecallIndex (FR-MIND-3) ---------------------------------------------
def test_recall_search_ranks_by_overlap_and_bounds_by_limit():
    idx = InMemoryRecallIndex()
    idx.index("r1", "Workday location react-select clearing trick")
    idx.index("r2", "Greenhouse cover letter formatting note")
    idx.index("r3", "Workday tenant account creation flow")

    hits = idx.search("Workday react-select", limit=5)
    assert hits  # at least one hit
    assert hits[0].run_id == "r1"  # best overlap ranked first
    assert all(h.score > 0 for h in hits)

    # limit is honored
    limited = idx.search("Workday", limit=1)
    assert len(limited) == 1


def test_recall_search_scopes_to_campaign():
    idx = InMemoryRecallIndex()
    idx.index("r1", "Acme Workday flow", campaign_id="c1")
    idx.index("r2", "Beta Workday flow", campaign_id="c2")
    hits = idx.search("Workday", campaign_id="c1")
    assert [h.run_id for h in hits] == ["r1"]
