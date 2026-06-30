"""Unit tests for Plan-as-Data core entities, validator, resolve_fill_values,
and the ReadOnlyScrapePlan constraint."""

from __future__ import annotations

import pytest

from applicant.core.entities.plan import (
    AssertOp,
    ClickOp,
    ExtractOp,
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
    ReadOnlyScrapePlan,
    resolve_fill_values,
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


class TestResolveFillValues:
    """resolve_fill_values maps fill/select ops to attribute cloud values."""

    def test_fill_ops_resolved_from_attribute_cloud(self) -> None:
        cloud = {"first_name": "Alice", "last_name": "Smith", "email": "alice@example.com"}
        ops = (
            GotoOp(url="https://example.com/apply"),
            FillOp(ref="r1", attribute_id="first_name"),
            FillOp(ref="r2", attribute_id="last_name"),
            FillOp(ref="r3", attribute_id="email"),
        )
        plan = Plan(ops=ops)
        resolved = resolve_fill_values(plan, cloud)
        assert resolved == {"r1": "Alice", "r2": "Smith", "r3": "alice@example.com"}

    def test_select_ops_resolved(self) -> None:
        cloud = {"country": "United States"}
        ops = (SelectOp(ref="r1", attribute_id="country"),)
        plan = Plan(ops=ops)
        resolved = resolve_fill_values(plan, cloud)
        assert resolved == {"r1": "United States"}

    def test_missing_attribute_skipped(self) -> None:
        """Attributes absent from the cloud are silently skipped (plan was pre-validated)."""
        cloud = {"email": "bob@example.com"}
        ops = (
            FillOp(ref="r1", attribute_id="phone"),  # not in cloud
            FillOp(ref="r2", attribute_id="email"),
        )
        plan = Plan(ops=ops)
        resolved = resolve_fill_values(plan, cloud)
        assert resolved == {"r2": "bob@example.com"}
        assert "r1" not in resolved

    def test_non_fill_ops_excluded(self) -> None:
        """GotoOp/ClickOp/StopOp are not fill-resolvable; they must not appear in output."""
        cloud = {"email": "c@c.com"}
        ops = (
            GotoOp(url="https://example.com"),
            FillOp(ref="r1", attribute_id="email"),
            ClickOp(ref="next-btn"),
            StopOp(reason="final_submit"),
        )
        plan = Plan(ops=ops)
        resolved = resolve_fill_values(plan, cloud)
        # Only the fill op should appear
        assert set(resolved.keys()) == {"r1"}

    def test_empty_cloud_yields_empty_mapping(self) -> None:
        ops = (FillOp(ref="r1", attribute_id="name"),)
        plan = Plan(ops=ops)
        resolved = resolve_fill_values(plan, {})
        assert resolved == {}

    def test_values_come_from_cloud_not_plan(self) -> None:
        """Value in resolved MUST come from attribute_cloud, not from any plan field."""
        cloud = {"name": "Dave Stored"}
        ops = (FillOp(ref="r1", attribute_id="name"),)
        plan = Plan(ops=ops)
        resolved = resolve_fill_values(plan, cloud)
        assert resolved["r1"] == "Dave Stored"


class TestReadOnlyScrapePlan:
    """ReadOnlyScrapePlan enforces the constraint that only extract/assert/wait
    ops are allowed in the scrape lane."""

    def test_valid_scrape_plan_accepted(self) -> None:
        ops = (
            ExtractOp(ref="r1", shape="text"),
            AssertOp(ref="r2", predicate="visible"),
            WaitOp(for_="visible", timeout=5.0),
        )
        plan = Plan(ops=ops)
        ro = ReadOnlyScrapePlan(plan=plan)
        assert len(ro.ops()) == 3

    def test_fill_op_rejected(self) -> None:
        ops = (
            ExtractOp(ref="r1", shape="text"),
            FillOp(ref="r2", attribute_id="email"),
        )
        plan = Plan(ops=ops)
        with pytest.raises(ValueError, match="mutating op"):
            ReadOnlyScrapePlan(plan=plan)

    def test_goto_op_rejected(self) -> None:
        ops = (GotoOp(url="https://example.com"),)
        plan = Plan(ops=ops)
        with pytest.raises(ValueError, match="mutating op"):
            ReadOnlyScrapePlan(plan=plan)

    def test_click_op_rejected(self) -> None:
        ops = (ClickOp(ref="btn"),)
        plan = Plan(ops=ops)
        with pytest.raises(ValueError, match="mutating op"):
            ReadOnlyScrapePlan(plan=plan)

    def test_select_op_rejected(self) -> None:
        ops = (SelectOp(ref="r1", attribute_id="country"),)
        plan = Plan(ops=ops)
        with pytest.raises(ValueError, match="mutating op"):
            ReadOnlyScrapePlan(plan=plan)

    def test_upload_op_rejected(self) -> None:
        ops = (UploadOp(ref="r1", document_id="doc1"),)
        plan = Plan(ops=ops)
        with pytest.raises(ValueError, match="mutating op"):
            ReadOnlyScrapePlan(plan=plan)

    def test_stop_op_rejected(self) -> None:
        ops = (StopOp(reason="final_submit"),)
        plan = Plan(ops=ops)
        with pytest.raises(ValueError, match="mutating op"):
            ReadOnlyScrapePlan(plan=plan)

    def test_empty_extract_plan_accepted(self) -> None:
        ops = (ExtractOp(ref=None, shape="full_page"),)
        plan = Plan(ops=ops)
        ro = ReadOnlyScrapePlan(plan=plan)
        assert ro.ops() == plan.ops

    def test_error_message_names_bad_ops(self) -> None:
        ops = (FillOp(ref="r1", attribute_id="x"), GotoOp(url="https://x.com"))
        plan = Plan(ops=ops)
        with pytest.raises(ValueError) as exc_info:
            ReadOnlyScrapePlan(plan=plan)
        msg = str(exc_info.value)
        assert "op[0]=fill" in msg
        assert "op[1]=goto" in msg
