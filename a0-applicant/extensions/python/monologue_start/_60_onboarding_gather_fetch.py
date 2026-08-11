"""redesign-conversational-onboarding.md §3.2.6 — fetch the next gather target.

Split fetch/render like `_11_tools_prompt.py`'s `TOOL_KWARGS_KEY` cache pattern:
fetch here (once per turn, `monologue_start` fires once per user turn/loop) and
render in `system_prompt/_20_onboarding_gather_prompt.py`, so a system-prompt
rebuild that happens more than once inside one turn's tool-call loop doesn't
re-hit the engine each time.

Mirrors `_50_engine_llm_sync.py`'s shape: best-effort, self-contained (loads the
sibling `api/onboarding.py` proxy by file path — see that extension's docstring
for why), never raises, never blocks the loop on a failure.

Only fetches once the first-run wizard has actually been shown (`oobe_shown`):
before that, the wizard modal is the active onboarding surface (§3.1's banner may
still be about to force it open) — asking about the same fields in chat at the
same time would be a confusing double-prompt.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from helpers.extension import Extension

#: `agent.set_data` key the system_prompt extension reads to render the block.
GATHER_TARGET_DATA_KEY = "_onboarding_gather_target"


def _load_onboarding_proxy():
    """Load the sibling ``api/onboarding.py`` module by file path (self-contained).

    See `extensions/python/banners/_10_onboarding_first_run.py`'s docstring for
    why this loads the file directly rather than importing a package path.
    """
    path = Path(__file__).resolve().parents[3] / "api" / "onboarding.py"
    spec = importlib.util.spec_from_file_location("_applicant_onboarding_proxy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load onboarding proxy from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OnboardingGatherFetch(Extension):
    async def execute(self, **kwargs):
        if not self.agent:
            return
        try:
            dispatch = _load_onboarding_proxy().dispatch

            state_result = dispatch({"action": "state"})
            if not state_result.get("ok"):
                return
            state = state_result.get("data") or {}
            if not state.get("oobe_shown"):
                return  # first-run wizard hasn't been shown yet — it owns the surface

            next_result = dispatch({"action": "next"})
            target = next_result.get("data") if next_result.get("ok") else None
            self.agent.set_data(GATHER_TARGET_DATA_KEY, target or None)
        except Exception:
            # Best-effort: an engine hiccup here must never break the assistant's turn.
            return
