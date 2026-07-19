"""Unit tests for LLMPlanner — default PlannerPort adapter."""

from __future__ import annotations

import json

import pytest

from applicant.adapters.planner.llm_planner import LLMPlanner, PlanParseError
from applicant.core.entities.plan import (
    AssertOp,
    ClickOp,
    ExtractOp,
    FillOp,
    FindOp,
    GotoOp,
    OpKind,
    Plan,
    SelectOp,
    StopOp,
    UploadOp,
    WaitOp,
)
from applicant.ports.driven.llm import ChatMessage, LLMResult
from applicant.ports.driving.planner import PlannerInput, PlannerObservation


class _FakeLLM:
    """Minimal fake LLMPort for unit tests.

    Matches the ``complete`` protocol signature used by LLMPlanner.plan().
    """

    def __init__(self, result_text: str = "") -> None:
        self._result_text = result_text
        self._raise_on_call: Exception | None = None

    def complete(
        self,
        messages: list[ChatMessage],
        *,
        start_tier: int = 1,
        json_schema: dict | None = None,
        max_tokens: int | None = None,
    ) -> LLMResult:
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return LLMResult(text=self._result_text, tier=start_tier, model="fake")

    @classmethod
    def that_returns(cls, text: str) -> _FakeLLM:
        return cls(result_text=text)

    @classmethod
    def that_raises(cls, exc: Exception) -> _FakeLLM:
        obj = cls()
        obj._raise_on_call = exc
        return obj


# Parallel-safety fixture: llm_planner has no module-level lru_cache, but
# this pattern ensures future caching additions won't leak across tests.
@pytest.fixture(autouse=True)
def _no_state_leak():
    yield


class TestPlanParseError:
    """PlanParseError is a plain Exception subclass."""

    def test_is_exception(self) -> None:
        assert issubclass(PlanParseError, Exception)

    def test_raise_and_catch(self) -> None:
        with pytest.raises(PlanParseError, match="test error"):
            raise PlanParseError("test error")


