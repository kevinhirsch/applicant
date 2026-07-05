"""Regression coverage for exhaustive-audit-pass-2 lens 04 (failure paths)
findings #69 and #54, confined to ``static/js/documentLibrary.js`` (the
inline redline/review panel opened from "Review and edit" in the Documents
tab).

Follows the convention of ``test_applicant_notifications_lens10.py``: every
fact is read from the actual static file content via ``pathlib`` + regex —
no browser, no DOM, no real socket. Each assertion was hand-verified to go
red when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see
``docs/design/audits/exhaustive2/04_failure_paths.md``):
  * #69 — ``redline.innerHTML = rl.rendered_html`` (and the "Compare to
    original" turn's ``renderedHtml2``) injected the engine's redline HTML
    straight into the DOM with no sanitization. That HTML incorporates
    scraped/model-derived content (posting text, LLM output), so it is an
    XSS sink. Both sites now route through ``markdownModule
    .sanitizeAllowedHtml`` — the workspace's existing allowlist HTML
    sanitizer (``static/js/markdown.js``, already used to scrub the
    ``<details>``/``<a>`` fragments ``mdToHtml`` preserves) — instead of
    assigning the untrusted string to ``innerHTML`` raw.
  * #54 — the free-text "ask for a change" instruction lived only in the
    DOM textarea, so re-rendering the review panel (after a turn's response,
    or a full materials reload closing/reopening it) silently discarded
    whatever the user had typed but not yet sent. A module-level draft map
    now persists the in-progress instruction (+ selected kind) keyed by
    document id, restoring it whenever the panel (re)builds and clearing it
    once the instruction is actually submitted (or the document is decided).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
DOCLIB_JS = JS_DIR / "documentLibrary.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #69: sanitize the engine-rendered redline HTML before injection ────────

def test_documentlibrary_imports_the_shared_markdown_sanitizer():
    """The fix must reuse the workspace's existing allowlist HTML sanitizer
    (``sanitizeAllowedHtml`` in ``markdown.js``) rather than inventing a new
    one — the file already imports the module as ``markdownModule``."""
    js = _read(DOCLIB_JS)
    assert re.search(r"import\s+markdownModule\s+from\s+['\"]\./markdown\.js['\"]", js), (
        "expected documentLibrary.js to import the shared markdown module"
    )


def test_primary_redline_html_is_sanitized_not_assigned_raw():
    """The PRIMARY redline render (`rl.rendered_html`/`rl.html`) must be
    passed through the sanitizer before it reaches innerHTML. A raw
    `redline.innerHTML = renderedHtml;` (with no sanitizer call anywhere on
    that statement) is exactly the unfixed XSS sink lens 04 #69 flagged."""
    js = _read(DOCLIB_JS)
    assert "const renderedHtml = rl && (rl.rendered_html || rl.html);" in js, (
        "expected the primary renderedHtml extraction to still be present"
    )
    # The dangerous raw form must not appear anywhere in the file.
    assert "redline.innerHTML = renderedHtml;" not in js, (
        "the primary redline must not assign the untrusted engine HTML to "
        "innerHTML unsanitized"
    )
    m = re.search(r"redline\.innerHTML\s*=\s*([^;]+);\s*\n\s*\}\s*else if \(additions\.length", js)
    assert m, "expected to find the primary redline's innerHTML assignment"
    assignment = m.group(1)
    assert "markdownModule.sanitizeAllowedHtml(renderedHtml)" in assignment, (
        "the primary redline HTML must be run through the shared sanitizer "
        f"before assignment; got: {assignment!r}"
    )


def test_compare_to_original_redline_html_is_also_sanitized():
    """The "Compare to original" turn re-injects a second engine-rendered
    diff (`renderedHtml2`) into the SAME `redline` element; this site must be
    sanitized too, not just the first render."""
    js = _read(DOCLIB_JS)
    assert "const renderedHtml2 = diff && (diff.rendered_html || diff.html);" in js, (
        "expected the compare-to-original renderedHtml2 extraction to still be present"
    )
    assert "redline.innerHTML = renderedHtml2;" not in js, (
        "the compare-to-original redline must not assign the untrusted "
        "engine HTML to innerHTML unsanitized"
    )
    m = re.search(r"redline\.innerHTML\s*=\s*([^;]+);\s*\n\s*\}\s*else if \(additions2\.length", js)
    assert m, "expected to find the compare-to-original redline's innerHTML assignment"
    assignment = m.group(1)
    assert "markdownModule.sanitizeAllowedHtml(renderedHtml2)" in assignment, (
        "the compare-to-original redline HTML must be run through the shared "
        f"sanitizer before assignment; got: {assignment!r}"
    )


