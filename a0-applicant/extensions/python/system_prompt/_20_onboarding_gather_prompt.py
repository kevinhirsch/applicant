"""redesign-conversational-onboarding.md §3.2.6 — render the gather nudge.

Mirrors `agent-zero/extensions/python/system_prompt/_14_project_prompt.py`'s
shape: reads data cached by the paired `monologue_start` fetch extension
(`monologue_start/_60_onboarding_gather_fetch.py`) and, if a target is cached,
appends a short block instructing the agent to ask about ONE of the missing
fields if it fits naturally — never more. Appends nothing when there's no
cached target (nothing outstanding, or the first-run wizard hasn't been shown
yet).
"""
from __future__ import annotations

from typing import Any

from agent import Agent, LoopData
from helpers.extension import Extension

#: Must match `monologue_start/_60_onboarding_gather_fetch.py`'s
#: GATHER_TARGET_DATA_KEY. Kept as a literal rather than cross-importing that
#: hook folder's module: extensions are loaded as bare top-level modules by
#: basename (`helpers/modules.py:import_module`), not as a package, so a
#: cross-hook-folder import is exactly the kind of sibling-import the sibling
#: `api/onboarding.py` proxy's docstring calls unreliable.
_GATHER_TARGET_DATA_KEY = "_onboarding_gather_target"

#: EEO needs gentler phrasing (never a bare demographic question) — the prompt
#: template's placeholder engine is plain `{{var}}` substitution with no
#: conditionals (helpers/files.py:replace_placeholders_text), so the EEO-only
#: note is built here in Python and interpolated as an (often empty) string.
_EEO_SECTION = "eeo"
_EEO_NOTE = (
    "\nThis section is voluntary EEO data (FR-ATTR-6): never ask a bare "
    '"what\'s your race/gender/veteran/disability status?" — frame it as '
    '"would you like to answer the voluntary EEO questions, or decline?" '
    "and never guess an answer the user didn't state."
)


class OnboardingGatherPrompt(Extension):
    async def execute(
        self,
        system_prompt: list = [],
        loop_data: LoopData = LoopData(),
        **kwargs: Any,
    ):
        if not self.agent:
            return
        target = self.agent.get_data(_GATHER_TARGET_DATA_KEY)
        if not target:
            return
        missing_fields = target.get("missing_fields") or []
        if not missing_fields:
            return

        fields_text = "\n".join(
            f"- {f.get('label') or f.get('key') or ''}"
            + (f" ({f['hint']})" if f.get("hint") else "")
            for f in missing_fields[:5]
        )
        eeo_note = _EEO_NOTE if target.get("section") == _EEO_SECTION else ""
        prompt = self.agent.read_prompt(
            "agent.system.onboarding_gather.md",
            section_title=target.get("title") or target.get("section") or "",
            section_hint=target.get("hint") or "",
            fields_text=fields_text,
            eeo_note=eeo_note,
        )
        system_prompt.append(prompt)
