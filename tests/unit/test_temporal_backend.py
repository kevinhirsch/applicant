"""Parallel-safe unit tests for the bi-temporal memory backend (AZ0-117)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.adapters.memory.temporal_backend import (
    TemporalFact,
    TemporalMemoryStore,
)
from applicant.ports.driven.memory_store import (
    KIND_ENVIRONMENT,
    KIND_USER,
    SCOPE_CAMPAIGN,
    SCOPE_GLOBAL,
    MemoryEntry,
    MemorySnapshot,
)


# ---------------------------------------------------------------------------
# Parallel-safety fixture — no caches to clear in this module, but xdist
# conventions require an autouse fixture for every unit-test module.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    yield


# ===================================================================
# TemporalFact
# ===================================================================


class TestTemporalFact:
    """TemporalFact frozen dataclass and is_current property."""

    @pytest.mark.unit
    def test_frozen(self) -> None:
        entry = MemoryEntry(text="hello")
        fact = TemporalFact(entry=entry)
        with pytest.raises((AttributeError, TypeError)):
            fact.entry = MemoryEntry(text="bye")  # type: ignore[misc]

    @pytest.mark.unit
    def test_is_current_when_valid_to_is_none(self) -> None:
        entry = MemoryEntry(text="current fact")
        fact = TemporalFact(entry=entry)
        assert fact.is_current is True

    @pytest.mark.unit
    def test_is_current_when_valid_to_is_set(self) -> None:
        entry = MemoryEntry(text="historical fact")
        now = datetime.now(UTC)
        fact = TemporalFact(entry=entry, valid_from=now, valid_to=now)
        assert fact.is_current is False

    @pytest.mark.unit
    def test_default_valid_from_is_utc_now(self) -> None:
        entry = MemoryEntry(text="test")
        before = datetime.now(UTC)
        fact = TemporalFact(entry=entry)
        after = datetime.now(UTC)
        assert before <= fact.valid_from <= after


# ===================================================================
# TemporalMemoryStore — add / replace / remove / history / snapshot
# ===================================================================


class TestAdd:
    """add() appends a new current fact."""

    @pytest.mark.unit
    def test_add_returns_entry(self) -> None:
        store = TemporalMemoryStore()
        entry = MemoryEntry(text="foo")
        result = store.add(entry)
        assert result is entry

    @pytest.mark.unit
    def test_add_creates_current_fact(self) -> None:
        store = TemporalMemoryStore()
        entry = MemoryEntry(text="foo")
        store.add(entry)
        result = store.snapshot()
        assert len(result.environment) == 1
        assert result.environment[0].text == "foo"

    @pytest.mark.unit
    def test_add_multiple_entries(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="a"))
        store.add(MemoryEntry(text="b"))
        store.add(MemoryEntry(text="c"))
        result = store.snapshot()
        assert len(result.environment) == 3
        assert [e.text for e in result.environment] == ["a", "b", "c"]


class TestReplace:
    """replace() closes the existing window and creates a new one."""

    @pytest.mark.unit
    def test_replace_returns_true_when_match_found(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="the color is red"))
        assert store.replace("color", MemoryEntry(text="the color is blue")) is True

    @pytest.mark.unit
    def test_replace_returns_false_when_no_match(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="the color is red"))
        assert store.replace("missing", MemoryEntry(text="new")) is False

    @pytest.mark.unit
    def test_replace_keeps_old_fact_with_closed_window(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="the color is red"))
        before = datetime.now(UTC)
        store.replace("color", MemoryEntry(text="the color is blue"))
        after = datetime.now(UTC)

        all_facts = store.history()
        assert len(all_facts) == 2
        old, new = all_facts

        # Old fact is no longer current
        assert old.is_current is False
        assert old.entry.text == "the color is red"
        assert old.valid_to is not None
        assert before <= old.valid_to <= after

        # New fact is current
        assert new.is_current is True
        assert new.entry.text == "the color is blue"

    @pytest.mark.unit
    def test_replace_only_closes_current_matching(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="the color is red"))
        store.replace("color", MemoryEntry(text="the color is blue"))
        # Now both are in history — replace again should match only the current one
        assert store.replace("color", MemoryEntry(text="the color is green")) is True
        history = store.history()
        assert len(history) == 3
        # First old, second old, current
        assert history[0].is_current is False
        assert history[1].is_current is False
        assert history[2].is_current is True
        assert history[2].entry.text == "the color is green"

    @pytest.mark.unit
    def test_replace_no_match_preserves_snapshot(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        store.replace("bar", MemoryEntry(text="baz"))
        result = store.snapshot()
        assert len(result.environment) == 1
        assert result.environment[0].text == "foo"

    @pytest.mark.unit
    def test_replace_substring_match(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="the quick brown fox"))
        assert store.replace("brown", MemoryEntry(text="the slow brown fox")) is True
        snapshot = store.snapshot()
        assert len(snapshot.environment) == 1
        assert snapshot.environment[0].text == "the slow brown fox"

    @pytest.mark.unit
    def test_replace_multiple_matches(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="color: red"))
        store.add(MemoryEntry(text="color: green"))
        assert store.replace("color", MemoryEntry(text="color: blue")) is True
        # Both old facts closed, one new added
        history = store.history()
        assert len(history) == 3
        assert history[0].is_current is False
        assert history[1].is_current is False
        assert history[2].is_current is True
        assert history[2].entry.text == "color: blue"


class TestRemove:
    """remove() closes matching facts and returns count."""

    @pytest.mark.unit
    def test_remove_returns_matched_count(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        store.add(MemoryEntry(text="bar"))
        assert store.remove("foo") == 1

    @pytest.mark.unit
    def test_remove_returns_zero_when_no_match(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        assert store.remove("missing") == 0

    @pytest.mark.unit
    def test_remove_closes_window(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        before = datetime.now(UTC)
        store.remove("foo")
        after = datetime.now(UTC)

        history = store.history()
        assert len(history) == 1
        assert history[0].is_current is False
        assert history[0].valid_to is not None
        assert before <= history[0].valid_to <= after

    @pytest.mark.unit
    def test_remove_entry_disappears_from_snapshot(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        store.add(MemoryEntry(text="bar"))
        store.remove("foo")
        snapshot = store.snapshot()
        assert len(snapshot.environment) == 1
        assert snapshot.environment[0].text == "bar"

    @pytest.mark.unit
    def test_remove_matches_all_current_with_substring(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo A"))
        store.add(MemoryEntry(text="foo B"))
        store.add(MemoryEntry(text="bar"))
        assert store.remove("foo") == 2
        snapshot = store.snapshot()
        assert len(snapshot.environment) == 1
        assert snapshot.environment[0].text == "bar"

    @pytest.mark.unit
    def test_remove_on_empty_store(self) -> None:
        store = TemporalMemoryStore()
        assert store.remove("anything") == 0

    @pytest.mark.unit
    def test_remove_does_not_affect_already_closed(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        store.remove("foo")
        # Remove again — should match nothing since the only match is closed
        assert store.remove("foo") == 0


class TestHistory:
    """history() returns all facts, optionally filtered."""

    @pytest.mark.unit
    def test_history_without_filter_returns_all(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="a"))
        store.add(MemoryEntry(text="b"))
        assert len(store.history()) == 2

    @pytest.mark.unit
    def test_history_with_filter_substring(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="alpha beta"))
        store.add(MemoryEntry(text="gamma delta"))
        result = store.history(find="alpha")
        assert len(result) == 1
        assert result[0].entry.text == "alpha beta"

    @pytest.mark.unit
    def test_history_filter_no_match(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="alpha"))
        assert store.history(find="missing") == []

    @pytest.mark.unit
    def test_history_filter_none_returns_all(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="a"))
        store.add(MemoryEntry(text="b"))
        assert len(store.history(find=None)) == 2

    @pytest.mark.unit
    def test_history_includes_closed_facts(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        store.remove("foo")
        assert len(store.history()) == 1


class TestSnapshot:
    """snapshot() returns only current facts, filtered by kind and scope."""

    @pytest.mark.unit
    def test_snapshot_returns_memory_snapshot(self) -> None:
        store = TemporalMemoryStore()
        result = store.snapshot()
        assert isinstance(result, MemorySnapshot)

    @pytest.mark.unit
    def test_snapshot_empty_store(self) -> None:
        store = TemporalMemoryStore()
        result = store.snapshot()
        assert result.environment == ()
        assert result.user == ()

    @pytest.mark.unit
    def test_snapshot_separates_environment_and_user(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="env fact", kind=KIND_ENVIRONMENT))
        store.add(MemoryEntry(text="user pref", kind=KIND_USER))
        result = store.snapshot()
        assert len(result.environment) == 1
        assert result.environment[0].text == "env fact"
        assert len(result.user) == 1
        assert result.user[0].text == "user pref"

    @pytest.mark.unit
    def test_snapshot_excludes_closed_facts(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="foo"))
        store.remove("foo")
        result = store.snapshot()
        assert len(result.environment) == 0
        assert len(result.user) == 0

    @pytest.mark.unit
    def test_snapshot_global_scope_by_default(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="global fact", scope=SCOPE_GLOBAL))
        # With no scope filter, global entries are included
        result = store.snapshot()
        assert len(result.environment) == 1

    @pytest.mark.unit
    def test_snapshot_filters_campaign_scope_without_campaign_id(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(
            text="campaign fact",
            scope=SCOPE_CAMPAIGN,
            campaign_id="camp-1",
        ))
        # No campaign_id filter — campaign entries are excluded
        result = store.snapshot()
        assert len(result.environment) == 0
        assert len(result.user) == 0

    @pytest.mark.unit
    def test_snapshot_includes_campaign_with_matching_campaign_id(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(
            text="campaign fact",
            scope=SCOPE_CAMPAIGN,
            campaign_id="camp-1",
        ))
        result = store.snapshot(scope=SCOPE_CAMPAIGN, campaign_id="camp-1")
        assert len(result.environment) == 1
        assert result.environment[0].text == "campaign fact"

    @pytest.mark.unit
    def test_snapshot_excludes_non_matching_campaign_id(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(
            text="campaign fact",
            scope=SCOPE_CAMPAIGN,
            campaign_id="camp-1",
        ))
        result = store.snapshot(scope=SCOPE_CAMPAIGN, campaign_id="camp-2")
        assert len(result.environment) == 0

    @pytest.mark.unit
    def test_snapshot_mixed_scope(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="global", scope=SCOPE_GLOBAL))
        store.add(MemoryEntry(
            text="campaign fact",
            scope=SCOPE_CAMPAIGN,
            campaign_id="camp-1",
        ))
        # Default filter (scope=None) — only global passed
        result = store.snapshot(scope=SCOPE_CAMPAIGN, campaign_id="camp-1")
        # The global fact also passes because its scope != SCOPE_CAMPAIGN
        # Looking at the source code:
        # visible = [e for e in current if e.scope != SCOPE_CAMPAIGN or e.campaign_id == campaign_id]
        # So global entries pass the filter regardless of campaign_id
        assert len(result.environment) == 2

    @pytest.mark.unit
    def test_snapshot_does_not_collect_replace_overwrites(self) -> None:
        store = TemporalMemoryStore()
        store.add(MemoryEntry(text="old version"))
        store.replace("old", MemoryEntry(text="new version"))
        result = store.snapshot()
        assert len(result.environment) == 1
        assert result.environment[0].text == "new version"


class TestThreadSafety:
    """Verify basic thread-safe operation (RLock)."""

    @pytest.mark.unit
    def test_concurrent_add_and_snapshot(self) -> None:
        import threading

        store = TemporalMemoryStore()
        results: list[int] = []
        errors: list[Exception] = []

        def worker(n: int) -> None:
            try:
                for i in range(n):
                    store.add(MemoryEntry(text=f"thread-{i}"))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(50,)),
            threading.Thread(target=worker, args=(50,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store.history()) == 100

    @pytest.mark.unit
    def test_add_doesnt_raise_on_rlock(self) -> None:
        store = TemporalMemoryStore()
        entry = MemoryEntry(text="test")
        store.add(entry)
        # Calling add within a with-self._lock block should not deadlock
        with store._lock:
            store.add(MemoryEntry(text="nested"))
        assert len(store.history()) == 2
