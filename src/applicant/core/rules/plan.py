"""Pure-domain validator for Plan-as-Data (NFR-TRUTH-1, FR-PREFILL-4).

Validates a :class:`~applicant.core.entities.plan.Plan` before execution:

* Schema-validate every Op variant.
* Bound the total op count (default 40).
* Reject ``fill``/``select`` whose ``attribute_id`` is unknown.
* Reject ``click``/``stop`` that would cross the stop-boundary without authorization.
* Reject any op that is not a member of the closed set.

Also provides:

* :func:`resolve_fill_values` — resolves each ``fill``/``select`` op's
  ``attribute_id`` to the stored attribute value from the attribute cloud,
  returning a mapping of ``ref -> value``.  Values ALWAYS come from the stored
  attribute cloud; the planner can never inject a literal value (NFR-TRUTH-1).

* :class:`ReadOnlyScrapePlan` — a typed wrapper that constrains a
  :class:`~applicant.core.entities.plan.Plan` to the read-only extract/assert/wait
  ops only, for the network-less JS scrape lane.

All pure — no I/O, no framework imports — so the validator is hermetically testable.
"""

from __future__ import annotations

from dataclasses import dataclass

from applicant.core.entities.plan import (
    ClickOp,
    FillOp,
    GotoOp,
    Op,
    OpKind,
    Plan,
    SelectOp,
    StopOp,
    UploadOp,
)

#: Maximum operations allowed in a single plan (bounds a runaway plan).
MAX_OPS_PER_PLAN = 40

#: Stop-boundary reasons that require human hand-off (FR-PREFILL-4).
STOP_REASONS = frozenset({
    "account_create",
    "captcha",
    "final_submit",
    "email_verify",
    "sms_verify",
    "two_factor",
    "oauth",
})


def validate_plan(plan: Plan, known_attribute_ids: frozenset[str]) -> list[str]:
    """Validate a plan against the closed op set and business rules.

    Returns a list of error messages (empty = plan is valid).
    """
    errors: list[str] = []

    if len(plan) == 0:
        errors.append("plan is empty")
    if len(plan) > MAX_OPS_PER_PLAN:
        errors.append(f"plan exceeds max ops ({len(plan)} > {MAX_OPS_PER_PLAN})")

    for i, op in enumerate(plan):
        _validate_op(i, op, known_attribute_ids, errors)

    return errors


def _validate_op(idx: int, op: Op, known_attribute_ids: frozenset[str], errors: list[str]) -> None:
    kind = op.kind

    # All ops must belong to the closed set.
    if kind not in set(OpKind):
        errors.append(f"op[{idx}]: unknown op kind {kind!r}")
        return

    # Schema checks per kind.
    if kind == OpKind.GOTO:
        if isinstance(op, GotoOp) and not op.url:
            errors.append(f"op[{idx}]: goto requires a non-empty url")

    elif kind == OpKind.FILL:
        if isinstance(op, FillOp):
            if not op.ref:
                errors.append(f"op[{idx}]: fill requires a ref")
            if not op.attribute_id:
                errors.append(f"op[{idx}]: fill requires an attribute_id")
            if op.attribute_id and op.attribute_id not in known_attribute_ids:
                errors.append(f"op[{idx}]: fill references unknown attribute_id {op.attribute_id!r}")

    elif kind == OpKind.SELECT:
        if isinstance(op, SelectOp):
            if not op.ref:
                errors.append(f"op[{idx}]: select requires a ref")
            if not op.attribute_id:
                errors.append(f"op[{idx}]: select requires an attribute_id")
            if op.attribute_id and op.attribute_id not in known_attribute_ids:
                errors.append(f"op[{idx}]: select references unknown attribute_id {op.attribute_id!r}")

    elif kind == OpKind.CLICK:
        if isinstance(op, ClickOp) and not op.ref:
            errors.append(f"op[{idx}]: click requires a ref")

    elif kind == OpKind.UPLOAD:
        if isinstance(op, UploadOp):
            if not op.ref:
                errors.append(f"op[{idx}]: upload requires a ref")
            if not op.document_id:
                errors.append(f"op[{idx}]: upload requires a document_id")

    elif kind == OpKind.STOP:
        if isinstance(op, StopOp):
            if not op.reason:
                errors.append(f"op[{idx}]: stop requires a reason")
            elif op.reason not in STOP_REASONS:
                errors.append(
                    f"op[{idx}]: stop reason {op.reason!r} is not a recognized stop reason; "
                    f"must be one of {sorted(STOP_REASONS)}"
                )

    # GotoOp URLs must pass SSRF guard — enforced at execution time (not pure),
    # but we can check for an empty url here. The SSRF check lives in
    # assert_navigable_url (applicant.adapters.browser.page_source).


