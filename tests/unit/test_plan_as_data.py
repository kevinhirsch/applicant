"""Unit tests for Plan-as-Data core entities and validator."""

from __future__ import annotations

import pytest

from applicant.core.entities.plan import (
    ClickOp,
    FillOp,
    GotoOp,
    OpKind,
    Plan,
    SelectOp,
    StopOp,
    UploadOp,
    WaitOp,
)
from applicant.core.rules.plan import (
    MAX_OPS_PER_PLAN,
    STOP_REASONS,
    validate_op_sequence,
    validate_plan,
)


class TestPlanEntities:
    """Plan/Op dataclass construction and identity."""

    def test_goto_op(self) -> None:
        op = GotoOp(url="https://example.com/apply")
        assert op.kind == OpKind.GOTO
        assert op.url == "https://example.com/apply"

    def test_fill_op(self) -> None:
        op = FillOp(ref="r1", attribute_id="first_name")
        assert op.kind == OpKind.FILL
        assert op.ref == "r1"
        assert op.attribute_id == "first_name"

    def test_select_op(self) -> None:
        op = SelectOp(ref="r2", attribute_id="country")
        assert op.kind == OpKind.SELECT

    def test_click_op(self) -> None:
        op = ClickOp(ref="r3")
        assert op.kind == OpKind.CLICK

    def test_upload_op(self) -> None:
        op = UploadOp(ref="r4", document_id="doc_resume_1")
        assert op.kind == OpKind.UPLOAD

    def test_stop_op(self) -> None:
        op = StopOp(reason="captcha")
        assert op.kind == OpKind.STOP
        assert op.reason == "captcha"

    def test_wait_op(self) -> None:
        op = WaitOp(for_="visible", timeout=5.0)
        assert op.kind == OpKind.WAIT
        assert op.for_ == "visible"
        assert op.timeout == 5.0

    def test_plan_construction(self) -> None:
        ops = (
            GotoOp(url="https://example.com/apply"),
            FillOp(ref="r1", attribute_id="first_name"),
            ClickOp(ref="r2"),
            StopOp(reason="final_submit"),
        )
        plan = Plan(ops=ops)
        assert len(plan) == 4
        assert plan[0].kind == OpKind.GOTO
        assert plan[-1].kind == OpKind.STOP

    def test_empty_plan(self) -> None:
        plan = Plan(ops=())
        assert len(plan) == 0
        assert list(plan) == []


class TestValidatePlan:
    """Pure-domain plan validation."""

    KNOWN_IDS = frozenset({"first_name", "last_name", "email", "phone", "country"})

    def test_valid_plan_passes(self) -> None:
        ops = (
            GotoOp(url="https://example.com/apply"),
            FillOp(ref="r1", attribute_id="first_name"),
            FillOp(ref="r2", attribute_id="last_name"),
            FillOp(ref="r3", attribute_id="email"),
        )
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert errors == []

    def test_empty_plan_fails(self) -> None:
        plan = Plan(ops=())
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("empty" in e for e in errors)

    def test_unknown_attribute_id(self) -> None:
        ops = (FillOp(ref="r1", attribute_id="nonexistent_attr"),)
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("unknown" in e.lower() for e in errors)

    def test_stop_reason_must_be_recognized(self) -> None:
        ops = (StopOp(reason="invalid_reason_x"),)
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("not a recognized" in e for e in errors)

    def test_all_valid_stop_reasons(self) -> None:
        for reason in STOP_REASONS:
            ops = (StopOp(reason=reason),)
            plan = Plan(ops=ops)
            # Alone, an empty known_ids is fine since stop doesn't reference them.
            errors = validate_plan(plan, frozenset())
            # Only errors should be about referencing attributes, not about stop reason.
            stop_errors = [e for e in errors if "stop" in e.lower()]
            assert stop_errors == [], f"Stop reason {reason!r} should be valid"

    def test_fill_requires_ref(self) -> None:
        ops = (FillOp(ref="", attribute_id="first_name"),)
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("ref" in e for e in errors)

    def test_goto_requires_url(self) -> None:
        ops = (GotoOp(url=""),)
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("url" in e for e in errors)

    def test_max_ops_exceeded(self) -> None:
        ops = tuple(ClickOp(ref=f"r{i}") for i in range(MAX_OPS_PER_PLAN + 1))
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("exceeds" in e for e in errors)

    def test_select_requires_attribute_id(self) -> None:
        ops = (SelectOp(ref="r1", attribute_id=""),)
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("attribute_id" in e for e in errors)

    def test_upload_requires_document_id(self) -> None:
        ops = (UploadOp(ref="r1", document_id=""),)
        plan = Plan(ops=ops)
        errors = validate_plan(plan, self.KNOWN_IDS)
        assert any("document_id" in e for e in errors)


class TestValidateOpSequence:
    """Plan sequencing rules."""

    def test_stop_must_be_last(self) -> None:
        ops = (
            GotoOp(url="https://example.com"),
            StopOp(reason="captcha"),
            FillOp(ref="r1", attribute_id="email"),
        )
        plan = Plan(ops=ops)
        errors = validate_op_sequence(plan)
        assert any("last" in e for e in errors)

    def test_stop_at_end_is_ok(self) -> None:
        ops = (
            GotoOp(url="https://example.com"),
            FillOp(ref="r1", attribute_id="email"),
            StopOp(reason="final_submit"),
        )
        plan = Plan(ops=ops)
        errors = validate_op_sequence(plan)
        assert errors == []

    def test_no_stop_is_ok(self) -> None:
        ops = (
            GotoOp(url="https://example.com"),
            FillOp(ref="r1", attribute_id="email"),
        )
        plan = Plan(ops=ops)
        errors = validate_op_sequence(plan)
        assert errors == []
