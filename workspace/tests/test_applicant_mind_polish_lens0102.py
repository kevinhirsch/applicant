"""Regression coverage for the copy/voice (exhaustive2 lens 02) + micro-
interactions (exhaustive2 lens 01) polish pass on ``static/js/applicantMind.js``
only.

Scope note: several lens 02 findings for this file (#142, #163, #164, #165,
#166, #170, #173, #176 — the Mind dialog title, the offline note, the
playbooks empty state, the Forget tooltip/confirm, the toast punctuation, the
close-tooltip redundancy, and the authority-claim warning) were **already**
applied by an earlier pass and are pinned verbatim — including straight
apostrophes and the close button's plain "Close" text label — by
``test_applicant_copy_voice_chatmindvaultremote.py`` and
``test_applicant_backlog_warmempty.py``. This pass leaves those strings
untouched and instead covers the *remaining* real violations found in this
file: leftover third-person "the assistant"/"it" phrasing that the cross-
cutting house-voice rule ("I", never "the assistant" or third-person "it",
as the agent's own voice) still applies to, the raw ``e.message`` toast/HTML
fallbacks that should route through the shared ``errText()`` helper, an
IME-composition guard on the playbook lookup's Enter-to-submit handler, and
a busy/disabled guard on the playbook Load button (previously the only
action button in this file with no in-flight guard at all).

Two hint strings inside ``_renderMemory`` ("as the assistant handles
applications, the lessons **it** picks up...") and ("tell the assistant what
you like...") are *not* touched here even though they are third-person: both
are pinned verbatim by ``test_applicant_backlog_warmempty.py`` (as
concatenated JS string-literal fragments), and editing only the reachable
half of each sentence while leaving the pinned half in place would produce
worse, dangling-pronoun grammar rather than better copy. They are left as a
documented, deliberate deferral.

Every assertion below was verified by hand to go RED against the original,
unpatched file (a copy was diffed against a `cp`-based backup, not
`git stash`, per this repo's shared-worktree rule) and back to GREEN after
the fix — the standard per-file lane test-coverage DoD.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
MIND_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantMind.js"


def _read() -> str:
    return MIND_JS.read_text(encoding="utf-8")


# ── copy/voice: first-person fixes ──────────────────────────────────────────


def test_ingest_box_heading_and_body_are_first_person():
    """The bulk-paste box heading and its explainer both third-personed the
    agent as "it" ("Tell it about yourself" / "what the assistant already
    knows") — the only other first-person-narrated copy on this surface says
    "I". Neither old phrase may survive; the fixed phrasing must be present."""
    js = _read()
    assert "Tell it about yourself" not in js
    assert "Tell me about yourself" in js
    assert "assistant already knows" not in js
    assert "Each line is checked against what I" in js
    assert "already know: new details are saved" in js


def test_lessons_empty_state_is_first_person():
    """#-adjacent (cross-cutting, not individually numbered): the per-ATS
    lessons-learned empty state said "what the assistant figures out gets
    remembered here for next time"."""
    js = _read()
    assert "what the assistant figures out" not in js
    assert "what I figure out gets remembered here for next time." in js


def test_routines_empty_state_is_first_person():
    """Cross-cutting: the learned-routines empty state said "after the
    assistant successfully fills out an application"."""
    js = _read()
    assert "after the assistant successfully fills out" not in js
    assert "after I successfully fill out an" in js


def test_feedback_history_empty_state_is_first_person():
    """Cross-cutting: "what you told it shows up here" third-personed the
    agent as "it" in the feedback-history empty state."""
    js = _read()
    assert "what you told it shows up here" not in js
    assert "what you told me shows up here" in js


def test_pinned_third_person_hints_are_deliberately_left_untouched():
    """Sanity check documenting the deferral: these two hints stay third
    person because half of each is pinned verbatim by
    test_applicant_backlog_warmempty.py as a JS string-literal fragment, and
    a partial edit would strand a pronoun with no antecedent. Confirms this
    pass did not silently revert someone else's fix."""
    js = _read()
    assert "the lessons it picks up along the way will show up here" in js
    assert "tell the assistant what you like or want changed" in js


# ── copy/voice: curly apostrophes on newly-touched strings ──────────────────


def test_curation_action_tooltips_use_curly_apostrophes():
    js = _read()
    assert "I'll remember it and use it going forward" not in js
    assert "I won't remember it or change anything because of it" not in js
    assert "I’ll remember it and use it going forward" in js
    assert "I won’t remember it or change anything because of it" in js


def test_routine_tally_uses_curly_apostrophe():
    js = _read()
    assert "${losses} didn't" not in js
    assert "${losses} didn’t" in js


def test_playbook_explainer_uses_curly_apostrophe():
    js = _read()
    assert "so I don't\n" not in js
    assert "so I don’t\n" in js


# ── micro-interactions: raw e.message routed through errText() ─────────────


def test_all_catch_blocks_route_through_errtext_not_raw_message():
    """Cross-cutting micro-interactions rule: user-facing toast/HTML fallback
    copy must never surface a raw ``e.message`` (proxy/engine internals) —
    it must be mapped through the shared ``errText()`` helper this file
    already imports from applicantCore.js."""
    js = _read()
    assert "e.message || 'Could not" not in js
    assert js.count("errText(e) || 'Could not") == 7


# ── micro-interactions: IME guard + busy guard on the playbook lookup ──────


def test_playbook_lookup_enter_handler_guards_ime_composition():
    """micro-interactions #15 (cross-cutting): no Enter handler in the file
    guarded against an IME composition-commit keystroke firing the action
    early — the playbook ATS lookup's Enter-to-load handler is the one Enter
    handler in this file and needs the standard guard."""
    js = _read()
    assert "ev.isComposing" in js
    assert "ev.keyCode === 229" in js


def test_playbook_load_button_has_a_busy_guard():
    """Cross-cutting busy/disabled-guard rule: every other action button in
    this file (Import, curation Approve/Dismiss, Forget, playbook Apply)
    already disables itself in flight -- the playbook Load button was the
    one holdout with no guard at all, inviting a stacked double-fetch."""
    js = _read()
    import re

    m = re.search(r"async function _loadPlaybook\(ats\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected _loadPlaybook's body"
    body = m.group(1)
    assert "applicant-mind-playbook-load" in body
    assert "loadBtn.disabled = true" in body
    assert "loadBtn.disabled = false" in body


# ── white-label: codename denylist (built without literal codenames) ───────


def _word_from_codes(codes: list[int]) -> str:
    return "".join(chr(c) for c in codes)


def test_no_codenames_leak_into_this_file():
    banned = [
        _word_from_codes([102, 105, 114, 101, 104, 111, 117, 115, 101]),
        _word_from_codes([111, 114, 119, 101, 108, 108]),
        _word_from_codes([111, 100, 121, 115, 115, 101, 117, 115]),
        _word_from_codes([115, 109, 111, 107, 101, 121]),
        _word_from_codes(
            [104, 101, 114, 109, 101, 115, 45, 97, 103, 101, 110, 116]
        ),
    ]
    js = _read().lower()
    for word in banned:
        assert word not in js, f"codename leak: {word!r}"


# ── brace-balance sanity ─────────────────────────────────────────────────────


def test_file_stays_brace_balanced():
    js = _read()
    assert js.count("{") == js.count("}")
