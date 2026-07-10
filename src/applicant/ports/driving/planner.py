"""PlannerPort — the driving (inbound) port for plan-as-data execution.

The planner is the **intelligence layer**: given a goal, an observation of the
current page (semantic DOM snapshot), the attribute-cloud manifest, and
constraints (stop-boundary rules), it emits one :class:`~applicant.core.entities.plan.Plan`
that the executor harness runs.

This replaces per-step LLM reasoning with a single plan emission, cutting model
round-trips from O(N) to O(1) per page while keeping all safety guarantees intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from applicant.core.entities.plan import Plan


@dataclass(frozen=True)
class PlannerObservation:
    """A snapshot of the current page the planner sees — semantic, not pixel.

    Contains interactive elements with their role, accessible name, nearby label
    text, current value, and a stable ``ref`` (``data-applicant-ref``).
    """

    snapshot_tokens: int = 0
    html_summary: str = ""
    detected_fields: list[dict] | None = None
    url: str = ""
    #: #305 vision lane: an optional base64-encoded PNG screenshot of the RENDERED
    #: page. When present the planner builds a MULTIMODAL prompt (image + text-DOM)
    #: so the model can ground its typed ops against canvas / image-map / purely
    #: visual forms the semantic DOM misses. ``None`` (the default) keeps the
    #: text-only prompt byte-identical. The screenshot only improves GROUNDING — the
    #: emitted plan still fills by ``attribute_id`` through the DSL, so vision can
    #: never inject a literal value or cross the stop-boundary.
    screenshot: str | None = None


@dataclass(frozen=True)
class PlannerInput:
    """Everything the planner needs to emit a plan."""

    goal: str
    observation: PlannerObservation | None = None
    facts: dict[str, str] | None = None  # attribute_id -> label
    constraints: dict[str, str] | None = None
    previous_plan_id: str | None = None
    failure_reason: str | None = None  # set on replan (self-correction loop)
    #: #306 AWM prior-injection: a compact, data-only summary of a routine that
    #: worked on this domain before (rendered by ``Routine.as_prior_text``). When
    #: present the planner injects it as a planning prior so coverage grows itself.
    #: It carries only op kinds + ids/locators — never a literal value — so it
    #: cannot leak a fabricated answer into the plan.
    prior_routine: str | None = None
    #: #306 Reflexion: a short reflection on the previous attempt's failure (what
    #: broke + why, e.g. a broken selector), richer than the bare ``failure_reason``,
    #: fed back into a reflective re-plan so a broken selector re-plans, not dead-stops.
    reflection: str | None = None


@runtime_checkable
class PlannerPort(Protocol):
    """Driving port: emit a Plan from goal + observation + facts + constraints."""

    def plan(self, input_: PlannerInput) -> Plan:
        """Emit a Plan to achieve ``goal`` given the current observation.

        The plan is validated by the caller before execution. If the planner
        cannot construct a valid plan (e.g. insufficient information), it returns
        an empty plan and the caller escalates to the human.
        """
        ...

    def plan_many(self, goal: str, pages: list[PlannerObservation], facts: dict[str, str]) -> list[Plan]:
        """Emit a plan for each page in a multi-page journey (flow planning).

        The flow planner plans the application journey once — enter application,
        navigate, fill page(s), stop at the first irreducible human step — and
        delegates each page to the page-level planner.
        """
        ...
