"""Unit tests for the plan-as-data typed-DSL planner (Issue #305)."""

from __future__ import annotations

import pytest

from applicant.core.rules.plan import (
    PREFILL_OPS,
    ReadOnlyScrapePlan,
    Plan,
    PlanOp,
    PlanOpType,
    PlanValidationResult,
    SCRAPE_OPS,
    validate_plan,
    resolve_fill_values,
)


class TestPlanOpValidation:
    """A typed plan is validated before any browser action runs."""

    def test_valid_fill_op(self):
        """A FILL op with attribute_id and selector passes validation."""
        op = PlanOp(
            type=PlanOpType.FILL,
            attribute_id="first_name",
            selector="#first_name_input",
        )
        validated = op.validated()
        assert validated.type == PlanOpType.FILL
        assert validated.attribute_id == "first_name"

    def test_valid_select_option_op(self):
        """A SELECT_OPTION op with attribute_id and selector passes."""
        op = PlanOp(
            type=PlanOpType.SELECT_OPTION,
            attribute_id="country",
            selector="select[name=country]",
        )
        validated = op.validated()
        assert validated.type == PlanOpType.SELECT_OPTION

    def test_valid_click_op(self):
        """A CLICK op with only a selector passes."""
        op = PlanOp(type=PlanOpType.CLICK, selector="button.next")
        validated = op.validated()
        assert validated.type == PlanOpType.CLICK

    def test_fill_op_missing_attribute_id_raises(self):
        """A FILL op without attribute_id raises ValueError."""
        op = PlanOp(type=PlanOpType.FILL, selector="#input")
        with pytest.raises(ValueError, match="attribute_id"):
            op.validated()

    def test_fill_op_missing_selector_raises(self):
        """A FILL op without selector raises ValueError."""
        op = PlanOp(type=PlanOpType.FILL, attribute_id="name")
        with pytest.raises(ValueError, match="selector"):
            op.validated()

    def test_final_submit_must_not_have_selector(self):
        """A FINAL_SUBMIT op must NOT carry a selector."""
        op = PlanOp(type=PlanOpType.FINAL_SUBMIT, selector="#submit")
        with pytest.raises(ValueError, match="must NOT carry a selector"):
            op.validated()

    def test_account_create_must_not_have_selector(self):
        """An ACCOUNT_CREATE op must NOT carry a selector."""
        op = PlanOp(type=PlanOpType.ACCOUNT_CREATE, selector="#create")
        with pytest.raises(ValueError, match="must NOT carry a selector"):
            op.validated()

    def test_extract_op_requires_selector(self):
        """An EXTRACT op requires a selector."""
        op = PlanOp(type=PlanOpType.EXTRACT)
        with pytest.raises(ValueError, match="selector"):
            op.validated()


