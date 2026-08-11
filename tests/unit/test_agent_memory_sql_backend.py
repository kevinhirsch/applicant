"""Unit tests for the DURABLE SQL agent-memory adapters (FR-MIND-1/2/3, #286).

The SQL trio (``SqlMemoryStore`` / ``SqlSkillStore`` / ``SqlRecallIndex``) must be
behaviorally identical to the in-memory trio (parity), but persist to the shared
SQLAlchemy storage stack so curated memory SURVIVES an engine restart — the
headline requirement (a "remembers you" product cannot lose it on restart).

Every test runs against a real temp-FILE SQLite database (not ``:memory:``) so a
brand-new store on the SAME url proves restart survival at the persistence layer.
Each operation opens a SHORT-LIVED session from the injected ``session_factory``.
"""

from __future__ import annotations

import threading
import time

import pytest
from sqlalchemy import event

from applicant.adapters.memory.in_memory import InMemoryMemoryStore
from applicant.adapters.memory.sql_backend import (
    SqlMemoryStore,
    SqlRecallIndex,
    SqlSkillStore,
)
from applicant.adapters.storage.models import Base
from applicant.adapters.storage.session import make_engine, make_session_factory
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    KIND_USER,
    SCOPE_CAMPAIGN,
    SCOPE_GLOBAL,
    MemoryEntry,
    MemorySnapshot,
    MemoryStore,
)
from applicant.ports.driven.recall_index import RecallIndex
from applicant.ports.driven.skill_store import Skill, SkillStore

pytestmark = pytest.mark.unit


# --- fixtures / helpers ----------------------------------------------------
def _sqlite_url(tmp_path) -> str:
    return f"sqlite:///{tmp_path / 'agent_memory.db'}"


def _make_factory(url: str):
    """Engine + session_factory for a file-SQLite DB, tables created.

    Enables WAL + a busy_timeout so concurrent short-lived writer sessions wait
    rather than raise ``database is locked`` (the sqlite analogue of Postgres
    row-level serialization the production DB provides natively).
    """
    engine = make_engine(url)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _rec):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    Base.metadata.create_all(engine)
    return engine, make_session_factory(engine)


@pytest.fixture
def factory(tmp_path):
    url = _sqlite_url(tmp_path)
    engine, sf = _make_factory(url)
    yield url, sf
    engine.dispose()


# --- MemoryStore parity (FR-MIND-1) ---------------------------------------
def test_memory_add_snapshot_split_by_kind(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf)
    store.add(MemoryEntry(text="ATS lesson", kind=KIND_ENVIRONMENT))
    store.add(MemoryEntry(text="User likes concise prose", kind=KIND_USER))
    snap = store.snapshot()
    assert [e.text for e in snap.environment] == ["ATS lesson"]
    assert [e.text for e in snap.user] == ["User likes concise prose"]
    assert len(snap.all()) == 2


def test_memory_replace_substring_match(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf)
    store.add(MemoryEntry(text="Workday needs react-select cleared"))
    assert store.replace("react-select", MemoryEntry(text="Workday tenant flow v2")) is True
    assert [e.text for e in store.snapshot().environment] == ["Workday tenant flow v2"]
    assert store.replace("nonexistent", MemoryEntry(text="x")) is False


def test_memory_replace_only_first_match(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf)
    store.add(MemoryEntry(text="tenant alpha note"))
    store.add(MemoryEntry(text="tenant beta note"))
    assert store.replace("tenant", MemoryEntry(text="tenant merged note")) is True
    texts = [e.text for e in store.snapshot().environment]
    # First (insertion-order) match replaced; the second untouched.
    assert texts == ["tenant merged note", "tenant beta note"]


def test_memory_remove_substring_match_returns_count(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf)
    store.add(MemoryEntry(text="tenant alpha note"))
    store.add(MemoryEntry(text="tenant beta note"))
    store.add(MemoryEntry(text="unrelated"))
    assert store.remove("tenant") == 2
    assert [e.text for e in store.snapshot().environment] == ["unrelated"]


def test_memory_snapshot_scopes_campaign_entries(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf)
    store.add(MemoryEntry(text="global lesson", scope=SCOPE_GLOBAL))
    store.add(MemoryEntry(text="campaign-1 lesson", scope=SCOPE_CAMPAIGN, campaign_id="c1"))
    store.add(MemoryEntry(text="campaign-2 lesson", scope=SCOPE_CAMPAIGN, campaign_id="c2"))
    snap = store.snapshot(campaign_id="c1")
    texts = [e.text for e in snap.environment]
    assert "global lesson" in texts
    assert "campaign-1 lesson" in texts
    assert "campaign-2 lesson" not in texts


