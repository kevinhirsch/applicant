"""LLMPlanner — default adapter for the PlannerPort (plan-as-data).

Uses the existing L1/L2 tier ladder: the **L1** (cheap, coding-capable) model
emits the plan because planning is a structured, code-shaped task a cheap model
does well. **L2** (pro) is reserved for hard writing tasks (cover letters,
screening prose) — unchanged. Planning ≠ writing.

The prompt = role + the DSL schema + the semantic DOM snapshot + the
attribute-cloud manifest (ids + labels, never raw secrets) + constraints (the
stop-boundary, the closed op set). Structured output / JSON-schema mode ON so
the plan parses deterministically.
"""

from __future__ import annotations

import json
import logging

from applicant.core.entities.plan import (
    AssertOp,
    ClickOp,
    ExtractOp,
    FillOp,
    FindOp,
    GotoOp,
    Op,
    OpKind,
    Plan,
    SelectOp,
    StopOp,
    UploadOp,
    WaitOp,
)
from applicant.ports.driven.llm import ChatMessage
from applicant.ports.driving.planner import PlannerInput, PlannerObservation
from applicant.core.rules.prompt_injection import neutralize_untrusted_text

log = logging.getLogger(__name__)

#: Template that describes the DSL schema to the LLM.
_DSL_SCHEMA_DESCRIPTION = """
You are an autonomous form-filling planner. Your job is to emit a plan as a JSON
list of operations. Each operation is a JSON object with a "kind" field.

AVAILABLE OPERATIONS:
- {"kind": "goto", "url": "..."} -- Navigate to a URL.
- {"kind": "find", "ref": "r1", "role": "input", "name": "...", "near": "..."} -- Resolve stable element handle.
- {"kind": "fill", "ref": "r1", "attribute_id": "..."} -- Fill a field from the attribute cloud by id.
- {"kind": "select", "ref": "r1", "attribute_id": "..."} -- Pick a dropdown/radio from the attribute cloud by id.
- {"kind": "click", "ref": "r1"} -- Click an element.
- {"kind": "upload", "ref": "r1", "document_id": "..."} -- Upload a document by id.
- {"kind": "extract", "ref": "r1", "shape": "..."} -- Read-only structured extraction.
- {"kind": "assert", "ref": "r1", "predicate": "..."} -- Verify page state.
- {"kind": "wait", "for": "visible", "timeout": 10.0} -- Wait for condition.
- {"kind": "stop", "reason": "..."} -- Hand off to human.

SAFETY RULES (must follow):
- fill/select/upload reference ATTRIBUTE_IDS (never literal values).
- Never emit a click that would submit the application or create an account.
- For account_create, captcha, final_submit, email_verify, two_factor, or oauth, emit stop.
- Maximum 40 operations per plan.
"""


class PlanParseError(Exception):
    """Raised when the LLM output cannot be parsed as a valid plan."""


