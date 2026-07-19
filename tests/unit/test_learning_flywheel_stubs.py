"""Unit tests for the #306 learning flywheel stubs (AWM, ACE, Reflexion)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from applicant.application.services.learning_flywheel import (
    AgentCognitiveEvolution,
    AgentWorkflowMemory,
    LearningFlywheel,
    Lesson,
    ParameterSuggestion,
    ReflexionEngine,
    WorkflowTrace,
)


@pytest.fixture(autouse=True)
def _xdist_safe() -> None:
    """No module-level caches, but required for parallel safety."""
    return


class TestWorkflowTrace:
    """Tests for the WorkflowTrace frozen dataclass."""

    def test_minimal_creation(self) -> None:
        trace = WorkflowTrace(campaign_id="camp-1", run_id="run-1")
        assert trace.campaign_id == "camp-1"
        assert trace.run_id == "run-1"
        assert trace.sources_queried == ()
        assert trace.roles_scored == 0
        assert trace.applications_submitted == 0
        assert trace.outcomes == ()
        assert trace.summary == ""

    def test_frozen_cannot_mutate(self) -> None:
        trace = WorkflowTrace(campaign_id="c", run_id="r")
        with pytest.raises(FrozenInstanceError):
            trace.summary = "changed"  # type: ignore[misc]

    def test_full_initialization(self) -> None:
        trace = WorkflowTrace(
            campaign_id="camp-2",
            run_id="run-2",
            sources_queried=("src-a", "src-b"),
            roles_scored=3,
            applications_submitted=2,
            outcomes=("applied",),
            summary="test summary",
        )
        assert trace.sources_queried == ("src-a", "src-b")
        assert trace.roles_scored == 3
        assert trace.applications_submitted == 2
        assert trace.outcomes == ("applied",)
        assert trace.summary == "test summary"


class TestAgentWorkflowMemory:
    """Tests for the AgentWorkflowMemory stub."""

    def test_default_storage_none(self) -> None:
        awm = AgentWorkflowMemory()
        assert awm._storage is None

    def test_record_does_not_raise(self) -> None:
        awm = AgentWorkflowMemory()
        trace = WorkflowTrace(campaign_id="c", run_id="r")
        awm.record(trace)

    def test_relevant_returns_empty(self) -> None:
        awm = AgentWorkflowMemory()
        assert awm.relevant("camp-1") == []

    def test_relevant_with_limit(self) -> None:
        awm = AgentWorkflowMemory()
        assert awm.relevant("camp-1", limit=10) == []


class TestParameterSuggestion:
    """Tests for the ParameterSuggestion dataclass."""

    def test_all_fields(self) -> None:
        sug = ParameterSuggestion(
            parameter="source_weight",
            current_value=0.5,
            suggested_value=0.7,
            rationale="better yield",
            confidence=0.85,
        )
        assert sug.parameter == "source_weight"
        assert sug.current_value == 0.5
        assert sug.suggested_value == 0.7
        assert sug.rationale == "better yield"
        assert sug.confidence == 0.85


class TestAgentCognitiveEvolution:
    """Tests for the AgentCognitiveEvolution stub."""

    def test_default_construction(self) -> None:
        ace = AgentCognitiveEvolution()
        assert ace._learning is None
        assert ace._run_counter == 0
        assert ace._eval_interval == 10

    def test_suggest_adjustments_below_interval(self) -> None:
        ace = AgentCognitiveEvolution()
        result = ace.suggest_adjustments("camp-1")
        assert result == []
        assert ace._run_counter == 1


class TestLesson:
    """Tests for the Lesson dataclass."""

    def test_minimal(self) -> None:
        lesson = Lesson(campaign_id="c", text="learn to test")
        assert lesson.campaign_id == "c"
        assert lesson.text == "learn to test"
        assert lesson.tags == ()

    def test_with_tags(self) -> None:
        lesson = Lesson(campaign_id="c", text="hello", tags=("discovery",))
        assert lesson.tags == ("discovery",)

    def test_frozen(self) -> None:
        lesson = Lesson(campaign_id="c", text="hi")
        with pytest.raises(FrozenInstanceError):
            lesson.text = "bye"  # type: ignore[misc]


class TestReflexionEngine:
    """Tests for the ReflexionEngine stub."""

    def test_default_construction(self) -> None:
        eng = ReflexionEngine()
        assert eng._memory is None

    def test_reflect_returns_empty(self) -> None:
        eng = ReflexionEngine()
        assert eng.reflect("camp-1", {}) == []


class TestLearningFlywheel:
    """Tests for the LearningFlywheel coordinator."""

    def test_default_construction(self) -> None:
        fw = LearningFlywheel()
        assert isinstance(fw._awm, AgentWorkflowMemory)
        assert isinstance(fw._ace, AgentCognitiveEvolution)
        assert isinstance(fw._reflexion, ReflexionEngine)

    def test_tick_does_not_raise(self) -> None:
        fw = LearningFlywheel()
        fw.tick("camp-1")

    def test_tick_with_data(self) -> None:
        fw = LearningFlywheel()
        data = {
            "run_id": "run-42",
            "sources_queried": ["indeed"],
            "roles_scored": 2,
            "applications_submitted": 1,
            "outcomes": ["submitted"],
            "summary": "applied to indeed",
        }
        fw.tick("camp-1", data)
