"""redesign-conversational-onboarding.md §3.2.5 — OnboardingNext agent tool.

Read-only lookup: what's the next required-onboarding-section gap the user
hasn't answered or explicitly declined? The agent calls this when it wants to
check what's still open — e.g. at the start of a session, or when the user asks
"what do you still need from me?". Never writes anything (see OnboardingAnswer
for the write path).

Self-contained: loads the sibling `api/onboarding.py` proxy by file path rather
than importing a `plugins.applicant.api...` package path — see
`extensions/python/banners/_10_onboarding_first_run.py`'s docstring for why
plugin sibling-imports are unreliable here.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.tool import Response, Tool


def _load_onboarding_proxy():
    path = Path(__file__).resolve().parents[1] / "api" / "onboarding.py"
    spec = importlib.util.spec_from_file_location("_applicant_onboarding_proxy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load onboarding proxy from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OnboardingNext(Tool):
    async def execute(self, **kwargs):
        try:
            dispatch = _load_onboarding_proxy().dispatch
            result = dispatch({"action": "next"})
        except Exception as exc:
            return Response(
                message=f"Couldn't reach the onboarding engine ({type(exc).__name__}: {exc}).",
                break_loop=False,
            )

        if not result.get("ok"):
            return Response(
                message="Couldn't reach the onboarding engine — is a model connected and a campaign started?",
                break_loop=False,
            )

        target = result.get("data")
        if not target:
            return Response(
                message=(
                    "Nothing outstanding — every required onboarding section is "
                    "either filled in or was explicitly declined."
                ),
                break_loop=False,
            )

        title = target.get("title") or target.get("section") or "unknown section"
        hint = target.get("hint") or ""
        lines = [f"Next up: {title}" + (f" — {hint}" if hint else "")]
        fields = target.get("missing_fields") or []
        if fields:
            lines.append("Still blank:")
            for f in fields[:3]:
                label = f.get("label") or f.get("key") or ""
                field_hint = f" ({f['hint']})" if f.get("hint") else ""
                lines.append(f"- {label}{field_hint}")
        return Response(message="\n".join(lines), break_loop=False)
