"""redesign-conversational-onboarding.md §3.2.5 — OnboardingAnswer agent tool.

Writes ONE user-stated answer into the onboarding intake — via the engine's
`save_field` (a read-merge-write that never clobbers sibling fields already
saved in that section) — or records an explicit decline (`omit=true`) so
`onboarding_next` / the proactive gather nudge never asks about that
field/section again.

Only ever write a value the user just typed themselves, in direct response to a
question about that exact field — never infer, paraphrase into a different
meaning, or guess a value the user didn't state. This mirrors the EEO section's
existing rule (core.rules.sensitive_fields — sensitive fields are never
AI-guessed) generalized to every field, matching the confirm=True first-party
trust posture the engine's onboarding bridges already assume. See
prompts/agent.system.tool.onboarding_answer.md for the full usage doc.

Self-contained: loads the sibling `api/onboarding.py` proxy by file path — see
`extensions/python/banners/_10_onboarding_first_run.py`'s docstring for why
plugin sibling-imports are unreliable here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from helpers.tool import Response, Tool


def _load_onboarding_proxy():
    path = Path(__file__).resolve().parents[1] / "api" / "onboarding.py"
    spec = importlib.util.spec_from_file_location("_applicant_onboarding_proxy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load onboarding proxy from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


class OnboardingAnswer(Tool):
    async def execute(
        self,
        section: str = "",
        field: str = "",
        value: str = "",
        omit: Any = False,
        **kwargs,
    ):
        section = (section or "").strip()
        field = (field or "").strip()
        omit = _truthy(omit)

        if not section:
            return Response(
                message="onboarding_answer needs a `section` (e.g. \"identity\", \"references\").",
                break_loop=False,
            )
        if not omit and (not field or value in (None, "")):
            return Response(
                message=(
                    "onboarding_answer needs both `field` and `value` for a real answer — "
                    "or pass `omit: true` to record that the user declined."
                ),
                break_loop=False,
            )

        try:
            dispatch = _load_onboarding_proxy().dispatch
            if omit:
                result = dispatch(
                    {"action": "omit", "section": section, "field": field or None}
                )
            else:
                result = dispatch(
                    {"action": "save_field", "section": section, "field": field, "value": value}
                )
        except Exception as exc:
            return Response(
                message=f"Couldn't reach the onboarding engine ({type(exc).__name__}: {exc}).",
                break_loop=False,
            )

        if not result.get("ok"):
            return Response(
                message=f"The engine rejected that ({result.get('error') or 'unknown error'}).",
                break_loop=False,
            )

        if omit:
            what = f"the {field} field" if field else "this whole section"
            detail = f"Got it — I won't ask about {what} in {section} again."
        else:
            detail = f"Saved your answer for {field} in {section}."

        message = self.agent.read_prompt("fw.onboarding_field_saved.md", detail=detail)
        return Response(message=message, break_loop=False)
