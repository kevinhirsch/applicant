"""Plan-as-data: typed-DSL planner over a semantic-DOM snapshot.

Plan-once architecture: the model emits a typed operation list over a
semantic-DOM snapshot; the browser harness executes each op through the
existing guarded actions. Safety holds by construction because:

* Fill/select ops resolve values by attribute id (never LLM free-text).
* Consequential ops (submit, account-create) stay behind the stop-boundary.
* The scrape lane is read-only and network-less.

This module defines the typed operation set (the DSL), validates plans against
the schema, and resolves fill values from the attribute cloud.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# ── Typed operation set (the DSL) ──────────────────────────────────────────


class PlanOpType(str, Enum):
    """Allowed typed operations in the plan-as-data DSL.

    Each operation maps to a guarded action in the browser harness.
    """

    # ── fill / select operations ──────────────────────────────────────────
    FILL = "fill"
    """Type a value into a text / textarea / email / password field.
    Resolves by attribute id; never LLM free-text (FR-PREFILL-3)."""

    SELECT_OPTION = "select_option"
    """Choose an option from a <select> or custom listbox/combobox.
    Resolves by attribute id."""

    UPLOAD_FILE = "upload_file"
    """Attach a file to an <input type=file>. Resolves the résumé path."""

    CLICK = "click"
    """Click a benign control (next, continue, add) — NOT final submit.
    Only allowed when the stop-boundary check passes."""

    # ── page navigation ───────────────────────────────────────────────────
    ADVANCE = "advance"
    """Move to the next page in a multi-step flow. Equivalent to clicking
    a Next/Continue button — no final submit."""

    # ── scrape lane (read-only / network-less) ────────────────────────────
    EXTRACT = "extract"
    """Read a value from the page without mutating any field or issuing
    a network request. Only allowed in a ReadOnlyScrapePlan."""

    # ── consequential operations (stop-boundary gated) ────────────────────
    FINAL_SUBMIT = "final_submit"
    """The final submit-application action. NEVER auto-authorized;
    withheld for human review."""

    ACCOUNT_CREATE = "account_create"
    """Create a new ATS account. Gated by automated-accounts policy."""

    ACCOUNT_LOGIN = "account_login"
    """Log in with a stored credential. The credential must be banked."""


#: The allowed operation set for pre-fill plans (everything except FINAL_SUBMIT
#: and ACCOUNT_CREATE — those are stop-boundary gated).
PREFILL_OPS: frozenset[PlanOpType] = frozenset(
    {
        PlanOpType.FILL,
        PlanOpType.SELECT_OPTION,
        PlanOpType.UPLOAD_FILE,
        PlanOpType.CLICK,
        PlanOpType.ADVANCE,
        PlanOpType.ACCOUNT_LOGIN,
    }
)

#: The allowed operation set for read-only scrape plans. Network-less and
#: non-mutating by construction.
SCRAPE_OPS: frozenset[PlanOpType] = frozenset({PlanOpType.EXTRACT})


@dataclass(frozen=True)
class PlanOp:
    """A single typed operation in a plan.

    Every operation references either an attribute id (for fill/select) or a
    selector (for click/advance). The type field determines which is used.
    """

    type: PlanOpType
    """The typed operation kind."""

    attribute_id: str | None = None
    """The semantic-DOM attribute id this op resolves to.
    Required for: FILL, SELECT_OPTION, UPLOAD_FILE.
    Must match an entry in the attribute cloud."""

    selector: str | None = None
    """The DOM selector for the target element.
    Required for: FILL, SELECT_OPTION, UPLOAD_FILE, CLICK, EXTRACT."""

    value: str | None = None
    """A literal value (resolved from the attribute cloud at plan time).
    Set during validation/resolution; not present at emission time."""

    label: str | None = None
    """Human-readable label for the field (for logging / audit)."""

    metadata: dict[str, str] = field(default_factory=dict)
    """Arbitrary metadata (page url, confidence, etc.)."""

    def validated(self) -> PlanOp:
        """Return a copy after asserting the op is internally consistent."""
        if self.type in (PlanOpType.FILL, PlanOpType.SELECT_OPTION, PlanOpType.UPLOAD_FILE):
            if not self.attribute_id:
                raise ValueError(f"{self.type} op requires attribute_id")
            if not self.selector:
                raise ValueError(f"{self.type} op requires selector")
        if self.type == PlanOpType.CLICK:
            if not self.selector:
                raise ValueError("CLICK op requires selector")
        if self.type == PlanOpType.EXTRACT:
            if not self.selector:
                raise ValueError("EXTRACT op requires selector")
        if self.type in (PlanOpType.FINAL_SUBMIT, PlanOpType.ACCOUNT_CREATE):
            if self.selector:
                raise ValueError(
                    f"{self.type} op must NOT carry a selector "
                    f"(it is a page-level action)"
                )
        return self


@dataclass(frozen=True)
class Plan:
    """A typed-DSL plan: an ordered list of operations over a semantic-DOM snapshot.

    Plans are immutable after creation. Validation runs at construction time.
    """

    ops: tuple[PlanOp, ...]
    """Ordered list of operations to execute."""

    plan_id: str | None = None
    """Optional stable identifier for dedup / caching."""

    page_url: str | None = None
    """The URL of the page this plan targets."""

    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the plan at construction time."""
        for op in self.ops:
            op.validated()