class TestPlanValidation:
    """Only typed operations from the allowed op-set are accepted."""

    def test_valid_prefill_plan_passes(self):
        """A plan with only allowed pre-fill ops passes validation."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="first_name",
                    selector="#first_name",
                ),
                PlanOp(
                    type=PlanOpType.SELECT_OPTION,
                    attribute_id="country",
                    selector="select[name=country]",
                ),
                PlanOp(type=PlanOpType.ADVANCE),
            )
        )
        result = validate_plan(plan)
        assert result.valid
        assert len(result.errors) == 0

    def test_disallowed_op_is_rejected(self):
        """A plan with a scrape-only op in a prefill plan is rejected."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                ),
                PlanOp(type=PlanOpType.EXTRACT, selector=".data"),
            )
        )
        result = validate_plan(plan)
        assert not result.valid
        assert any("not in the allowed op-set" in e for e in result.errors)

    def test_final_submit_rejected_in_prefill_plan(self):
        """FINAL_SUBMIT is rejected in a default (prefill) plan."""
        plan = Plan(
            ops=(
                PlanOp(type=PlanOpType.FINAL_SUBMIT),
            )
        )
        result = validate_plan(plan)
        assert not result.valid
        assert any("final_submit" in e for e in result.errors)

    def test_empty_plan_is_valid(self):
        """An empty plan (no ops) passes validation."""
        plan = Plan(ops=())
        result = validate_plan(plan)
        assert result.valid

    def test_fill_op_with_pre_resolved_value_rejected(self):
        """A FILL op with a pre-resolved value is rejected (values must come from the cloud)."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                    value="John",
                ),
            )
        )
        result = validate_plan(plan)
        assert not result.valid
        assert any("pre-resolved" in e for e in result.errors)

    def test_whitespace_attribute_id_rejected(self):
        """An attribute_id that is only whitespace is rejected."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="   ",
                    selector="#input",
                ),
            )
        )
        result = validate_plan(plan)
        assert not result.valid

    def test_custom_allowed_ops_used(self):
        """Custom allowed_ops are used when provided."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                ),
            )
        )
        # Only allow EXTRACT — FILL should be rejected
        result = validate_plan(plan, allowed_ops=SCRAPE_OPS)
        assert not result.valid


class TestResolveFillValues:
    """Fill operations resolve values by attribute id so the fabrication guard holds."""

    def test_resolve_fill_value_from_cloud(self):
        """A FILL op's value is resolved from the attribute cloud."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="first_name",
                    selector="#first_name",
                ),
            )
        )
        cloud = {"first_name": "Jane"}
        result = resolve_fill_values(plan, cloud)
        assert result.valid
        assert len(result.resolved_ops) == 1
        assert result.resolved_ops[0].value == "Jane"

    def test_resolve_select_option_from_cloud(self):
        """A SELECT_OPTION op's value is resolved from the attribute cloud."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.SELECT_OPTION,
                    attribute_id="country",
                    selector="select[name=country]",
                ),
            )
        )
        cloud = {"country": "United States"}
        result = resolve_fill_values(plan, cloud)
        assert result.valid
        assert result.resolved_ops[0].value == "United States"

    def test_unknown_attribute_id_rejected(self):
        """An op referencing an unknown attribute id is rejected."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="nonexistent",
                    selector="#input",
                ),
            )
        )
        cloud = {"known_attr": "value"}
        result = resolve_fill_values(plan, cloud)
        assert not result.valid
        assert any("not found" in e for e in result.errors)

    def test_non_fill_ops_pass_through(self):
        """Non-fill ops (CLICK, ADVANCE) pass through unchanged."""
        plan = Plan(
            ops=(
                PlanOp(type=PlanOpType.CLICK, selector="button.next"),
                PlanOp(type=PlanOpType.ADVANCE),
            )
        )
        cloud: dict[str, str] = {}
        result = resolve_fill_values(plan, cloud)
        assert result.valid
        assert len(result.resolved_ops) == 2
        assert result.resolved_ops[0].type == PlanOpType.CLICK
        assert result.resolved_ops[1].type == PlanOpType.ADVANCE

    def test_mixed_plan_resolves_only_fill_ops(self):
        """Only fill/select/file ops are resolved; others pass through."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                ),
                PlanOp(type=PlanOpType.CLICK, selector="button.next"),
                PlanOp(
                    type=PlanOpType.SELECT_OPTION,
                    attribute_id="country",
                    selector="select[name=country]",
                ),
            )
        )
        cloud = {"name": "Jane", "country": "Canada"}
        result = resolve_fill_values(plan, cloud)
        assert result.valid
        assert result.resolved_ops[0].value == "Jane"
        assert result.resolved_ops[1].type == PlanOpType.CLICK
        assert result.resolved_ops[2].value == "Canada"

    def test_every_filled_value_traces_to_stored_attribute(self):
        """Every filled value traces back to a stored attribute, never LLM free-text."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="full_name",
                    selector="#name",
                ),
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="email",
                    selector="#email",
                ),
                PlanOp(
                    type=PlanOpType.SELECT_OPTION,
                    attribute_id="pronouns",
                    selector="select[name=pronouns]",
                ),
            )
        )
        cloud = {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "pronouns": "She/Her",
        }
        result = resolve_fill_values(plan, cloud)
        assert result.valid
        for op in result.resolved_ops:
            assert op.value is not None
            # Every value is exactly what was stored
            assert op.value == cloud[op.attribute_id]


