"""Self-improvement learning flywheel — AWM + ACE + Reflexion stubs (#306).

This module defines the ARCHITECTURE for the next-generation self-improvement loop
that layers three metacognitive patterns on top of the Phase-1 statistical learning
and Phase-4 advanced cross-referencing:

  **AWM — Agent Workflow Memory (FR-MIND-14)**
    Durable traces of WHAT the agent did in previous runs (sources queried,
    roles scored, applications submitted, outcomes observed) so future runs can
    retrieve relevant prior experience — not just the aggregate statistics the
    LearningService already maintains.

  **ACE — Agent Cognitive Evolution (FR-LEARN-8)**
    Periodic re-evaluation of the agent's own prompts, heuristics, and scoring
    thresholds against observed outcomes. If a certain source-yield weight or
    scoring parameter consistently underperforms, ACE proposes an adjustment.

  **Reflexion (FR-LEARN-9)**
    After each complete campaign cycle (discovery → digest → application →
    outcome), the agent reflects on what worked and what didn't, producing a
    short natural-language "lesson" that is stored in the curated memory store
    and available to future runs as advisory context.

These three patterns form a **flywheel**: AWM provides the raw material (what
happened), Reflexion distills it into lessons (why it matters), and ACE adjusts
the knobs (how to do better). All three are non-blocking (run as background
curation after the main loop) and advisory-only (they can never override the
user's hard criteria or escalate authority).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from applicant.observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# AWM — Agent Workflow Memory (#306)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class WorkflowTrace:
    """A single trace of one campaign run's workflow (AWM).

    Persisted so future runs can retrieve relevant prior experience — not just
    the aggregate statistics the LearningService already maintains.
    """

    campaign_id: str
    run_id: str
    sources_queried: tuple[str, ...] = ()
    roles_scored: int = 0
    applications_submitted: int = 0
    outcomes: tuple[str, ...] = ()
    summary: str = ""


class AgentWorkflowMemory:
    """Stub: durable workflow memory for future-run retrieval (FR-MIND-14).

    The interface is intentionally minimal: ``record`` writes a trace after
    each campaign cycle; ``relevant`` retrieves traces similar to the current
    context for advisory use in scoring/discovery bias. Backends (in-memory,
    Postgres, vector) are swappable via the storage port.
    """

    def __init__(self, storage: Any = None) -> None:
        self._storage = storage

    def record(self, trace: WorkflowTrace) -> None:
        """Persist a workflow trace for future retrieval."""
        log.debug("awm_record", campaign_id=trace.campaign_id, run_id=trace.run_id)

    def relevant(
        self, campaign_id: str, *, limit: int = 5
    ) -> list[WorkflowTrace]:
        """Retrieve prior traces relevant to a campaign."""
        return []


# ---------------------------------------------------------------------------
# ACE — Agent Cognitive Evolution (#306)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ParameterSuggestion:
    """A proposed adjustment to a learning/scoring parameter (ACE)."""

    parameter: str
    current_value: float
    suggested_value: float
    rationale: str
    confidence: float  # 0.0–1.0


class AgentCognitiveEvolution:
    """Stub: periodic re-evaluation of agent parameters (FR-LEARN-8).

    After N runs, ACE reviews the observed output metrics (source yield,
    approval rate, conversion rate) against the current parameter settings
    (source weights, scoring bias cap, exploration budget, discount factor)
    and proposes parameter adjustments that are staged for operator review
    before taking effect.
    """

    def __init__(self, learning_service: Any = None) -> None:
        self._learning = learning_service
        self._run_counter: int = 0
        self._eval_interval: int = 10  # runs between evaluations

    def suggest_adjustments(self, campaign_id: str) -> list[ParameterSuggestion]:
        """Review recent outcomes and suggest parameter tweaks."""
        self._run_counter += 1
        if self._run_counter < self._eval_interval:
            return []
        self._run_counter = 0
        log.info("ace_evaluation", campaign_id=campaign_id)
        return []


# ---------------------------------------------------------------------------
# Reflexion (#306)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Lesson:
    """A natural-language lesson distilled from one campaign cycle (Reflexion).

    ``text`` is a short (< 500 char) plain-language observation.
    ``tags`` help retrieval (e.g. ``["discovery", "source_yield"]``).
    """

    campaign_id: str
    text: str
    tags: tuple[str, ...] = ()


class ReflexionEngine:
    """Stub: post-cycle reflection producing lessons (FR-LEARN-9).

    After a complete campaign cycle, Reflexion reviews what happened
    (discovery counts, digest approvals/declines, submission outcomes)
    and produces short natural-language lessons stored in the curated
    memory store for advisory context in future runs.
    """

    def __init__(self, memory_store: Any = None) -> None:
        self._memory = memory_store

    def reflect(self, campaign_id: str, cycle_data: dict) -> list[Lesson]:
        """Analyze a completed cycle and return lessons learned."""
        log.debug("reflexion_reflect", campaign_id=campaign_id)
        return []


# ---------------------------------------------------------------------------
# Flywheel coordinator (#306)
# ---------------------------------------------------------------------------
class LearningFlywheel:
    """Coordinator for the AWM + ACE + Reflexion self-improvement loop (#306).

    Orchestrates the three metacognitive patterns so they share one scheduling
    tick and do not interfere with the main agent loop. Runs as a non-blocking
    background pass (FR-MIND-7 style).

    Default state: all three patterns are **stubs** that record no-op traces.
    Operators opt in by wiring real backends (Postgres AWM store, LLM-backed
    Reflexion, ACE evaluator) behind the interfaces above.
    """

    def __init__(
        self,
        *,
        awm: AgentWorkflowMemory | None = None,
        ace: AgentCognitiveEvolution | None = None,
        reflexion: ReflexionEngine | None = None,
    ) -> None:
        self._awm = awm or AgentWorkflowMemory()
        self._ace = ace or AgentCognitiveEvolution()
        self._reflexion = reflexion or ReflexionEngine()

    def tick(self, campaign_id: str, cycle_data: dict | None = None) -> None:
        """One flywheel tick — record, reflect, suggest."""
        data = cycle_data or {}
        trace = WorkflowTrace(
            campaign_id=campaign_id,
            run_id=data.get("run_id", ""),
            sources_queried=tuple(data.get("sources_queried", [])),
            roles_scored=int(data.get("roles_scored", 0)),
            applications_submitted=int(data.get("applications_submitted", 0)),
            outcomes=tuple(data.get("outcomes", [])),
            summary=data.get("summary", ""),
        )
        self._awm.record(trace)
        lessons = self._reflexion.reflect(campaign_id, data)
        for lesson in lessons:
            log.info("flywheel_lesson", text=lesson.text, tags=lesson.tags)
        suggestions = self._ace.suggest_adjustments(campaign_id)
        for s in suggestions:
            log.info("flywheel_suggestion", param=s.parameter, to=s.suggested_value)
