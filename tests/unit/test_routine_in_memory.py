"""Tests for InMemoryRoutineStore adapter."""
from __future__ import annotations

import pytest

from applicant.adapters.routine.in_memory import InMemoryRoutineStore
from applicant.ports.driven.routine_store import (
    DEFAULT_PRUNE_THRESHOLD,
    Routine,
    RoutineStep,
)


@pytest.fixture(autouse=True)
def _reset_module_state():
    """No-op fixture for xdist parallel safety."""
    yield


@pytest.mark.unit
class TestGet:
    def test_returns_none_for_unknown_domain(self):
        store = InMemoryRoutineStore()
        assert store.get("no-such-domain") is None

    def test_returns_none_for_empty_domain(self):
        store = InMemoryRoutineStore()
        assert store.get("") is None

    def test_returns_routine_after_induce(self):
        store = InMemoryRoutineStore()
        steps = (RoutineStep(kind="fill"),)
        store.induce("test.example.com", steps)
        r = store.get("test.example.com")
        assert r is not None
        assert r.domain == "test.example.com"


@pytest.mark.unit
class TestInduce:
    def test_creates_new_routine_with_steps(self):
        store = InMemoryRoutineStore()
        steps = (RoutineStep(kind="fill", ref="#name"), RoutineStep(kind="click", ref="#submit"))
        r = store.induce("example.com", steps)
        assert r is not None
        assert r.domain == "example.com"
        assert len(r.steps) == 2
        assert r.steps[0].kind == "fill"
        assert r.steps[0].ref == "#name"

    def test_returns_none_for_empty_domain(self):
        store = InMemoryRoutineStore()
        assert store.induce("", (RoutineStep(kind="fill"),)) is None

    def test_returns_none_for_empty_steps(self):
        store = InMemoryRoutineStore()
        assert store.induce("example.com", ()) is None

    def test_updates_existing_increments_successes(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        r = store.induce("example.com", (RoutineStep(kind="select"),))
        assert r is not None
        assert r.steps[0].kind == "select"
        assert r.successes == 2
        assert r.failures == 0

    def test_new_routine_starts_with_successes_1(self):
        store = InMemoryRoutineStore()
        r = store.induce("example.com", (RoutineStep(kind="fill"),))
        assert r.successes == 1
        assert r.failures == 0


@pytest.mark.unit
class TestRecordSuccess:
    def test_increments_successes(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        store.record_success("example.com")
        r = store.get("example.com")
        assert r.successes == 2

    def test_noop_for_unknown_domain(self):
        store = InMemoryRoutineStore()
        store.record_success("no-such-domain")
        assert store.get("no-such-domain") is None

    def test_noop_for_empty_domain(self):
        store = InMemoryRoutineStore()
        store.record_success("")
        assert store.get("") is None


@pytest.mark.unit
class TestRecordFailure:
    def test_increments_failures(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        r = store.record_failure("example.com")
        assert r is not None
        assert r.failures == 1

    def test_returns_none_for_unknown_domain(self):
        store = InMemoryRoutineStore()
        assert store.record_failure("no-such-domain") is None

    def test_returns_none_for_empty_domain(self):
        store = InMemoryRoutineStore()
        assert store.record_failure("") is None

    def test_prunes_when_net_failures_cross_threshold(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        # successes=1, failures=0. Need net failures >= DEFAULT_PRUNE_THRESHOLD (3)
        # After 4 failures: successes=1, failures=4, net=3 -> prune
        store.record_failure("example.com")  # f=1, net=-0 -> still ok
        store.record_failure("example.com")  # f=2, net=-1
        store.record_failure("example.com")  # f=3, net=-2
        store.record_failure("example.com")  # f=4, net=3 >= threshold -> prune
        assert store.get("example.com") is None

    def test_success_offsets_failure_no_prune(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        store.record_failure("example.com")  # s=1, f=1
        store.record_failure("example.com")  # s=1, f=2
        store.record_success("example.com")  # s=2, f=2
        r = store.record_failure("example.com")  # s=2, f=3, net=1 < threshold
        assert r is not None
        assert r.successes == 2
        assert r.failures == 3


@pytest.mark.unit
class TestAllDomains:
    def test_returns_registered_domain_keys(self):
        store = InMemoryRoutineStore()
        store.induce("a.example.com", (RoutineStep(kind="fill"),))
        store.induce("b.example.com", (RoutineStep(kind="click"),))
        domains = store.all_domains()
        assert isinstance(domains, tuple)
        assert "a.example.com" in domains
        assert "b.example.com" in domains

    def test_empty_when_no_routines(self):
        store = InMemoryRoutineStore()
        assert store.all_domains() == ()


@pytest.mark.unit
class TestSnapshot:
    def test_returns_dict_with_routines_key(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        snap = store.snapshot()
        assert isinstance(snap, dict)
        assert "routines" in snap

    def test_contains_domain_data(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill", ref="#field"),))
        snap = store.snapshot()
        assert "example.com" in snap["routines"]
        entry = snap["routines"]["example.com"]
        assert entry["domain"] == "example.com"
        assert entry["successes"] == 1
        assert entry["failures"] == 0


@pytest.mark.unit
class TestRestore:
    def test_loads_snapshot_via_persister(self):
        snapshot_data = {
            "routines": {
                "example.com": {
                    "domain": "example.com",
                    "steps": [
                        {"kind": "fill", "ref": "#name", "attribute_id": "", "document_id": "", "role": "", "name": ""}
                    ],
                    "successes": 2,
                    "failures": 1,
                    "source": "induced",
                }
            }
        }

        class FakePersister:
            def load(self):
                return snapshot_data

            def save(self, data):
                pass

        store = InMemoryRoutineStore(persister=FakePersister())
        store.restore()
        r = store.get("example.com")
        assert r is not None
        assert r.domain == "example.com"
        assert r.successes == 2
        assert r.failures == 1

    def test_noop_without_persister(self):
        store = InMemoryRoutineStore()
        store.restore()  # should not raise


@pytest.mark.unit
class TestPersist:
    def test_calls_persister_save_with_snapshot(self):
        saved_calls = []

        class FakePersister:
            def load(self):
                return None

            def save(self, data):
                saved_calls.append(data)

        store = InMemoryRoutineStore(persister=FakePersister())
        store.induce("example.com", (RoutineStep(kind="fill"),))
        assert len(saved_calls) == 1
        assert "routines" in saved_calls[0]
        assert "example.com" in saved_calls[0]["routines"]

    def test_noop_without_persister(self):
        store = InMemoryRoutineStore()
        store.induce("example.com", (RoutineStep(kind="fill"),))
        store.persist()  # should not raise