def test_memory_snapshot_truncates_to_bounds(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf, memory_max_chars=50)
    store.add(MemoryEntry(text="a" * 40))
    store.add(MemoryEntry(text="b" * 40))  # would exceed 50
    snap = store.snapshot()
    assert snap.truncated is True
    assert len(snap.environment) == 1


def test_memory_snapshot_user_bounds_independent(factory):
    _url, sf = factory
    store = SqlMemoryStore(sf, memory_max_chars=10000, user_max_chars=50)
    store.add(MemoryEntry(text="e" * 40, kind=KIND_ENVIRONMENT))
    store.add(MemoryEntry(text="u" * 40, kind=KIND_USER))
    store.add(MemoryEntry(text="v" * 40, kind=KIND_USER))  # exceeds user budget
    snap = store.snapshot()
    assert len(snap.environment) == 1
    assert len(snap.user) == 1
    assert snap.truncated is True


# --- DURABILITY: the headline test ----------------------------------------
def test_memory_survives_store_dispose_and_reconstruction(factory):
    """Write, DISPOSE the store, build a NEW store on the SAME DB url: entries persist."""
    url, sf = factory
    store1 = SqlMemoryStore(sf)
    store1.add(MemoryEntry(text="env lesson kept across restart", kind=KIND_ENVIRONMENT))
    store1.add(
        MemoryEntry(
            text="user prefers Kevin, not Mr Hirsch",
            kind=KIND_USER,
            scope=SCOPE_GLOBAL,
        )
    )
    store1.add(
        MemoryEntry(
            text="acme workday tenant is acme.myworkday",
            kind=KIND_ENVIRONMENT,
            scope=SCOPE_CAMPAIGN,
            campaign_id="acme",
        )
    )
    # Simulate an engine restart: throw away the store, session_factory AND engine,
    # then reconnect a BRAND-NEW trio to the same on-disk database.
    del store1

    engine2 = make_engine(url)
    sf2 = make_session_factory(engine2)
    try:
        store2 = SqlMemoryStore(sf2)
        snap = store2.snapshot()
        assert "env lesson kept across restart" in [e.text for e in snap.environment]
        assert "user prefers Kevin, not Mr Hirsch" in [e.text for e in snap.user]
        # Campaign-scoped entry visible only under its campaign, kind preserved.
        camp = store2.snapshot(campaign_id="acme")
        assert "acme workday tenant is acme.myworkday" in [e.text for e in camp.environment]
        assert "acme workday tenant is acme.myworkday" not in [
            e.text for e in store2.snapshot(campaign_id="other").environment
        ]
    finally:
        engine2.dispose()


# --- CONCURRENCY -----------------------------------------------------------
def test_concurrent_adds_do_not_lose_updates(factory):
    """Concurrent add()s from many threads (fresh session per op) lose nothing."""
    _url, sf = factory
    store = SqlMemoryStore(sf)
    n_threads, per_thread = 8, 25
    errors: list[Exception] = []

    def _worker(w: int) -> None:
        try:
            for i in range(per_thread):
                store.add(MemoryEntry(text=f"worker {w} entry {i} lorem ipsum note"))
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(w,)) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent add() raised: {errors[:3]}"
    # No lost updates: every write is a distinct row. snapshot() is char-bounded, so
    # count rows directly via a large-budget snapshot.
    big = SqlMemoryStore(sf, memory_max_chars=10_000_000, user_max_chars=10_000_000)
    assert len(big.snapshot().environment) == n_threads * per_thread


