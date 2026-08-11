"""Unit tests for RoutineStep, Routine dataclasses and RoutineStore protocol."""

from __future__ import annotations

import pytest

from applicant.ports.driven.routine_store import (
    DEFAULT_PRUNE_THRESHOLD,
    Routine,
    RoutineStep,
    RoutineStore,
)


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Autouse fixture ensuring parallel-safe xdist execution."""
    pass


class TestRoutineStep:
    """RoutineStep frozen dataclass — struct, hash, and equality."""

    @pytest.mark.unit
    def test_minimal_defaults(self) -> None:
        step = RoutineStep(kind="fill")
        assert step.kind == "fill"
        assert step.ref == ""
        assert step.attribute_id == ""
        assert step.document_id == ""
        assert step.role == ""
        assert step.name == ""

    @pytest.mark.unit
    def test_explicit_fields(self) -> None:
        step = RoutineStep(
            kind="select",
            ref="#field-1",
            attribute_id="attr-42",
            document_id="doc-7",
            role="combobox",
            name="Country",
        )
        assert step.kind == "select"
        assert step.ref == "#field-1"
        assert step.attribute_id == "attr-42"
        assert step.document_id == "doc-7"
        assert step.role == "combobox"
        assert step.name == "Country"

    @pytest.mark.unit
    def test_equality(self) -> None:
        step1 = RoutineStep(kind="fill", ref="r1")
        step2 = RoutineStep(kind="fill", ref="r1")
        step3 = RoutineStep(kind="fill", ref="r2")
        assert step1 == step2
        assert step1 != step3

    @pytest.mark.unit
    def test_hashable(self) -> None:
        step = RoutineStep(kind="fill")
        s = {step}
        assert step in s

    @pytest.mark.unit
    def test_repr(self) -> None:
        step = RoutineStep(kind="fill", ref="x")
        r = repr(step)
        assert "RoutineStep" in r
        assert "kind=" in r
        assert "'fill'" in r
        assert "'x'" in r

    @pytest.mark.unit
    def test_frozen(self) -> None:
        step = RoutineStep(kind="fill")
        with pytest.raises(AttributeError):
            step.kind = "select"  # type: ignore[misc]


class TestRoutine:
    """Routine frozen dataclass — score property, as_prior_text, hash."""

    @pytest.mark.unit
    def test_minimal_defaults(self) -> None:
        r = Routine(domain="example.ats.com")
        assert r.domain == "example.ats.com"
        assert r.steps == ()
        assert r.successes == 1
        assert r.failures == 0
        assert r.source == "induced"

    @pytest.mark.unit
    def test_explicit_construction(self) -> None:
        steps = (
            RoutineStep(kind="fill", ref="#name"),
            RoutineStep(kind="select", ref="#country"),
        )
        r = Routine(
            domain="ats.example.io",
            steps=steps,
            successes=5,
            failures=2,
            source="curation",
        )
        assert r.domain == "ats.example.io"
        assert r.steps == steps
        assert r.successes == 5
        assert r.failures == 2
        assert r.source == "curation"

    @pytest.mark.unit
    def test_score_property(self) -> None:
        """score = successes - failures."""
        r = Routine(domain="x", successes=10, failures=3)
        assert r.score == 7

    @pytest.mark.unit
    def test_score_negative(self) -> None:
        """score can be negative when failures exceed successes."""
        r = Routine(domain="x", successes=0, failures=3)
        assert r.score == -3

    @pytest.mark.unit
    def test_score_zero(self) -> None:
        r = Routine(domain="x", successes=1, failures=1)
        assert r.score == 0

    @pytest.mark.unit
    def test_as_prior_text_empty_steps(self) -> None:
        r = Routine(domain="x")
        assert r.as_prior_text() == ""

    @pytest.mark.unit
    def test_as_prior_text_with_steps(self) -> None:
        steps = (
            RoutineStep(kind="fill", ref="#name", role="textbox", name="Name"),
            RoutineStep(kind="select", ref="#country", attribute_id="attr-1"),
            RoutineStep(kind="upload", document_id="doc-resume"),
            RoutineStep(kind="click"),  # no optional slots
        )
        r = Routine(domain="x", steps=steps)
        text = r.as_prior_text()
        lines = text.split("\n")
        assert len(lines) == 4
        assert "- fill ref=#name role=textbox name=Name" in lines[0]
        assert "- select ref=#country attribute_id=attr-1" in lines[1]
        assert "- upload document_id=doc-resume" in lines[2]
        assert "- click" in lines[3]

    @pytest.mark.unit
    def test_equality(self) -> None:
        steps = (RoutineStep(kind="fill"),)
        r1 = Routine(domain="x", steps=steps, successes=1, failures=0)
        r2 = Routine(domain="x", steps=steps, successes=1, failures=0)
        r3 = Routine(domain="y", steps=steps)
        assert r1 == r2
        assert r1 != r3

    @pytest.mark.unit
    def test_hashable(self) -> None:
        r = Routine(domain="x")
        s = {r}
        assert r in s

    @pytest.mark.unit
    def test_repr(self) -> None:
        r = Routine(domain="ats.io")
        rep = repr(r)
        assert "Routine" in rep
        assert "domain=" in rep

    @pytest.mark.unit
    def test_frozen(self) -> None:
        r = Routine(domain="x")
        with pytest.raises(AttributeError):
            r.domain = "y"  # type: ignore[misc]


class TestRoutineStoreProtocol:
    """RoutineStore runtime_checkable Protocol — isinstance checks."""

    @pytest.mark.unit
    def test_runtime_checkable(self) -> None:
        """RoutineStore is marked @runtime_checkable."""
        assert hasattr(RoutineStore, "__instancecheck__")
        assert hasattr(RoutineStore, "__subclasscheck__")

    @pytest.mark.unit
    def test_concrete_implementation_passes_isinstance(self) -> None:
        class InMemoryStore:
            def __init__(self) -> None:
                self._store: dict[str, Routine] = {}

            def get(self, domain: str) -> Routine | None:
                return self._store.get(domain)

            def induce(self, domain: str, steps: tuple[RoutineStep, ...]) -> Routine | None:
                if not steps:
                    return None
                r = Routine(domain=domain, steps=steps, successes=1)
                self._store[domain] = r
                return r

            def record_success(self, domain: str) -> None:
                if domain in self._store:
                    r = self._store[domain]
                    self._store[domain] = Routine(
                        domain=r.domain, steps=r.steps,
                        successes=r.successes + 1, failures=r.failures,
                        source=r.source,
                    )

            def record_failure(self, domain: str) -> Routine | None:
                if domain not in self._store:
                    return None
                r = self._store[domain]
                new_failures = r.failures + 1
                if new_failures - r.successes >= DEFAULT_PRUNE_THRESHOLD:
                    del self._store[domain]
                    return None
                updated = Routine(
                    domain=r.domain, steps=r.steps,
                    successes=r.successes, failures=new_failures,
                    source=r.source,
                )
                self._store[domain] = updated
                return updated

        store = InMemoryStore()
        assert isinstance(store, RoutineStore)

    @pytest.mark.unit
    def test_non_implementing_class_fails_isinstance(self) -> None:
        class NotAStore:
            pass

        assert not isinstance(NotAStore(), RoutineStore)

    @pytest.mark.unit
    def test_method_signatures_available(self) -> None:
        """Protocol defines get, induce, record_success, record_failure."""
        assert hasattr(RoutineStore, "get")
        assert hasattr(RoutineStore, "induce")
        assert hasattr(RoutineStore, "record_success")
        assert hasattr(RoutineStore, "record_failure")


class TestConstants:
    """Module-level constants."""

    @pytest.mark.unit
    def test_default_prune_threshold(self) -> None:
        assert DEFAULT_PRUNE_THRESHOLD == 3
