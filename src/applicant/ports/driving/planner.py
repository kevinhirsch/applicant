"""PlannerPort — driving port for the plan-as-data typed-DSL planner.

The PlannerPort is the driving port every surface (pre-fill, scrape, whole-
application) uses to request a plan. The same typed-DSL contract is used
across all surfaces.

Implementations:
* The real LLM-backed planner emits typed operations over a semantic-DOM
  snapshot.
* The test stub returns canned plans.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.rules.plan import Plan, PlanValidationResult, ReadOnlyScrapePlan


@runtime_checkable
class PlannerPort(Protocol):
    """Driving port: the engine's plan-as-data planner.

    Every surface requests a typed-DSL plan through this port. The same
    contract is used for pre-fill, scrape, and whole-application flows.
    """

    def plan_prefill(
        self,
        page_url: str,
        fields: list[dict],
        attributes: dict[str, str],
    ) -> Plan:
        """Emit a typed-DSL plan for a pre-fill page.

        Args:
            page_url: The URL of the page to plan for.
            fields: Detected fields on the page (label, selector, type).
            attributes: Attribute cloud (attribute_id -> value).

        Returns:
            A validated Plan with fill/select/advance ops.
        """
        ...

    def plan_scrape(
        self,
        page_url: str,
        fields: list[dict],
    ) -> ReadOnlyScrapePlan:
        """Emit a read-only scrape plan for a page.

        Args:
            page_url: The URL of the page to scrape.
            fields: Detected fields on the page.

        Returns:
            A ReadOnlyScrapePlan with only EXTRACT ops.
        """
        ...

    def validate_plan(
        self,
        plan: Plan,
        *,
        allowed_ops: frozenset | None = None,
    ) -> PlanValidationResult:
        """Validate a plan against the plan-as-data schema.

        Args:
            plan: The plan to validate.
            allowed_ops: Optional override for the allowed op-set.

        Returns:
            PlanValidationResult indicating validity.
        """
        ...

    def resolve_fill_values(
        self,
        plan: Plan,
        attribute_map: dict[str, str],
    ) -> PlanValidationResult:
        """Resolve fill values from the attribute cloud.

        Args:
            plan: The plan with attribute_id references.
            attribute_map: Attribute cloud (attribute_id -> value).

        Returns:
            PlanValidationResult with resolved operations.
        """
        ...

    def stop_boundary_check(self, plan: Plan) -> bool:
        """Check whether a plan crosses the stop-boundary.

        A plan that contains FINAL_SUBMIT or ACCOUNT_CREATE ops crosses the
        stop-boundary and must be withheld for human review.

        Returns:
            True if the plan stays within the stop-boundary.
        """
        ...
