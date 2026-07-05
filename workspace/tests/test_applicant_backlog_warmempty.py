"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md's
delight backlog item "warm empty states everywhere," confined to this batch's
four owned modules: applicantMind.js, applicantCompare.js, applicantGallery.js,
applicantVault.js.

Per-file findings (see PR description / session notes for the full audit):

- applicantMind.js: the curation ("Waiting for your review") empty copy was
  ALREADY warm (explains what the surface is, why it's empty, what happens
  next) — left untouched. The two per-block memory hints inside
  `_renderMemory` ("Nothing remembered yet." / "No preferences captured
  yet.") were genuinely flat — warmed to explain why the section is empty
  and what will fill it. The modal-offline note and the saved-playbooks
  empty copy were warm in shape but still spoke in third person ("the
  assistant") and leaned on "AI model" jargon — the copy/voice (exhaustive2
  lens 02) audit's findings #163/#164 rewrote both to first person.
- applicantCompare.js: the modal's initial "Nothing to compare yet" empty
  state already reused the shared `emptyHTML()` kit and was warm. The
  `_renderResult` no-data fallback ("No comparison returned.") was a bare,
  un-kitted string — rewritten to use the same shared `emptyHTML()` kit with
  plain-language guidance.
- applicantGallery.js: the "No job searches yet" and "Nothing captured yet"
  top-level empty states already used `emptyHTML()` with a Create-a-job-search
  CTA and were warm. The per-section fallbacks (screenshots / materials, via
  the local `_empty()` helper) were flat one-liners — warmed to explain what
  populates each section.
- applicantVault.js: the intro paragraph and the confirm-before-discard copy
  were already warm; the "no job search selected" and "no sign-ins saved yet"
  empty-list notes (both the static markup default and the two JS-set
  strings) were flat — warmed to explain why empty and what to do.

Follows the convention of test_applicant_round1_remainder_welcomecard.py:
every fact is read from the actual static file content via `pathlib` + regex
— no browser, no DOM, no real socket, since these are simple copy/text
assertions rather than structural DOM-behavior ones.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion fail
-> restore) per the batch's test-coverage DoD.
"""

from __future__ import annotations

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"

MIND_JS = JS_DIR / "applicantMind.js"
COMPARE_JS = JS_DIR / "applicantCompare.js"
GALLERY_JS = JS_DIR / "applicantGallery.js"
VAULT_JS = JS_DIR / "applicantVault.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── applicantMind.js ─────────────────────────────────────────────────────────

def test_mind_memory_block_hints_are_warm_not_flat():
    js = _read(MIND_JS)
    # The old flat, no-context hints must be gone.
    assert "'Nothing remembered yet.'" not in js
    assert "'No preferences captured yet.'" not in js
    # Warm replacements explain WHY it's empty and WHAT fills it.
    assert "Nothing remembered about the work yet" in js
    assert "the lessons it picks up along the way will show up here" in js
    assert "No preferences captured yet — tell the assistant what you like" in js


def test_mind_curation_notes_already_warm_untouched():
    """Sanity check that the curation empty-state (already warm since this
    batch) is still intact — proves this pass was a copy/tone fix, not a
    wholesale rewrite of applicantMind.js."""
    js = _read(MIND_JS)
    assert "Nothing waiting for your review. New suggestions appear here before anything is saved." in js


def test_mind_offline_and_skills_notes_are_first_person_not_third():
    """copy/voice (02) audit #163/#164: the modal-offline note and the
    saved-playbooks empty state used to speak in third person ("the
    assistant") and lean on internal "AI model" jargon — both rewritten to
    first person, plain language. The old third-person strings must be gone."""
    js = _read(MIND_JS)
    assert "Connect an AI model to start building what the assistant remembers" not in js
    assert "Connect a model in Settings or the setup wizard, and I'll start remembering" in js
    assert "what I learn." in js
    assert "No saved playbooks yet. The assistant writes these from its own work." not in js
    assert "No saved playbooks yet. I write these as I learn from my own work." in js


# ── applicantCompare.js ──────────────────────────────────────────────────────

def test_compare_no_data_fallback_uses_shared_empty_kit_not_bare_string():
    js = _read(COMPARE_JS)
    assert "'<div style=\"opacity:0.7;\">No comparison returned.</div>'" not in js
    assert "No comparison came back" in js
    # Copy/voice pass (02): the follow-up line dropped the "engine" jargon in
    # favor of first-person, plain-language guidance — assert the jargon is
    # gone and the warm replacement is present.
    assert "The engine did not return a result for that comparison" not in js
    assert "I couldn't build a comparison from those IDs" in js


def test_compare_initial_empty_state_already_warm_untouched():
    js = _read(COMPARE_JS)
    assert "Nothing to compare yet" in js
    # Copy/voice pass (02): "ids" -> "IDs" casing fix (item #229).
    assert "Pick applications or postings above, paste two or more IDs" in js
    # Both empty states route through the shared kit — consistency check.
    assert js.count("emptyHTML(") >= 2


# ── applicantGallery.js ──────────────────────────────────────────────────────

def test_gallery_section_empty_states_are_warm_not_flat():
    js = _read(GALLERY_JS)
    assert "_empty('No screenshots yet.')" not in js
    assert "_empty('No generated materials yet.')" not in js
    assert "these are captured automatically as the agent works through each page" in js
    assert "resumes, cover letters, and screening answers will appear here as the agent drafts them" in js


def test_gallery_top_level_empty_states_already_warm_untouched():
    js = _read(GALLERY_JS)
    assert "Create a job search to start capturing screenshots and materials here." in js
    assert "This job search has no screenshots or generated materials yet" in js


# ── applicantVault.js ────────────────────────────────────────────────────────

def test_vault_no_signins_notes_are_warm_not_flat():
    js = _read(VAULT_JS)
    # None of the three old bare copies should remain verbatim.
    assert "No sign-ins saved yet.\n" not in js
    assert "'Choose a job search first.'" not in js
    # The static markup default and both JS-set strings now explain the why
    # and the next action, and stay consistent with each other.
    warm_no_signins = "No sign-ins saved yet — add one below and the assistant will use it to sign in automatically."
    assert js.count(warm_no_signins) == 2  # markup default + the JS re-set on empty list
    assert "No job search yet — sign-ins are saved per job search, so create one first and they will show up here." in js


def test_vault_intro_and_discard_copy_already_warm_untouched():
    js = _read(VAULT_JS)
    assert "Passwords are encrypted and are never shown again or sent" in js
    assert "back to this screen." in js
    assert "Discard the sign-in details you just typed? They have not been saved yet." in js