class TestStopBoundary:
    """Consequential operations stay behind the stop-boundary."""

    def test_plan_without_consequential_ops_passes_boundary(self):
        """A plan with only pre-fill ops does not cross the stop-boundary."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                ),
            )
        )
        # validate with default prefill ops — any op not in PREFILL_OPS would fail
        result = validate_plan(plan, allowed_ops=PREFILL_OPS)
        assert result.valid

    def test_final_submit_plan_is_not_in_prefill_ops(self):
        """FINAL_SUBMIT is not in the prefill op-set."""
        assert PlanOpType.FINAL_SUBMIT not in PREFILL_OPS

    def test_account_create_plan_is_not_in_prefill_ops(self):
        """ACCOUNT_CREATE is not in the prefill op-set."""
        assert PlanOpType.ACCOUNT_CREATE not in PREFILL_OPS


class TestReadOnlyScrapePlan:
    """The discovery/scrape lane is read-only and network-less."""

    def test_read_only_scrape_plan_with_extract_ops(self):
        """A ReadOnlyScrapePlan with EXTRACT ops is valid."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.EXTRACT,
                    selector=".job-title",
                ),
                PlanOp(
                    type=PlanOpType.EXTRACT,
                    selector=".company-name",
                ),
            )
        )
        scrape = ReadOnlyScrapePlan(plan=plan)
        assert len(scrape.ops) == 2
        assert all(op.type == PlanOpType.EXTRACT for op in scrape.ops)

    def test_read_only_scrape_rejects_non_extract_ops(self):
        """A ReadOnlyScrapePlan with non-EXTRACT ops is rejected."""
        plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                ),
            )
        )
        with pytest.raises(ValueError, match="only allows EXTRACT ops"):
            ReadOnlyScrapePlan(plan=plan)

    def test_read_only_scrape_empty_plan(self):
        """An empty ReadOnlyScrapePlan is valid (no data to extract)."""
        plan = Plan(ops=())
        scrape = ReadOnlyScrapePlan(plan=plan)
        assert len(scrape.ops) == 0

    def test_read_only_scrape_cannot_mutate(self):
        """ReadOnlyScrapePlan guarantees no mutation ops exist."""
        plan = Plan(
            ops=(
                PlanOp(type=PlanOpType.CLICK, selector="button"),
            )
        )
        with pytest.raises(ValueError, match="only allows EXTRACT ops"):
            ReadOnlyScrapePlan(plan=plan)


class TestPlannerPortContract:
    """A unified PlannerPort drives all surfaces."""

    def test_same_dsl_contract_across_surfaces(self):
        """The same Plan type is used for all surfaces."""
        # Pre-fill plan
        prefill_plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.FILL,
                    attribute_id="name",
                    selector="#name",
                ),
            )
        )
        assert isinstance(prefill_plan, Plan)

        # Scrape plan
        scrape_plan = Plan(
            ops=(
                PlanOp(
                    type=PlanOpType.EXTRACT,
                    selector=".data",
                ),
            )
        )
        assert isinstance(scrape_plan, Plan)

        # ReadOnlyScrapePlan wraps a Plan
        read_only = ReadOnlyScrapePlan(plan=scrape_plan)
        assert isinstance(read_only.plan, Plan)

    def test_plan_op_type_enum_values(self):
        """All PlanOpType enum values are valid strings."""
        assert PlanOpType.FILL.value == "fill"
        assert PlanOpType.SELECT_OPTION.value == "select_option"
        assert PlanOpType.FINAL_SUBMIT.value == "final_submit"
        assert PlanOpType.EXTRACT.value == "extract"
        assert PlanOpType.ADVANCE.value == "advance"
        assert PlanOpType.CLICK.value == "click"
        assert PlanOpType.UPLOAD_FILE.value == "upload_file"
        assert PlanOpType.ACCOUNT_CREATE.value == "account_create"
        assert PlanOpType.ACCOUNT_LOGIN.value == "account_login"

    def test_prefill_ops_set(self):
        """PREFILL_OPS contains only pre-fill-safe operations."""
        assert PlanOpType.FILL in PREFILL_OPS
        assert PlanOpType.SELECT_OPTION in PREFILL_OPS
        assert PlanOpType.UPLOAD_FILE in PREFILL_OPS
        assert PlanOpType.CLICK in PREFILL_OPS
        assert PlanOpType.ADVANCE in PREFILL_OPS
        assert PlanOpType.ACCOUNT_LOGIN in PREFILL_OPS
        assert PlanOpType.FINAL_SUBMIT not in PREFILL_OPS
        assert PlanOpType.ACCOUNT_CREATE not in PREFILL_OPS
        assert PlanOpType.EXTRACT not in PREFILL_OPS

    def test_scrape_ops_set(self):
        """SCRAPE_OPS contains only EXTRACT."""
        assert PlanOpType.EXTRACT in SCRAPE_OPS
        assert len(SCRAPE_OPS) == 1
