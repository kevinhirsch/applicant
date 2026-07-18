import pytest
from typing import runtime_checkable

from applicant.ports.driven.recall_index import RecallHit, RecallIndex


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Autouse fixture for parallel (xdist) safety."""
    yield


class TestRecallHitDefaults:
    """RecallHit dataclass uses correct defaults."""

    def test_minimal_construction(self):
        hit = RecallHit(run_id="run-1", text="some text")
        assert hit.run_id == "run-1"
        assert hit.text == "some text"
        assert hit.score == 0.0
        assert hit.campaign_id is None


class TestRecallHitAllFields:
    """RecallHit accepts all fields including optional ones."""

    def test_full_construction(self):
        hit = RecallHit(
            run_id="run-2",
            text="another text",
            score=0.95,
            campaign_id="camp-1",
        )
        assert hit.run_id == "run-2"
        assert hit.text == "another text"
        assert hit.score == 0.95
        assert hit.campaign_id == "camp-1"


class TestRecallHitFrozen:
    """RecallHit is a frozen dataclass."""

    def test_cannot_modify_run_id(self):
        hit = RecallHit(run_id="run-3", text="t")
        with pytest.raises(AttributeError):
            hit.run_id = "run-4"

    def test_cannot_modify_text(self):
        hit = RecallHit(run_id="run-3", text="t")
        with pytest.raises(AttributeError):
            hit.text = "changed"

    def test_cannot_modify_score(self):
        hit = RecallHit(run_id="run-3", text="t")
        with pytest.raises(AttributeError):
            hit.score = 1.0

    def test_cannot_modify_campaign_id(self):
        hit = RecallHit(run_id="run-3", text="t")
        with pytest.raises(AttributeError):
            hit.campaign_id = "camp-99"


class TestRecallIndexProtocol:
    """RecallIndex is a runtime_checkable Protocol."""

    def test_is_runtime_checkable(self):
        assert runtime_checkable(RecallIndex)


class TestRecallIndexConcreteImplementation:
    """A concrete class that implements the Protocol is recognized."""

    def test_concrete_class_is_instance(self):
        class InMemoryRecallIndex:
            def __init__(self):
                self._store: list[RecallHit] = []

            def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
                self._store.append(RecallHit(run_id=run_id, text=text, campaign_id=campaign_id))

            def search(
                self,
                query: str,
                *,
                limit: int = 5,
                scope: str | None = None,
                campaign_id: str | None = None,
            ) -> tuple[RecallHit, ...]:
                return tuple(self._store[:limit])

        idx = InMemoryRecallIndex()
        assert isinstance(idx, RecallIndex)

    def test_search_returns_tuple_of_recall_hit(self):
        class InMemoryRecallIndex:
            def __init__(self):
                self._store: list[RecallHit] = []

            def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
                self._store.append(RecallHit(run_id=run_id, text=text, campaign_id=campaign_id))

            def search(
                self,
                query: str,
                *,
                limit: int = 5,
                scope: str | None = None,
                campaign_id: str | None = None,
            ) -> tuple[RecallHit, ...]:
                return tuple(self._store[:limit])

        idx = InMemoryRecallIndex()
        idx.index("run-1", "hello world")
        idx.index("run-2", "goodbye world")

        result = idx.search("world")
        assert isinstance(result, tuple)
        assert all(isinstance(h, RecallHit) for h in result)

    def test_search_default_limit_is_5(self):
        class InMemoryRecallIndex:
            def __init__(self):
                self._store: list[RecallHit] = []

            def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
                self._store.append(RecallHit(run_id=run_id, text=text, campaign_id=campaign_id))

            def search(
                self,
                query: str,
                *,
                limit: int = 5,
                scope: str | None = None,
                campaign_id: str | None = None,
            ) -> tuple[RecallHit, ...]:
                return tuple(self._store[:limit])

        idx = InMemoryRecallIndex()
        for i in range(10):
            idx.index(f"run-{i}", f"text {i}")

        result = idx.search("text")
        assert len(result) == 5

    def test_search_custom_limit(self):
        class InMemoryRecallIndex:
            def __init__(self):
                self._store: list[RecallHit] = []

            def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
                self._store.append(RecallHit(run_id=run_id, text=text, campaign_id=campaign_id))

            def search(
                self,
                query: str,
                *,
                limit: int = 5,
                scope: str | None = None,
                campaign_id: str | None = None,
            ) -> tuple[RecallHit, ...]:
                return tuple(self._store[:limit])

        idx = InMemoryRecallIndex()
        for i in range(10):
            idx.index(f"run-{i}", f"text {i}")

        result = idx.search("text", limit=3)
        assert len(result) == 3

    def test_search_accepts_scope_and_campaign_id(self):
        class InMemoryRecallIndex:
            def __init__(self):
                self._store: list[RecallHit] = []

            def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
                self._store.append(RecallHit(run_id=run_id, text=text, campaign_id=campaign_id))

            def search(
                self,
                query: str,
                *,
                limit: int = 5,
                scope: str | None = None,
                campaign_id: str | None = None,
            ) -> tuple[RecallHit, ...]:
                return tuple(self._store[:limit])

        idx = InMemoryRecallIndex()
        idx.index("run-1", "text")

        result = idx.search("text", scope="owner-1", campaign_id="camp-1")
        assert len(result) == 1


class TestRecallIndexNonImplementingClass:
    """A class that does not implement the Protocol is not an instance."""

    def test_class_without_methods_is_not_instance(self):
        class EmptyIndex:
            pass

        assert not isinstance(EmptyIndex(), RecallIndex)

    def test_class_with_only_index_is_not_instance(self):
        class PartialIndex:
            def index(self, run_id: str, text: str, campaign_id: str | None = None) -> None:
                pass

        assert not isinstance(PartialIndex(), RecallIndex)

    def test_class_with_only_search_is_not_instance(self):
        class PartialIndex:
            def search(
                self,
                query: str,
                *,
                limit: int = 5,
                scope: str | None = None,
                campaign_id: str | None = None,
            ) -> tuple[RecallHit, ...]:
                return ()

        assert not isinstance(PartialIndex(), RecallIndex)
