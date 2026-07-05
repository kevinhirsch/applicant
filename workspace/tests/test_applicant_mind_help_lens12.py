"""Regression coverage for exhaustive-audit-pass-2 lens 12 (help &
self-explainability), finding #11, confined to ``static/js/applicantMind.js``
(the "What I remember" / Mind surface).

Follows the convention of ``test_applicant_notifications_lens10.py``: every
fact is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket. Each assertion was hand-verified to go red
when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Finding covered (see ``docs/design/audits/exhaustive2/12_help_selfexplain.md``,
item #11): "Saved playbooks" and memory-curation approvals were never
explained — the Mind surface showed "Saved playbooks" and learning-curation
approve/decline rows with no copy saying what a playbook *is*, when the agent
consults one, or what approving/declining a "learning" changes about future
behavior. This adds a two-line intro ahead of the Saved-playbooks list plus
per-action ``title=`` explainers on the curation Approve/Dismiss buttons.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
MIND_JS = JS_DIR / "applicantMind.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Saved-playbooks section: intro copy explaining what a playbook is ──────

def test_saved_playbooks_section_has_intro_copy():
    """The "Saved playbooks" section header must be immediately followed by
    plain-language intro copy explaining what a playbook actually is, before
    the skills list itself is rendered."""
    js = _read(MIND_JS)
    m = re.search(
        r'<h4[^>]*>Saved playbooks</h4>\s*'
        r'<div[^>]*>(.*?)</div>\s*'
        r'\$\{_renderSkills\(skills\)\}',
        js,
        re.DOTALL,
    )
    assert m, (
        "expected intro copy between the 'Saved playbooks' header and the "
        "rendered skills list"
    )
    intro = m.group(1)
    assert "playbook" in intro.lower(), (
        "the intro copy must actually use the word 'playbook' while "
        "explaining it"
    )


def test_saved_playbooks_intro_explains_what_a_playbook_is_and_when_used():
    """The intro must say (in the product's own voice) what a playbook is
    (steps the assistant writes for itself) and when it's consulted (before
    doing similar work again) — not just gesture at the word."""
    js = _read(MIND_JS)
    m = re.search(
        r'<h4[^>]*>Saved playbooks</h4>\s*'
        r'<div[^>]*>(.*?)</div>\s*'
        r'\$\{_renderSkills\(skills\)\}',
        js,
        re.DOTALL,
    )
    assert m, "expected intro copy block before the skills list"
    intro = re.sub(r"\s+", " ", m.group(1)).strip().lower()
    assert "steps" in intro, "intro should describe a playbook as a set of steps"
    assert "again" in intro or "next time" in intro, (
        "intro should say the playbook is consulted before doing similar "
        "work again"
    )


# ── Curation approve/dismiss: per-action explainers ─────────────────────────

def test_curation_approve_button_has_explainer_title():
    """The curation "Approve" button must carry a title= explaining that
    approving actually saves the suggestion into what the assistant
    remembers and uses going forward."""
    js = _read(MIND_JS)
    m = re.search(
        r'<button type="button" class="cal-btn applicant-mind-approve"[^>]*title="([^"]+)"[^>]*>Approve</button>',
        js,
    )
    assert m, "expected a title= attribute on the curation Approve button"
    title = m.group(1).lower()
    assert "remember" in title or "save" in title, (
        "Approve's title should say this gets saved / remembered"
    )


def test_curation_dismiss_button_has_explainer_title():
    """The curation "Dismiss" button must carry a title= explaining that
    dismissing discards the suggestion without changing the assistant's
    memory or behavior."""
    js = _read(MIND_JS)
    m = re.search(
        r'<button type="button" class="cal-btn applicant-mind-deny"[^>]*title="([^"]+)"[^>]*>Dismiss</button>',
        js,
    )
    assert m, "expected a title= attribute on the curation Dismiss button"
    title = m.group(1).lower()
    assert "won't" in title or "not" in title or "throw" in title or "discard" in title, (
        "Dismiss's title should say nothing is saved/remembered as a result"
    )


# ── White-label: no codenames, no FR-/NFR- jargon in the new copy ──────────

_DENYLIST = re.compile(r"firehouse|orwell|odysseus|smokey|hermes-agent", re.IGNORECASE)


def test_new_copy_is_white_label_clean():
    """The new intro copy and button titles must not leak upstream
    persona/vendor codenames or FR-/NFR- requirement jargon."""
    js = _read(MIND_JS)
    assert not _DENYLIST.search(js), (
        "applicantMind.js must not contain upstream codenames"
    )
    assert not re.search(r"\bFR-[A-Z]+-\d+\b", js), (
        "applicantMind.js must not leak FR- requirement IDs into user-facing copy"
    )
    assert not re.search(r"\bNFR-[A-Z]+-\d+\b", js), (
        "applicantMind.js must not leak NFR- requirement IDs into user-facing copy"
    )