# ── Plan validation ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlanValidationResult:
    """Result of validating a plan against the plan-as-data schema."""

    valid: bool
    """True if the plan passes all validation rules."""

    errors: tuple[str, ...] = ()
    """Validation error messages (non-empty when valid is False)."""

    resolved_ops: tuple[PlanOp, ...] = ()
    """The validated operations with fill values resolved from the cloud."""


def validate_plan(plan: Plan, *, allowed_ops: frozenset[PlanOpType] | None = None) -> PlanValidationResult:
    """Validate a plan against the allowed op-set.

    Checks:
    * Every op type is in the allowed set.
    * Every fill/select/file op references a non-empty attribute_id.
    * Every op with a selector has a non-empty selector.
    * No op references a value (that is resolved later).
    * Consequential ops (FINAL_SUBMIT, ACCOUNT_CREATE) are recognized.

    Returns a PlanValidationResult. When valid is False, the errors tuple
    contains human-readable messages.
    """
    if allowed_ops is None:
        allowed_ops = PREFILL_OPS

    errors: list[str] = []

    for i, op in enumerate(plan.ops):
        # Check op type is allowed
        if op.type not in allowed_ops:
            errors.append(
                f"op[{i}]: type {op.type.value!r} is not in the allowed op-set "
                f"({sorted(o.value for o in allowed_ops)})"
            )
            continue

        # Structural checks
        if op.type in (PlanOpType.FILL, PlanOpType.SELECT_OPTION, PlanOpType.UPLOAD_FILE):
            if not op.attribute_id:
                errors.append(f"op[{i}]: {op.type.value} op missing attribute_id")
            if not op.selector:
                errors.append(f"op[{i}]: {op.type.value} op missing selector")
            if op.value is not None:
                errors.append(
                    f"op[{i}]: {op.type.value} op must NOT carry a pre-resolved "
                    f"value"
                )

        if op.type == PlanOpType.CLICK:
            if not op.selector:
                errors.append(f"op[{i}]: CLICK op missing selector")

        if op.type == PlanOpType.EXTRACT:
            if not op.selector:
                errors.append(f"op[{i}]: EXTRACT op missing selector")

        # Check for unknown attribute ids (basic: non-empty + no whitespace-only)
        if op.attribute_id and not op.attribute_id.strip():
            errors.append(f"op[{i}]: attribute_id is whitespace-only")

    if errors:
        return PlanValidationResult(valid=False, errors=tuple(errors))

    return PlanValidationResult(valid=True, resolved_ops=plan.ops)


def resolve_fill_values(
    plan: Plan,
    attribute_map: dict[str, str],
    *,
    allowed_ops: frozenset[PlanOpType] | None = None,
) -> PlanValidationResult:
    """Resolve fill values from the attribute cloud for every fill/select/file op.

    Each op's attribute_id is looked up in ``attribute_map`` (attribute_id -> value).
    If any attribute_id is missing, the plan is rejected — no LLM fallback at this
    layer (the calling harness may escalate, but the plan-as-data contract is
    attribute-id-bound).

    Returns a PlanValidationResult with resolved_ops populated on success.
    """
    if allowed_ops is None:
        allowed_ops = PREFILL_OPS

    # First validate structure
    base = validate_plan(plan, allowed_ops=allowed_ops)
    if not base.valid:
        return base

    resolved: list[PlanOp] = []
    errors: list[str] = []

    for i, op in enumerate(plan.ops):
        if op.type in (PlanOpType.FILL, PlanOpType.SELECT_OPTION, PlanOpType.UPLOAD_FILE):
            value = attribute_map.get(op.attribute_id)
            if value is None:
                errors.append(
                    f"op[{i}]: attribute_id {op.attribute_id!r} not found "
                    f"in attribute cloud"
                )
                continue
            resolved.append(
                PlanOp(
                    type=op.type,
                    attribute_id=op.attribute_id,
                    selector=op.selector,
                    value=value,
                    label=op.label,
                    metadata=op.metadata,
                )
            )
        else:
            resolved.append(op)

    if errors:
        return PlanValidationResult(valid=False, errors=tuple(errors))

    return PlanValidationResult(valid=True, resolved_ops=tuple(resolved))


# ── ReadOnlyScrapePlan ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReadOnlyScrapePlan:
    """A read-only scrape plan over a semantic-DOM snapshot.

    Guaranteed by construction:
    * All ops are EXTRACT ops (read-only, network-less).
    * No op can mutate the page or issue network requests.
    """

    plan: Plan

    def __post_init__(self) -> None:
        """Validate that every op is an EXTRACT op."""
        for op in self.plan.ops:
            if op.type != PlanOpType.EXTRACT:
                raise ValueError(
                    f"ReadOnlyScrapePlan only allows EXTRACT ops, "
                    f"got {op.type.value!r}"
                )
        # Validate the underlying plan
        result = validate_plan(self.plan, allowed_ops=SCRAPE_OPS)
        if not result.valid:
            raise ValueError(
                f"ReadOnlyScrapePlan validation failed: {result.errors}"
            )

    @property
    def ops(self) -> tuple[PlanOp, ...]:
        return self.plan.ops