# --- LATENCY GUARD (no bridge-style hot-path stall) -----------------------
def test_snapshot_is_single_query_and_fast(factory):
    """snapshot() on a populated table is ONE indexed query, well under budget.

    Guards against re-introducing the disabled ``bridge`` backend's ~45s hot-path
    network stall: reads must stay local + single-query + fast.
    """
    _url, sf = factory
    store = SqlMemoryStore(sf)
    for i in range(300):
        scope = SCOPE_CAMPAIGN if i % 2 else SCOPE_GLOBAL
        store.add(
            MemoryEntry(
                text=f"lesson number {i} about ats behavior",
                kind=KIND_USER if i % 3 == 0 else KIND_ENVIRONMENT,
                scope=scope,
                campaign_id="c1" if scope == SCOPE_CAMPAIGN else None,
            )
        )

    engine = sf().get_bind()  # the sessionmaker's bound engine (public API)

    selects: list[str] = []

    @event.listens_for(engine, "after_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    try:
        # Warm, then assert exactly one SELECT for a snapshot call.
        store.snapshot(campaign_id="c1")
        selects.clear()
        snap = store.snapshot(campaign_id="c1")
        assert len(selects) == 1, f"snapshot must be a single query, ran {len(selects)}"
        assert isinstance(snap, MemorySnapshot)

        # Latency: min over several warmed runs must be under the tight budget.
        best = min(
            (_timed(store.snapshot, campaign_id="c1") for _ in range(20)),
        )
        assert best < 0.05, f"snapshot too slow: {best * 1000:.1f}ms (budget 50ms)"
    finally:
        event.remove(engine, "after_cursor_execute", _count)


def _timed(fn, **kw) -> float:
    start = time.perf_counter()
    fn(**kw)
    return time.perf_counter() - start


# --- BOUNDS / PRUNING (table stays bounded over many writes) --------------
def test_table_is_pruned_to_row_cap_per_scope(factory):
    """Beyond the per-scope row cap, the OLDEST rows are pruned (feature_stats cap)."""
    _url, sf = factory
    store = SqlMemoryStore(sf, max_rows_per_scope=10)
    for i in range(50):
        store.add(MemoryEntry(text=f"global note {i:03d} lorem ipsum"))
    big = SqlMemoryStore(sf, memory_max_chars=10_000_000, user_max_chars=10_000_000)
    texts = [e.text for e in big.snapshot().environment]
    # Table bounded to the cap, and the NEWEST rows are the ones retained.
    assert len(texts) == 10
    assert "global note 049 lorem ipsum" in texts
    assert "global note 000 lorem ipsum" not in texts


def test_pruning_is_per_scope_bucket(factory):
    """The cap applies per (scope, campaign) bucket, not globally."""
    _url, sf = factory
    store = SqlMemoryStore(sf, max_rows_per_scope=5)
    for i in range(20):
        store.add(MemoryEntry(text=f"global {i:03d} note here"))
    for i in range(20):
        store.add(
            MemoryEntry(
                text=f"campaign {i:03d} note here",
                scope=SCOPE_CAMPAIGN,
                campaign_id="c1",
            )
        )
    big = SqlMemoryStore(sf, memory_max_chars=10_000_000, user_max_chars=10_000_000)
    snap = big.snapshot(campaign_id="c1")
    globals_kept = [e for e in snap.environment if e.scope == SCOPE_GLOBAL]
    campaign_kept = [e for e in snap.environment if e.scope == SCOPE_CAMPAIGN]
    assert len(globals_kept) == 5
    assert len(campaign_kept) == 5


# --- SkillStore parity (FR-MIND-2) ----------------------------------------
def test_skill_create_load_and_list_is_progressive(factory):
    _url, sf = factory
    store = SqlSkillStore(sf)
    store.create(
        Skill(
            name="workday-location",
            description="Clear react-select for location",
            when_to_use="On Workday location fields",
            procedure=("Click the control", "Clear, then type the city"),
        )
    )
    metas = store.list_skills()
    assert len(metas) == 1
    assert metas[0].name == "workday-location"
    assert not hasattr(metas[0], "procedure")
    full = store.load("workday-location")
    assert full is not None
    assert full.procedure == ("Click the control", "Clear, then type the city")


def test_skill_patch_and_edit_and_delete(factory):
    _url, sf = factory
    store = SqlSkillStore(sf)
    store.create(Skill(name="s1", description="orig", version="1.0.0"))
    patched = store.patch("s1", description="updated")
    assert patched is not None and patched.description == "updated"
    assert store.load("s1").description == "updated"

    edited = store.edit("s1", Skill(name="s1", description="rewritten", version="2.0.0"))
    assert edited is not None and edited.version == "2.0.0"

    assert store.delete("s1") is True
    assert store.load("s1") is None
    assert store.patch("missing", description="x") is None
    assert store.edit("missing", Skill(name="missing")) is None
    assert store.delete("missing") is False


def test_skill_list_filters_by_scope_and_campaign(factory):
    from applicant.ports.driven.skill_store import SKILL_SCOPE_CAMPAIGN, SKILL_SCOPE_GLOBAL

    _url, sf = factory
    store = SqlSkillStore(sf)
    store.create(Skill(name="g", scope=SKILL_SCOPE_GLOBAL))
    store.create(Skill(name="c1", scope=SKILL_SCOPE_CAMPAIGN, campaign_id="c1"))
    store.create(Skill(name="c2", scope=SKILL_SCOPE_CAMPAIGN, campaign_id="c2"))
    # campaign_id filter keeps global (None) + the matching campaign.
    names = {m.name for m in store.list_skills(campaign_id="c1")}
    assert names == {"g", "c1"}


def test_skills_survive_reconstruction(factory):
    url, sf = factory
    store = SqlSkillStore(sf)
    store.create(
        Skill(
            name="greenhouse-cover",
            description="cover letter formatting",
            procedure=("draft", "trim to one page"),
            tags=("greenhouse", "cover"),
        )
    )
    engine2 = make_engine(url)
    sf2 = make_session_factory(engine2)
    try:
        loaded = SqlSkillStore(sf2).load("greenhouse-cover")
        assert loaded is not None
        assert loaded.procedure == ("draft", "trim to one page")
        assert loaded.tags == ("greenhouse", "cover")
    finally:
        engine2.dispose()


# --- RecallIndex parity (FR-MIND-3) ---------------------------------------
def test_recall_search_ranks_by_overlap_and_bounds_by_limit(factory):
    _url, sf = factory
    idx = SqlRecallIndex(sf)
    idx.index("r1", "Workday location react-select clearing trick")
    idx.index("r2", "Greenhouse cover letter formatting note")
    idx.index("r3", "Workday tenant account creation flow")

    hits = idx.search("Workday react-select", limit=5)
    assert hits
    assert hits[0].run_id == "r1"
    assert all(h.score > 0 for h in hits)

    limited = idx.search("Workday", limit=1)
    assert len(limited) == 1


def test_recall_search_scopes_to_campaign(factory):
    _url, sf = factory
    idx = SqlRecallIndex(sf)
    idx.index("r1", "Acme Workday flow", campaign_id="c1")
    idx.index("r2", "Beta Workday flow", campaign_id="c2")
    hits = idx.search("Workday", campaign_id="c1")
    assert [h.run_id for h in hits] == ["r1"]


def test_recall_index_upserts_and_survives_reconstruction(factory):
    url, sf = factory
    idx = SqlRecallIndex(sf)
    idx.index("r1", "first version of the run text")
    idx.index("r1", "second version replaces the first for run text")  # upsert
    engine2 = make_engine(url)
    sf2 = make_session_factory(engine2)
    try:
        hits = SqlRecallIndex(sf2).search("second version")
        assert len(hits) == 1
        assert hits[0].run_id == "r1"
        assert "second version" in hits[0].text
    finally:
        engine2.dispose()


def test_recall_empty_query_returns_nothing(factory):
    _url, sf = factory
    idx = SqlRecallIndex(sf)
    idx.index("r1", "some text")
    assert idx.search("") == ()


# --- ports satisfied -------------------------------------------------------
def test_sql_adapters_satisfy_ports(factory):
    _url, sf = factory
    assert isinstance(SqlMemoryStore(sf), MemoryStore)
    assert isinstance(SqlSkillStore(sf), SkillStore)
    assert isinstance(SqlRecallIndex(sf), RecallIndex)


# --- direct parity cross-check against the in-memory reference -------------
def test_sql_matches_in_memory_reference_behaviour(factory):
    """Same operations, same observable snapshot on both adapters."""
    _url, sf = factory
    ref = InMemoryMemoryStore()
    sql = SqlMemoryStore(sf)
    ops = [
        MemoryEntry(text="lesson one about ats"),
        MemoryEntry(text="lesson two user pref", kind=KIND_USER),
        MemoryEntry(text="campaign lesson", scope=SCOPE_CAMPAIGN, campaign_id="c1"),
    ]
    for e in ops:
        ref.add(e)
        sql.add(e)
    for store in (ref, sql):
        snap = store.snapshot(campaign_id="c1")
        assert [e.text for e in snap.environment] == [
            "lesson one about ats",
            "campaign lesson",
        ]
        assert [e.text for e in snap.user] == ["lesson two user pref"]
    # replace + remove parity
    assert ref.replace("lesson one", MemoryEntry(text="lesson one v2")) == sql.replace(
        "lesson one", MemoryEntry(text="lesson one v2")
    )
    assert ref.remove("campaign") == sql.remove("campaign")