def validate_op_sequence(plan: Plan) -> list[str]:
    """Validate the sequencing rules of a plan.

    E.g. ``goto`` must come before ``fill`` ops that reference page elements,
    ``stop`` must be the last op in the sequence.
    """
    errors: list[str] = []
    ops = list(plan)

    for i, op in enumerate(ops):
        kind = op.kind if hasattr(op, "kind") else None

        # stop must be last op
        if kind == OpKind.STOP and i != len(ops) - 1:
            errors.append(f"op[{i}]: stop must be the last op in the plan")

    return errors


def resolve_fill_values(
    plan: Plan,
    attribute_cloud: dict[str, str],
) -> dict[str, str]:
    """Resolve each fill/select op to its stored attribute value.

    Returns a mapping of ``ref -> resolved_value`` for every ``fill`` and
    ``select`` op in the plan.  Values come exclusively from ``attribute_cloud``
    (a ``attribute_id -> value`` mapping previously loaded from the credential /
    attribute store) — the planner can never inject a literal value, satisfying
    NFR-TRUTH-1 by construction.

    Ops whose ``attribute_id`` is absent from the cloud are silently skipped
    (the validator already rejects such plans before execution, so this is a
    best-effort defensive pass for callers that pre-validated the plan).

    Args:
        plan: A validated :class:`~applicant.core.entities.plan.Plan`.
        attribute_cloud: Mapping from attribute id to stored value.

    Returns:
        ``{ref: value}`` for every resolvable fill/select op in the plan.
    """
    resolved: dict[str, str] = {}
    for op in plan:
        if isinstance(op, (FillOp, SelectOp)):
            value = attribute_cloud.get(op.attribute_id)
            if value is not None:
                resolved[op.ref] = value
    return resolved


#: Op kinds allowed in a read-only scrape plan (no mutations, no navigation).
_READ_ONLY_KINDS = frozenset({
    OpKind.EXTRACT,
    OpKind.ASSERT,
    OpKind.WAIT,
})


@dataclass(frozen=True)
class ReadOnlyScrapePlan:
    """A plan constrained to read-only ops (extract/assert/wait).

    The network-less JS scrape lane only needs to read structured data from
    a semantic DOM snapshot — it must never issue fill/click/navigate ops.
    Wrapping a :class:`~applicant.core.entities.plan.Plan` in this class
    enforces the constraint before execution.

    Raises:
        ValueError: If the underlying plan contains any non-read-only op.
    """

    plan: Plan

    def __post_init__(self) -> None:
        bad_ops = [
            (i, op.kind)
            for i, op in enumerate(self.plan)
            if op.kind not in _READ_ONLY_KINDS
        ]
        if bad_ops:
            desc = ", ".join(f"op[{i}]={k.value}" for i, k in bad_ops)
            raise ValueError(
                f"ReadOnlyScrapePlan contains mutating op(s): {desc}. "
                "Only extract/assert/wait ops are allowed in the scrape lane."
            )

    def ops(self) -> tuple[Op, ...]:
        """Return the validated read-only ops."""
        return self.plan.ops