class LLMPlanner:
    """Default PlannerPort adapter using the configured LLM tier ladder."""

    def __init__(self, llm, max_ops: int = 40) -> None:
        self._llm = llm
        self._max_ops = max_ops

    def plan(self, input_: PlannerInput) -> Plan:
        """Emit a Plan from the given input using the L1 LLM.

        #305 vision lane: when the observation carries a base64 PNG ``screenshot``,
        the user message attaches it as an image so the model grounds its typed ops
        against the RENDERED page (canvas / image-map / purely visual forms). With no
        screenshot the message is text-only — byte-identical to before. Vision only
        improves GROUNDING: the plan still fills by ``attribute_id`` through the DSL,
        so an image can never inject a literal value or cross the stop-boundary.
        """
        prompt = self._build_prompt(input_)
        images = self._observation_images(input_)
        try:
            raw = self._llm.complete(
                [ChatMessage(role="user", content=prompt, images=images)],
                start_tier=1,
            )
        except Exception:
            log.warning("LLMPlanner: LLM call failed", exc_info=True)
            return Plan(ops=())

        text = (raw.text or "").strip()
        if not text:
            return Plan(ops=())

        try:
            ops = self._parse_json_plan(text)
        except PlanParseError:
            log.warning("LLMPlanner: failed to parse LLM output as plan")
            return Plan(ops=())

        return Plan(ops=tuple(ops))

    def plan_many(self, goal: str, pages: list[PlannerObservation], facts: dict[str, str]) -> list[Plan]:
        plans: list[Plan] = []
        for page in pages:
            inp = PlannerInput(goal=goal, observation=page, facts=facts)
            plans.append(self.plan(inp))
        return plans

    @staticmethod
    def _observation_images(input_: PlannerInput) -> tuple[str, ...]:
        """Base64 PNG image parts to attach to the planner message (#305 vision).

        Returns the observation's ``screenshot`` as a one-image tuple when present,
        else an empty tuple (text-only path, byte-identical to before).
        """
        obs = input_.observation
        shot = getattr(obs, "screenshot", None) if obs is not None else None
        return (shot,) if shot else ()

    def _build_prompt(self, input_: PlannerInput) -> str:
        parts = [_DSL_SCHEMA_DESCRIPTION]
        parts.append(f"\nGOAL: {neutralize_untrusted_text(input_.goal)}")
        if input_.observation:
            obs = input_.observation
            parts.append(f"\nCURRENT URL: {neutralize_untrusted_text(obs.url)}")
            parts.append(f"\nDOM SNAPSHOT ({obs.snapshot_tokens} tokens):\n{neutralize_untrusted_text(obs.html_summary)}")
            # #305 vision lane: tell the model a rendered screenshot is attached so it
            # grounds ops against the pixels (canvas / image-map / visual-only forms)
            # AND the text-DOM. The op set is unchanged — it still fills by attribute_id.
            if getattr(obs, "screenshot", None):
                parts.append(
                    "\nA SCREENSHOT of the rendered page is attached. Use it to LOCATE "
                    "and ground the fields (especially canvas / image / visual-only "
                    "controls the DOM snapshot misses), then emit the SAME typed ops "
                    "(fill/select by attribute_id). Never transcribe a value from the "
                    "image — values come only from the attribute manifest by id."
                )
        if input_.facts:
            facts_str = "; ".join(f"{k}: {v}" for k, v in input_.facts.items())
            parts.append(f"\nATTRIBUTE MANIFEST (id: label):\n{facts_str}")
        if input_.constraints:
            for k, v in input_.constraints.items():
                parts.append(f"\nCONSTRAINT {k}: {v}")
        # #306 AWM prior-injection: a routine that worked on this domain before is
        # offered to the planner as a prior (data only — op kinds + ids/locators,
        # never a literal value), so coverage grows itself across encounters.
        if input_.prior_routine:
            parts.append(
                "\nA ROUTINE THAT WORKED HERE BEFORE (use as a prior; re-ground "
                "the refs against the CURRENT DOM, keep the same fields/ids):\n"
                f"{input_.prior_routine}"
            )
        if input_.failure_reason:
            parts.append(f"\nPREVIOUS ATTEMPT FAILED: {input_.failure_reason}")
        # #306 Reflexion: a richer reflection (what broke + why) steers the re-plan
        # away from the failed approach (e.g. a broken selector) rather than dead-stopping.
        if input_.reflection:
            parts.append(
                "\nREFLECTION ON THE LAST FAILURE (avoid repeating it; try a different "
                f"locator/approach for the broken step):\n{input_.reflection}"
            )
        parts.append("\n\nRespond with ONLY a JSON array of operation objects. No explanation.")
        return "\n".join(parts)

    def _parse_json_plan(self, text: str) -> list[Op]:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.find("\n")
            if first_newline != -1:
                cleaned = cleaned[first_newline:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()
        try:
            raw_list = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise PlanParseError(f"invalid JSON: {exc}") from exc
        if not isinstance(raw_list, list):
            raise PlanParseError("expected a JSON array")
        ops: list[Op] = []
        for item in raw_list:
            kind = item.get("kind", "")
            if kind == OpKind.GOTO.value:
                ops.append(GotoOp(url=item.get("url", "")))
            elif kind == OpKind.FIND.value:
                ops.append(FindOp(ref=item.get("ref", ""), role=item.get("role", ""),
                                  name=item.get("name"), near=item.get("near")))
            elif kind == OpKind.FILL.value:
                ops.append(FillOp(ref=item.get("ref", ""), attribute_id=item.get("attribute_id", "")))
            elif kind == OpKind.SELECT.value:
                ops.append(SelectOp(ref=item.get("ref", ""), attribute_id=item.get("attribute_id", "")))
            elif kind == OpKind.CLICK.value:
                ops.append(ClickOp(ref=item.get("ref", "")))
            elif kind == OpKind.UPLOAD.value:
                ops.append(UploadOp(ref=item.get("ref", ""), document_id=item.get("document_id", "")))
            elif kind == OpKind.EXTRACT.value:
                ops.append(ExtractOp(ref=item.get("ref"), shape=item.get("shape", "")))
            elif kind == OpKind.ASSERT.value:
                ops.append(AssertOp(ref=item.get("ref", ""), predicate=item.get("predicate", "")))
            elif kind == OpKind.WAIT.value:
                ops.append(WaitOp(for_=item.get("for", "visible"), timeout=item.get("timeout", 10.0)))
            elif kind == OpKind.STOP.value:
                ops.append(StopOp(reason=item.get("reason", "")))
            else:
                log.warning("LLMPlanner: unknown op kind %r -- skipping", kind)
        if len(ops) > self._max_ops:
            ops = ops[: self._max_ops]
        return ops
