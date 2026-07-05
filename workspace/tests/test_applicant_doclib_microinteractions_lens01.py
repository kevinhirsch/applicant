"""Regression coverage for exhaustive-audit-pass-2 lens 01 (micro-interactions
& input mechanics), confined to ``static/js/documentLibrary.js``.

Follows the convention of ``test_applicant_documentlibrary_redline_lens04.py``:
every fact is read from the actual static file content via ``pathlib`` + regex
— no browser, no DOM, no real socket. Each assertion was hand-verified to go
red when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/01_micro_interactions.md``):
  * #6  — the "Draft cover letter" / "Draft screening answer" buttons fired a
    POST with no in-flight guard; a double-click drafted two of each. Both
    now disable (and relabel) themselves for the duration of their own
    request.
  * #10 — the screening-question prompt used a bare ``window.prompt()``.
    Replaced with the workspace's ``styledPrompt`` (the same helper the
    digest's Pass flow already uses), falling back to ``window.prompt`` only
    if the kit helper is unavailable.
  * #15 — the application-id and job-search-id lookup inputs' Enter handlers
    had no ``isComposing``/keyCode-229 guard, so an IME composition-commit
    Enter (CJK / dead-key input) fired the lookup prematurely.
  * #40 — Approve/Decline in the redline review panel called
    ``_loadApplicantMaterials`` directly, tearing down and rebuilding the
    whole list (scroll to top, the just-reviewed item's panel collapses).
    Both handlers now go through ``_reloadApplicantMaterialsPreservingContext``,
    which preserves the list's scroll position and best-effort reopens the
    same item's review panel afterwards.
  * #63 — the redline pane was hard-capped at ``max-height:200px`` with no
    way to see more. A show-more/show-less toggle now lifts the cap to
    ``none`` and back, appearing only when the content actually overflows.
  * #65 — resume-variant-library cards (the "Resume versions" list) were
    inert divs. They are now keyboard-activatable/clickable, opening the
    variant's compiled PDF (the same download endpoint the materials-list
    variant card's "Download PDF" button already calls).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #6: in-flight busy/disable guard on the draft cover-letter / answer buttons ──

def test_cover_letter_button_disables_while_in_flight():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"const coverBtn = genWrap\.querySelector\('#doclib-gen-cover-btn'\);"
        r"[\s\S]*?coverBtn\.addEventListener\('click', async \(\) => \{([\s\S]*?)\n\s*\}\);\s*\n\s*const answerBtn",
        js,
    )
    assert m, "expected the cover-letter button's click handler"
    body = m.group(1)
    assert "if (coverBtn.disabled) return;" in body, (
        "expected an in-flight re-entrancy guard on the cover-letter button"
    )
    assert "coverBtn.disabled = true;" in body
    assert re.search(r"finally\s*\{\s*coverBtn\.disabled = false;", body), (
        "expected the button to always re-enable itself once the request settles"
    )


def test_screening_answer_button_disables_while_in_flight():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"const answerBtn = genWrap\.querySelector\('#doclib-gen-answer-btn'\);"
        r"[\s\S]*?answerBtn\.addEventListener\('click', async \(\) => \{([\s\S]*?)\n\s*\}\);\s*\n\s*\n\s*// Template merge-fill",
        js,
    )
    assert m, "expected the screening-answer button's click handler"
    body = m.group(1)
    assert "if (answerBtn.disabled) return;" in body, (
        "expected an in-flight re-entrancy guard on the screening-answer button"
    )
    assert "answerBtn.disabled = true;" in body
    assert re.search(r"finally\s*\{\s*answerBtn\.disabled = false;", body), (
        "expected the button to always re-enable itself once the request settles"
    )


# ── #10: styledPrompt instead of window.prompt for the screening question ──

def test_screening_question_uses_styled_prompt_not_bare_window_prompt():
    js = _read(DOCLIB_JS)
    # The old unguarded single-line call must be gone.
    assert "(window.prompt('What screening question should I answer?') || '').trim();" not in js, (
        "the screening question must no longer be captured via a bare window.prompt()"
    )
    assert "uiModule.styledPrompt('What screening question should I answer?'" in js, (
        "expected the screening question to be captured via uiModule.styledPrompt"
    )
    # window.prompt may still appear as a defensive fallback only.
    m = re.search(
        r"uiModule && uiModule\.styledPrompt\s*\n\s*\?\s*await uiModule\.styledPrompt\("
        r"'What screening question should I answer\?',\s*\{([\s\S]*?)\}\,?\s*\)\s*\n\s*:\s*"
        r"window\.prompt\('What screening question should I answer\?'\)",
        js,
    )
    assert m, "expected a styledPrompt-first, window.prompt-fallback pattern"


# ── #15: isComposing guard on the appid / campaign-id lookup Enter handlers ──

def test_applicant_appid_lookup_guards_ime_composition_enter():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"input\.addEventListener\('keydown', \(e\) => \{([\s\S]*?)\}\);",
        js,
    )
    assert m, "expected the application-id input's keydown handler"
    body = m.group(1)
    assert "e.isComposing" in body and "_go();" in body, (
        "expected the application-id lookup Enter handler to guard IME composition"
    )


def test_variant_campaign_lookup_guards_ime_composition_enter():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"vInput\.addEventListener\('keydown', \(e\) => \{([\s\S]*?)\}\);",
        js,
    )
    assert m, "expected the job-search-id (variant) input's keydown handler"
    body = m.group(1)
    assert "e.isComposing" in body and "_goVariants();" in body, (
        "expected the variant lookup Enter handler to guard IME composition"
    )


# ── #40: Approve/Decline preserve scroll / reopen the same item in place ──

def test_reload_helper_preserves_scroll_and_reopens_same_item():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"async function _reloadApplicantMaterialsPreservingContext\(appId, results, openItemId\) \{([\s\S]*?)\n\s*\}\n",
        js,
    )
    assert m, "expected the _reloadApplicantMaterialsPreservingContext helper"
    body = m.group(1)
    assert "scrollTop" in body, "expected the helper to capture/restore scroll position"
    assert "await _loadApplicantMaterials(appId, results);" in body
    assert "CSS.escape(String(openItemId))" in body, (
        "expected the helper to look the same item back up after the reload"
    )
    assert ".doclib-applicant-review-toggle" in body, (
        "expected the helper to reopen via the review-toggle button"
    )


def test_approve_and_decline_call_the_context_preserving_reload():
    js = _read(DOCLIB_JS)
    approve_m = re.search(
        r"if \(uiModule\) uiModule\.showToast\('Document approved'\);\s*\n(.*?)\n\s*\} catch \(err\) \{\s*\n\s*approveBtn\.disabled = false;",
        js,
        re.DOTALL,
    )
    assert approve_m, "expected the redline panel's approve-success handler"
    assert "_reloadApplicantMaterialsPreservingContext(appId, results, item.id);" in approve_m.group(1), (
        "expected Approve to use the context-preserving reload, not a bare full reload"
    )

    decline_m = re.search(
        r"if \(uiModule\) uiModule\.showToast\('Document declined'\);\s*\n(.*?)\n\s*\} catch \(err\) \{\s*\n\s*declineBtn\.disabled = false;",
        js,
        re.DOTALL,
    )
    assert decline_m, "expected the redline panel's decline-success handler"
    assert "_reloadApplicantMaterialsPreservingContext(appId, results, item.id);" in decline_m.group(1), (
        "expected Decline to use the context-preserving reload, not a bare full reload"
    )


def test_card_carries_item_id_for_reload_lookup():
    js = _read(DOCLIB_JS)
    assert "card.dataset.itemId = String(item.id);" in js, (
        "expected each material card to carry its item id in the DOM so the "
        "context-preserving reload can find it again"
    )


# ── #63: redline expand/collapse toggle ──

def test_redline_has_show_more_toggle():
    js = _read(DOCLIB_JS)
    assert "const redlineToggle = document.createElement('button');" in js, (
        "expected a redline expand/collapse toggle button"
    )
    m = re.search(
        r"const _syncRedlineToggle = \(\) => \{([\s\S]*?)\n\s*\};",
        js,
    )
    assert m, "expected a _syncRedlineToggle helper"
    body = m.group(1)
    assert "redline.style.maxHeight" in body
    assert "redline.scrollHeight > redline.clientHeight" in body, (
        "expected the toggle's visibility to depend on actual overflow"
    )


def test_redline_toggle_flips_maxheight_between_capped_and_none():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"redlineToggle\.addEventListener\('click', \(\) => \{([\s\S]*?)\n\s*\}\);",
        js,
    )
    assert m, "expected a click handler on the redline toggle"
    body = m.group(1)
    assert "redline.style.maxHeight === 'none' ? '200px' : 'none'" in body, (
        "expected the toggle to flip the redline between the 200px cap and no cap"
    )


def test_redline_still_starts_capped_at_200px():
    js = _read(DOCLIB_JS)
    assert "max-height:200px;overflow:auto;" in js, (
        "expected the redline's initial compact cap to be preserved"
    )


# ── #65: variant-library cards are clickable / keyboard-activatable ──

def test_variant_card_is_a_focusable_button_role_with_dataset_id():
    js = _read(DOCLIB_JS)
    assert "class=\"admin-card doclib-variant-card\" data-variant-id=" in js, (
        "expected each variant row to carry a data-variant-id hook"
    )
    assert "role=\"${rawId ? 'button' : 'group'}\" tabindex=\"${rawId ? '0' : '-1'}\"" in js, (
        "expected variant cards with a real id to be keyboard-focusable buttons"
    )


def test_variant_card_click_and_keyboard_open_the_same_download_endpoint():
    js = _read(DOCLIB_JS)
    m = re.search(
        r"container\.querySelectorAll\('\.doclib-variant-card\[data-variant-id\]'\)\.forEach\(\(el\) => \{([\s\S]*?)\n\s*\}\);\s*\n\s*\}",
        js,
    )
    assert m, "expected the wiring block for variant-card open behavior"
    body = m.group(1)
    assert "/variants/${encodeURIComponent(vid)}/download`" in body, (
        "expected the variant card's open action to reuse the existing download endpoint"
    )
    assert "el.addEventListener('click', _openVariant);" in body
    assert re.search(r"e\.key !== 'Enter' && e\.key !== ' '", body), (
        "expected both Enter and Space to activate the variant card from the keyboard"
    )


def test_no_upstream_codenames_or_fr_jargon_introduced():
    """White-label: the new code/comments must not leak FR-/NFR- requirement
    jargon or upstream vendor/persona codenames into the file (user-facing
    strings must stay plain language)."""
    js = _read(DOCLIB_JS)
    for marker in ("_reloadApplicantMaterialsPreservingContext", "redlineToggle", "doclib-variant-card", "coverBtn"):
        idx = js.find(marker)
        assert idx != -1, f"expected to find marker {marker!r}"
        window = js[max(0, idx - 400): idx + 4000]
        assert not re.search(r"\bFR-[A-Z]", window)
        assert not re.search(r"\bNFR-[A-Z]", window)
