"""Regression coverage for exhaustive-audit-pass-2 lens 12 (help &
self-explainability), finding #46, confined to
``static/js/applicantChat.js`` (the assistant chat modal's tappable starter
prompts).

Follows the convention of ``test_applicant_mind_help_lens12.py`` /
``test_applicant_campaign_settings_help_lens12.py``: every fact is read from
the actual static file content via ``pathlib`` + regex — no browser, no DOM,
no real socket. The assertion below was hand-verified to go red when the
underlying fix is reverted (backup the file to /tmp, revert the change,
rerun, see the assertion fail, restore from the backup) per the project's
revert-verify convention.

Finding covered (see
``docs/design/audits/exhaustive2/12_help_selfexplain.md``, item #46):
"The assistant's starter chips include no help-shaped prompt" — the tappable
``_STARTER_PROMPTS`` set offered only task-shaped chips ("Tell me what
you're looking for", "What have you found so far?", "Change what you look
for") — nothing invited a new user to ask "How does this all work?", even
though the assistant now has product knowledge to answer that. This adds a
help/orientation starter prompt to the set so the chat becomes a
discoverable help channel with a single tap.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CHAT_JS = JS_DIR / "applicantChat.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _starter_prompts_block() -> str:
    js = _read(CHAT_JS)
    m = re.search(
        r"const _STARTER_PROMPTS\s*=\s*\[(.*?)\];",
        js,
        re.DOTALL,
    )
    assert m, "expected a _STARTER_PROMPTS array literal in applicantChat.js"
    return m.group(1)


def test_starter_prompts_include_a_help_shaped_prompt():
    """The starter-prompt set must include an orientation/help-shaped prompt
    (e.g. asking the assistant to explain how the product works), not just
    task-shaped chips."""
    block = _starter_prompts_block()
    assert re.search(r"how (does|this)[^'\"]*work", block, re.IGNORECASE), (
        "expected a help/orientation starter prompt (asking how the product "
        "works) in _STARTER_PROMPTS"
    )


def test_existing_task_shaped_starter_prompts_are_preserved():
    """The pre-existing task-shaped chips must still be present — this fix
    only adds a chip, it doesn't replace any."""
    block = _starter_prompts_block()
    assert "Tell me what you're looking for" in block
    assert "What have you found so far?" in block
    assert "Change what you look for" in block


def test_new_starter_prompt_matches_existing_format():
    """The new prompt must be a plain single-quoted string literal in the
    same array, matching the existing entries' quoting/format (no markup, no
    trailing period the others don't have, first-person/plain-language
    voice)."""
    block = _starter_prompts_block()
    entries = [
        line.strip().rstrip(",").strip()
        for line in block.strip().splitlines()
        if line.strip()
    ]
    assert len(entries) == 4, f"expected 4 starter prompts, found: {entries!r}"
    for entry in entries:
        assert entry[0] in "'\"", f"expected a quoted string literal, got: {entry!r}"
        assert entry[0] == entry[-1], f"unterminated string literal: {entry!r}"