class TestLLMPlannerConstructor:
    """LLMPlanner stores its dependencies and max_ops."""

    def test_stores_llm(self) -> None:
        llm = _FakeLLM()
        planner = LLMPlanner(llm)
        assert planner._llm is llm

    def test_default_max_ops(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        assert planner._max_ops == 40

    def test_custom_max_ops(self) -> None:
        planner = LLMPlanner(_FakeLLM(), max_ops=10)
        assert planner._max_ops == 10


class TestLLMPlannerPlan:
    """LLMPlanner.plan() maps LLM output to a validated Plan."""

    @staticmethod
    def _input(**overrides) -> PlannerInput:
        kwargs = {"goal": "fill the form"}
        kwargs.update(overrides)
        return PlannerInput(**kwargs)

    def test_returns_plan_with_parsed_ops(self) -> None:
        llm = _FakeLLM.that_returns(
            '[{"kind": "goto", "url": "https://example.com"}, {"kind": "fill", "ref": "r1", "attribute_id": "name"}]'
        )
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 2
        assert plan[0].kind == OpKind.GOTO
        assert plan[0].url == "https://example.com"
        assert plan[1].kind == OpKind.FILL

    def test_empty_plan_on_empty_llm_output(self) -> None:
        llm = _FakeLLM.that_returns("")
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 0

    def test_empty_plan_on_whitespace_output(self) -> None:
        llm = _FakeLLM.that_returns("   \n  \t  ")
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 0

    def test_empty_plan_on_llm_exception(self) -> None:
        llm = _FakeLLM.that_raises(RuntimeError("LLM down"))
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 0

    def test_empty_plan_on_invalid_json(self) -> None:
        llm = _FakeLLM.that_returns("not json")
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 0

    def test_empty_plan_on_non_array_json(self) -> None:
        llm = _FakeLLM.that_returns('{"a": 1}')
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 0

    def test_truncates_beyond_max_ops(self) -> None:
        ops = [{"kind": "wait"}] * 10
        llm = _FakeLLM.that_returns(json.dumps(ops))
        planner = LLMPlanner(llm, max_ops=3)
        plan = planner.plan(self._input())
        assert len(plan) == 3

    def test_strips_markdown_code_fence(self) -> None:
        llm = _FakeLLM.that_returns('```json\n[{"kind": "stop", "reason": "done"}]\n```')
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 1
        assert plan[0].kind == OpKind.STOP
        assert plan[0].reason == "done"

    def test_all_op_kinds_are_parsed(self) -> None:
        llm = _FakeLLM.that_returns(
            json.dumps([
                {"kind": "goto", "url": "https://example.com"},
                {"kind": "find", "ref": "r1", "role": "input", "name": "email", "near": "Email:"},
                {"kind": "fill", "ref": "r1", "attribute_id": "email"},
                {"kind": "select", "ref": "r2", "attribute_id": "country"},
                {"kind": "click", "ref": "r3"},
                {"kind": "upload", "ref": "r4", "document_id": "resume"},
                {"kind": "extract", "ref": "r5", "shape": "text"},
                {"kind": "assert", "ref": "r6", "predicate": "visible"},
                {"kind": "wait", "for": "visible", "timeout": 5.0},
                {"kind": "stop", "reason": "done"},
            ])
        )
        planner = LLMPlanner(llm)
        plan = planner.plan(self._input())
        assert len(plan) == 10
        assert isinstance(plan[0], GotoOp)
        assert isinstance(plan[1], FindOp)
        assert isinstance(plan[2], FillOp)
        assert isinstance(plan[3], SelectOp)
        assert isinstance(plan[4], ClickOp)
        assert isinstance(plan[5], UploadOp)
        assert isinstance(plan[6], ExtractOp)
        assert isinstance(plan[7], AssertOp)
        assert isinstance(plan[8], WaitOp)
        assert isinstance(plan[9], StopOp)


class TestLLMPlannerPlanMany:
    """plan_many creates one Plan per page observation."""

    def test_one_plan_per_page(self) -> None:
        llm = _FakeLLM.that_returns('[{"kind": "stop", "reason": "done"}]')
        planner = LLMPlanner(llm)
        pages = [
            PlannerObservation(url="https://example.com/p1"),
            PlannerObservation(url="https://example.com/p2"),
            PlannerObservation(url="https://example.com/p3"),
        ]
        plans = planner.plan_many("apply", pages, {"name": "first_name"})
        assert len(plans) == 3
        assert all(isinstance(p, Plan) for p in plans)

    def test_empty_pages_returns_empty_list(self) -> None:
        llm = _FakeLLM.that_returns('[{"kind": "stop", "reason": "done"}]')
        planner = LLMPlanner(llm)
        plans = planner.plan_many("apply", [], {})
        assert plans == []


class TestObservationImages:
    """_observation_images extracts the base64 screenshot from observation."""

    def test_no_screenshot_returns_empty_tuple(self) -> None:
        obs = PlannerObservation(url="https://example.com")
        inp = PlannerInput(goal="test", observation=obs)
        result = LLMPlanner._observation_images(inp)
        assert result == ()

    def test_with_screenshot_returns_tuple(self) -> None:
        obs = PlannerObservation(url="https://example.com", screenshot="base64data==")
        inp = PlannerInput(goal="test", observation=obs)
        result = LLMPlanner._observation_images(inp)
        assert result == ("base64data==",)

    def test_none_observation_returns_empty_tuple(self) -> None:
        inp = PlannerInput(goal="test", observation=None)
        result = LLMPlanner._observation_images(inp)
        assert result == ()


class TestBuildPrompt:
    """_build_prompt constructs the prompt with all context sections."""

    @staticmethod
    def _planner(**overrides) -> tuple[LLMPlanner, PlannerInput]:
        planner = LLMPlanner(_FakeLLM())
        defaults = {
            "goal": "apply to acme",
            "observation": None,
            "facts": None,
            "constraints": None,
        }
        defaults.update(overrides)
        return planner, PlannerInput(**defaults)

    def test_includes_goal(self) -> None:
        planner, inp = self._planner(goal="apply to acme")
        prompt = planner._build_prompt(inp)
        assert "apply to acme" in prompt

    def test_includes_dsl_schema(self) -> None:
        planner, inp = self._planner()
        prompt = planner._build_prompt(inp)
        assert "AVAILABLE OPERATIONS" in prompt

    def test_includes_url_and_dom_when_observation(self) -> None:
        obs = PlannerObservation(
            url="https://example.com/apply",
            html_summary="<form>...</form>",
            snapshot_tokens=42,
        )
        planner, inp = self._planner(observation=obs)
        prompt = planner._build_prompt(inp)
        assert "https://example.com/apply" in prompt
        assert "<form>...</form>" in prompt
        assert "42" in prompt

    def test_includes_facts_manifest(self) -> None:
        planner, inp = self._planner(facts={"name": "First Name", "email": "Email Address"})
        prompt = planner._build_prompt(inp)
        assert "name: First Name" in prompt
        assert "email: Email Address" in prompt

    def test_includes_constraints(self) -> None:
        planner, inp = self._planner(constraints={"stop_on": "final_submit"})
        prompt = planner._build_prompt(inp)
        assert "CONSTRAINT stop_on: final_submit" in prompt

    def test_includes_prior_routine(self) -> None:
        planner, inp = self._planner(prior_routine="goto page1; fill name; click next")
        prompt = planner._build_prompt(inp)
        assert "goto page1" in prompt

    def test_includes_failure_reason(self) -> None:
        planner, inp = self._planner(failure_reason="field not found")
        prompt = planner._build_prompt(inp)
        assert "PREVIOUS ATTEMPT FAILED: field not found" in prompt

    def test_includes_reflection(self) -> None:
        planner, inp = self._planner(reflection="try a different locator for the broken step")
        prompt = planner._build_prompt(inp)
        assert "try a different locator" in prompt

    def test_includes_screenshot_instruction_when_screenshot_present(self) -> None:
        obs = PlannerObservation(url="https://example.com", screenshot="base64")
        planner, inp = self._planner(observation=obs)
        prompt = planner._build_prompt(inp)
        assert "SCREENSHOT of the rendered page" in prompt

    def test_omits_screenshot_instruction_when_screenshot_missing(self) -> None:
        obs = PlannerObservation(url="https://example.com")
        planner, inp = self._planner(observation=obs)
        prompt = planner._build_prompt(inp)
        assert "SCREENSHOT" not in prompt

    def test_includes_trailing_response_instruction(self) -> None:
        planner, inp = self._planner()
        prompt = planner._build_prompt(inp)
        assert "Respond with ONLY a JSON array" in prompt


class TestParseJsonPlan:
    """_parse_json_plan converts raw LLM text to a list of Op objects."""

    def test_valid_json_array(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        ops = planner._parse_json_plan('[{"kind": "stop", "reason": "done"}]')
        assert len(ops) == 1
        assert isinstance(ops[0], StopOp)

    def test_strips_markdown_fence(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        ops = planner._parse_json_plan('```\n[{"kind": "stop", "reason": "done"}]\n```')
        assert len(ops) == 1

    def test_strips_json_language_fence(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        ops = planner._parse_json_plan('```json\n[{"kind": "stop", "reason": "done"}]\n```')
        assert len(ops) == 1

    def test_raises_on_invalid_json(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        with pytest.raises(PlanParseError, match="invalid JSON"):
            planner._parse_json_plan("not json at all")

    def test_raises_on_non_array(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        with pytest.raises(PlanParseError, match="expected a JSON array"):
            planner._parse_json_plan('{"a": 1}')

    def test_skips_unknown_op_kind(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        ops = planner._parse_json_plan(
            '[{"kind": "unknown_operation"}, {"kind": "stop", "reason": "done"}]'
        )
        assert len(ops) == 1
        assert ops[0].kind == OpKind.STOP

    def test_empty_array_gives_empty_list(self) -> None:
        planner = LLMPlanner(_FakeLLM())
        ops = planner._parse_json_plan("[]")
        assert ops == []

    def test_truncates_beyond_max_ops(self) -> None:
        planner = LLMPlanner(_FakeLLM(), max_ops=2)
        ops = planner._parse_json_plan(
            json.dumps([{"kind": "wait"}, {"kind": "wait"}, {"kind": "wait"}, {"kind": "wait"}])
        )
        assert len(ops) == 2
