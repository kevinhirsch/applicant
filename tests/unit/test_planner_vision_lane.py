"""Hermetic tests for the #305 VISION lane (screenshot → multimodal planner prompt).

Skyvern-parity gap #1: the planner can ground its typed ops against a rendered
screenshot in addition to the semantic DOM. These tests prove:

* The planner attaches the screenshot as an image ONLY when the observation carries
  one; with no screenshot the message is text-only (byte-identical to before).
* The LLM wire serialization turns image parts into the OpenAI multipart ``content``
  array (and Ollama's native ``images`` list), and is byte-identical without images.
* Vision only IMPROVES grounding: whatever the vision-augmented planner emits still
  passes the plan validator — it fills by ``attribute_id`` via the DSL, cannot inject
  a raw literal, and cannot emit a submit / account-create op that crosses the
  stop-boundary (the validator refuses anything but a recognized StopOp reason).
* Screenshot capture in PrefillService is fully defensive: a fake browser returning
  fixed bytes flows through to the observation, and a browser with no capture / a
  ``None`` result degrades to the text-only prompt.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from applicant.adapters.planner.llm_planner import LLMPlanner
from applicant.core.entities.plan import FillOp, Plan, SelectOp, StopOp
from applicant.core.rules.plan import validate_plan
from applicant.ports.driven.llm import ChatMessage, LLMResult
from applicant.ports.driving.planner import PlannerInput, PlannerObservation

# A tiny valid-ish base64 PNG payload (content is irrelevant to these tests).
_FAKE_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-fake-bytes").decode("ascii")

# A vision-augmented plan the model might emit once it has seen the screenshot: it
# grounds the canvas/visual fields but still fills BY ATTRIBUTE_ID via the DSL.
_VISION_PLAN_JSON = (
    '[{"kind": "find", "ref": "r1", "role": "input", "name": "First name"},'
    ' {"kind": "fill", "ref": "r1", "attribute_id": "first_name"},'
    ' {"kind": "select", "ref": "r2", "attribute_id": "country"},'
    ' {"kind": "stop", "reason": "final_submit"}]'
)


class _CapturingLLM:
    """Fake LLMPort that records the messages it was handed and returns fixed text."""

    def __init__(self, text: str = "[]") -> None:
        self._text = text
        self.captured: list[ChatMessage] = []

    def complete(self, messages, *, start_tier=1, json_schema=None, max_tokens=None):
        self.captured = list(messages)
        return LLMResult(text=self._text, tier=start_tier, model="fake")

    def is_configured(self) -> bool:
        return True

    def list_models(self):
        return ["fake"]


# ── Multimodal prompt construction ──────────────────────────────────────────


class TestMultimodalPromptBuilt:
    def test_screenshot_present_attaches_image(self):
        """A screenshot on the observation ⇒ the user message carries the image."""
        llm = _CapturingLLM(text=_VISION_PLAN_JSON)
        planner = LLMPlanner(llm=llm)
        obs = PlannerObservation(url="https://x.com/apply", html_summary="<form/>",
                                 screenshot=_FAKE_PNG)
        planner.plan(PlannerInput(goal="fill form", observation=obs,
                                  facts={"first_name": "first_name", "country": "country"}))
        assert len(llm.captured) == 1
        msg = llm.captured[0]
        assert msg.images == (_FAKE_PNG,)
        # The prompt tells the model a screenshot is attached (grounding hint).
        assert "SCREENSHOT" in msg.content

    def test_no_screenshot_is_text_only(self):
        """No screenshot ⇒ NO image parts and NO screenshot hint (byte-identical path)."""
        llm = _CapturingLLM(text="[]")
        planner = LLMPlanner(llm=llm)
        obs = PlannerObservation(url="https://x.com/apply", html_summary="<form/>")
        planner.plan(PlannerInput(goal="fill form", observation=obs))
        assert len(llm.captured) == 1
        msg = llm.captured[0]
        assert msg.images == ()
        assert "SCREENSHOT" not in msg.content

    def test_no_observation_is_text_only(self):
        """No observation at all ⇒ no images, no crash."""
        llm = _CapturingLLM(text="[]")
        planner = LLMPlanner(llm=llm)
        planner.plan(PlannerInput(goal="fill form"))
        assert llm.captured[0].images == ()


# ── LLM wire serialization (multimodal, and byte-identical without images) ──


class TestWireSerialization:
    def test_openai_content_multipart_with_image(self):
        from applicant.adapters.llm.openai_compatible import _raw_message, _wire_content

        m = ChatMessage(role="user", content="hello", images=(_FAKE_PNG,))
        content = _wire_content(m)
        assert isinstance(content, list)
        assert content[0] == {"type": "text", "text": "hello"}
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"] == f"data:image/png;base64,{_FAKE_PNG}"
        assert _raw_message(m) == {"role": "user", "content": content}

    def test_openai_content_plain_string_without_image(self):
        from applicant.adapters.llm.openai_compatible import _raw_message, _wire_content

        m = ChatMessage(role="user", content="hello")
        # Byte-identical to the historical ``{"role", "content"}`` dict.
        assert _wire_content(m) == "hello"
        assert _raw_message(m) == {"role": "user", "content": "hello"}

    def test_ollama_native_images_list(self):
        from applicant.adapters.llm.openai_compatible import _ollama_message

        m = ChatMessage(role="user", content="hi", images=(_FAKE_PNG,))
        out = _ollama_message(m)
        assert out == {"role": "user", "content": "hi", "images": [_FAKE_PNG]}
        # No images ⇒ no ``images`` key (byte-identical).
        assert _ollama_message(ChatMessage(role="user", content="hi")) == {
            "role": "user", "content": "hi",
        }


# ── Safety: the vision-augmented plan still passes the validator ────────────


class TestVisionPlanIsSafe:
    def test_vision_plan_passes_validator(self):
        """The plan the vision planner emits validates: fill/select by attribute_id."""
        llm = _CapturingLLM(text=_VISION_PLAN_JSON)
        planner = LLMPlanner(llm=llm)
        obs = PlannerObservation(url="https://x.com/apply", screenshot=_FAKE_PNG)
        plan = planner.plan(PlannerInput(goal="fill form", observation=obs))
        errors = validate_plan(plan, frozenset({"first_name", "country"}))
        assert errors == [], errors
        # Every fill/select carries an attribute_id — never a literal value.
        for op in plan:
            if isinstance(op, (FillOp, SelectOp)):
                assert op.attribute_id
                assert not hasattr(op, "value")

    def test_vision_cannot_emit_raw_literal(self):
        """FillOp has no literal-value field — a vision op can only name an attribute_id.

        Even if the model 'reads' a value off the screenshot, the DSL gives it nowhere
        to put a literal: fills resolve from the attribute cloud downstream.
        """
        assert "value" not in FillOp.__dataclass_fields__
        assert "value" not in SelectOp.__dataclass_fields__
        # A fill whose attribute_id is not in the cloud is rejected (can't smuggle text).
        plan = Plan(ops=(FillOp(ref="r1", attribute_id="Alice Smith typed from image"),))
        errors = validate_plan(plan, frozenset({"first_name"}))
        assert any("unknown attribute_id" in e for e in errors)

    def test_vision_cannot_cross_stop_boundary(self):
        """A vision op emitting an unrecognized stop reason (a submit) is refused."""
        # Only the recognized hand-off reasons are allowed; an invented 'submit' fails.
        plan = Plan(ops=(FillOp(ref="r1", attribute_id="first_name"),
                         StopOp(reason="submit_application_now")))
        errors = validate_plan(plan, frozenset({"first_name"}))
        assert any("not a recognized stop reason" in e for e in errors)
        # The recognized final_submit hand-off IS allowed (routes to human review).
        ok = Plan(ops=(FillOp(ref="r1", attribute_id="first_name"),
                       StopOp(reason="final_submit")))
        assert validate_plan(ok, frozenset({"first_name"})) == []


# ── PrefillService screenshot capture is defensive ─────────────────────────


@dataclass
class _BytesBrowser:
    """Fake browser exposing screenshot_bytes → fixed bytes (the vision capture)."""

    raw: bytes | None = b"pixels"

    def screenshot_bytes(self, aid):
        return self.raw


class _NoCaptureBrowser:
    """Fake browser with NO screenshot_bytes method (older adapter)."""


class TestPrefillScreenshotCapture:
    def _svc(self, browser):
        from applicant.adapters.detection.detection_monitor import DetectionMonitor
        from applicant.adapters.sandbox.local_sandbox import LocalSandbox
        from applicant.adapters.storage.in_memory import InMemoryStorage
        from applicant.application.services.prefill_service import PrefillService

        return PrefillService(
            storage=InMemoryStorage(),
            browser=browser,
            detection=DetectionMonitor(),
            sandbox=LocalSandbox(),
            credentials=None,
        )

    def test_bytes_captured_and_base64_encoded(self):
        svc = self._svc(_BytesBrowser(raw=b"pixels"))
        got = svc._capture_screenshot_b64("app-1")
        assert got == base64.b64encode(b"pixels").decode("ascii")

    def test_none_result_degrades_to_text_only(self):
        svc = self._svc(_BytesBrowser(raw=None))
        assert svc._capture_screenshot_b64("app-1") is None

    def test_missing_capability_degrades_to_text_only(self):
        svc = self._svc(_NoCaptureBrowser())
        assert svc._capture_screenshot_b64("app-1") is None