def test_redline_visual_styling_markers_are_preserved():
    """The sanitizer swap must not have collapsed the fallback add/remove
    visual markers (the plain-list path is untouched by the sanitizer fix,
    but a naive rewrite could plausibly have deleted it alongside the
    primary branch)."""
    js = _read(DOCLIB_JS)
    assert "color:var(--color-success,#4caf50)" in js
    assert "color:var(--color-danger,#e06c75)" in js


# ── #54: persist the free-text "ask for a change" instruction across re-render ──

def test_review_instruction_draft_store_exists_module_level():
    """A module-level draft store must exist so a typed-but-unsent
    instruction survives `_renderApplicantReview` being called again for the
    same panel (e.g. after a turn, or after a materials reload reopens the
    review)."""
    js = _read(DOCLIB_JS)
    assert re.search(r"const _reviewInstructionDrafts\s*=\s*new Map\(\);", js), (
        "expected a module-level Map tracking in-progress review instructions"
    )


def test_review_render_restores_draft_before_binding_placeholder():
    """`_renderApplicantReview` must read any saved draft for this item and
    write it into the textarea/kind-select before the box is usable, keyed
    by the document id so it targets the right panel."""
    js = _read(DOCLIB_JS)
    m = re.search(
        r"function _renderApplicantReview\(item, appId, panel, session, card, results\) \{([\s\S]*?)\n    \}\n",
        js,
    )
    assert m, "expected to locate the _renderApplicantReview function body"
    body = m.group(1)
    assert "_reviewInstructionDrafts.get(_draftKey)" in body, (
        "expected the render to look up a saved draft for this item"
    )
    assert "instruction.value = _draft.text;" in body, (
        "expected a saved draft's text to be restored into the textarea"
    )
    assert "kindSel.value = _draft.kind" in body, (
        "expected a saved draft's kind to be restored into the select"
    )


def test_instruction_input_persists_draft_on_every_keystroke():
    """The textarea must save its value to the draft store on `input` (not
    just on send), so a re-render mid-typing doesn't lose anything."""
    js = _read(DOCLIB_JS)
    assert "instruction.addEventListener('input', _saveDraft);" in js, (
        "expected the instruction textarea to persist its draft on every keystroke"
    )
    m = re.search(r"const _saveDraft = \(\) => \{([\s\S]*?)\n\s*\};", js)
    assert m, "expected a _saveDraft helper"
    save_body = m.group(1)
    assert "_reviewInstructionDrafts.set(_draftKey" in save_body
    assert "_reviewInstructionDrafts.delete(_draftKey)" in save_body


def test_draft_cleared_once_the_instruction_is_actually_submitted():
    """Once a turn POST succeeds, the draft must be cleared so the next
    render doesn't resurrect an already-applied instruction."""
    js = _read(DOCLIB_JS)
    m = re.search(
        r"if \(!res\.ok\) throw new Error\(await _applicantErrText\(res\)\);\s*\n\s*const next = await res\.json\(\);\s*\n(.*?)\n\s*if \(uiModule\) uiModule\.showToast\('Change applied'\);",
        js,
        re.DOTALL,
    )
    assert m, "expected the turn-success handler for the 'Request change' button"
    assert "_reviewInstructionDrafts.delete(_draftKey);" in m.group(1), (
        "expected the draft to be cleared once the instruction is applied"
    )


def test_draft_cleared_on_approve_and_decline():
    """Approving/declining ends this document's review flow; the draft store
    should not leak a stale instruction into a future reopen of the same
    item's panel."""
    js = _read(DOCLIB_JS)
    approve_m = re.search(
        r"/approve`, \{ method: 'POST', credentials: 'same-origin' \}\);\s*\n\s*if \(!res\.ok\) throw new Error\(await _applicantErrText\(res\)\);\s*\n(.*?)\n\s*if \(uiModule\) uiModule\.showToast\('Document approved'\);",
        js,
    )
    assert approve_m, "expected the approve-success handler"
    assert "_reviewInstructionDrafts.delete(_draftKey);" in approve_m.group(1)

    decline_m = re.search(
        r"/decline`, \{ method: 'POST', credentials: 'same-origin' \}\);\s*\n\s*if \(!res\.ok\) throw new Error\(await _applicantErrText\(res\)\);\s*\n(.*?)\n\s*if \(uiModule\) uiModule\.showToast\('Document declined'\);",
        js,
    )
    assert decline_m, "expected the decline-success handler"
    assert "_reviewInstructionDrafts.delete(_draftKey);" in decline_m.group(1)


def test_no_upstream_codenames_or_fr_jargon_introduced():
    """White-label: the new code/comments must not leak FR-/NFR- requirement
    jargon into the file (user-facing strings must stay plain language)."""
    js = _read(DOCLIB_JS)
    idx = js.find("_reviewInstructionDrafts")
    assert idx != -1
    window = js[max(0, idx - 400): idx + 4000]
    assert not re.search(r"\bFR-[A-Z]", window)
    assert not re.search(r"\bNFR-[A-Z]", window)
