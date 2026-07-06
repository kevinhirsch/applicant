"""Regression coverage for the accessibility deep pass (lens 05, exhaustive2),
docs/design/audits/exhaustive2/05_a11y_deep.md, items #64, #15/#16, #62, #23.

Confined to ``workspace/static/index.html`` only (per the batch brief). All
fixes here are additive/corrective attribute changes — no element structure,
ids, or ``<script>`` tags were touched.

- **#64** — the criteria/attribute editor inputs (job titles, locations, work
  modes, keywords, salary, attribute name/value, banned-phrases) carried
  ``aria-label`` overrides that duplicated their visible ``<label>`` or echoed
  the placeholder example, which wins the accessible-name computation over
  the real label. Where a proper ``<label for>`` already exists, the
  redundant/echoing ``aria-label`` was removed so the real label wins. The
  banned-phrases ``<textarea>`` has no visible ``<label>`` at all (only a
  sibling ``<span>``), so its ``aria-label`` was corrected to name the field
  instead of echoing the placeholder text.
- **#15/#16** — the status strip (``#applicant-status-strip``) was a
  clickable ``<button>`` whose role was overridden to ``status`` with a
  static ``aria-label`` masking the live child text, and no ``aria-atomic``.
  Fixed by leaving the button as a plain (unmasked) button and moving
  ``role="status" aria-live="polite" aria-atomic="true"`` onto the child
  ``#applicant-status-text`` span that JS actually updates.
- **#62** — ``.icon-rail`` (``#icon-rail``) was a bare ``<div>`` with no
  navigation semantics. Added ``role="navigation" aria-label="Icon rail"``.
- **#23** — the static, unwired ``aria-busy="false"`` on ``#chat-container``
  was removed (grepped: no JS ever toggles aria-busy on this specific id).

Follows the convention of ``test_applicant_round2_wave1_a11y_labels.py``:
every fact is read from the actual static file content via ``pathlib`` +
regex — no browser, no DOM, no real socket. Each assertion here was verified
by hand to go red when the corresponding fix is reverted (temporarily
restored to its pre-fix state from a backup) and green again once restored.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"


def _read() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _tag_for_id(html: str, element_id: str) -> str:
    """Return the full opening tag (any element) for a given `id="..."`."""
    m = re.search(rf'<[a-zA-Z][^>]*\bid="{re.escape(element_id)}"[^>]*>', html)
    assert m, f'expected an element with id="{element_id}" in index.html'
    return m.group(0)


def _attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{re.escape(name)}="([^"]*)"', tag)
    return m.group(1) if m else None


# ── #64: criteria/attribute editor — echoing/duplicate aria-labels removed ──

# Fields that already have a proper visible <label for="..."> association:
# the overriding aria-label must be gone so the real label wins.
LABELLED_FIELD_IDS_NO_ARIA_LABEL = [
    "applicant-crit-titles",
    "applicant-crit-locations",
    "applicant-crit-workmodes",
    "applicant-crit-keywords",
    "applicant-crit-salary",
    "applicant-attr-name",
    "applicant-attr-value",
]


def test_labelled_criteria_fields_have_no_overriding_aria_label():
    html = _read()
    for field_id in LABELLED_FIELD_IDS_NO_ARIA_LABEL:
        tag = _tag_for_id(html, field_id)
        assert _attr(tag, "aria-label") is None, (
            f"#{field_id} still has an aria-label overriding its visible "
            f"<label>: {tag}"
        )
        # Sanity: each of these must still have a real <label for="id">
        # pointing at it, otherwise removing aria-label would strand it
        # nameless.
        assert re.search(rf'<label\b[^>]*\bfor="{re.escape(field_id)}"', html), (
            f'#{field_id} has no aria-label but also no <label for="{field_id}">'
        )


def test_criteria_fields_still_have_a_title_hint():
    # We didn't touch the `title` tooltips — just the competing aria-labels.
    html = _read()
    for field_id in ("applicant-crit-titles", "applicant-crit-salary", "applicant-attr-value"):
        tag = _tag_for_id(html, field_id)
        assert _attr(tag, "title"), f"#{field_id} unexpectedly lost its title hint"


def test_banned_phrases_textarea_aria_label_no_longer_echoes_placeholder():
    html = _read()
    tag = _tag_for_id(html, "applicant-banned-input")
    placeholder = _attr(tag, "placeholder")
    aria_label = _attr(tag, "aria-label")
    assert aria_label, "#applicant-banned-input should keep a naming aria-label (no visible <label> exists)"
    assert aria_label != placeholder, (
        "#applicant-banned-input's aria-label should no longer be a verbatim "
        "echo of its placeholder example"
    )
    assert "delve into" not in aria_label, "aria-label still echoes the placeholder example text"
    assert re.search(r"\bphrase", aria_label, re.IGNORECASE), (
        "aria-label should plainly name the field (phrases to never use)"
    )


# ── #15/#16: status strip — plain button + live region on the child span ──


def test_status_strip_button_is_not_masqueraded_as_a_status_role():
    html = _read()
    tag = _tag_for_id(html, "applicant-status-strip")
    assert _attr(tag, "role") is None, (
        "#applicant-status-strip is a clickable <button> and must not have "
        "its role overridden to status"
    )
    assert _attr(tag, "aria-live") is None, (
        "aria-live belongs on the live text span, not the clickable button wrapper"
    )
    assert _attr(tag, "aria-label") is None, (
        "a static aria-label on the button masks the live child text from "
        "being announced — it must be removed so the button's name is "
        "computed from its (live) content"
    )


def test_status_text_span_is_the_live_region_now():
    html = _read()
    tag = _tag_for_id(html, "applicant-status-text")
    assert _attr(tag, "role") == "status", "#applicant-status-text must carry role=status"
    assert _attr(tag, "aria-live") == "polite", "#applicant-status-text must carry aria-live=polite"
    assert _attr(tag, "aria-atomic") == "true", "#applicant-status-text must carry aria-atomic=true"


# ── #62: icon rail gets navigation semantics ──


def test_icon_rail_has_navigation_role_and_label():
    html = _read()
    tag = _tag_for_id(html, "icon-rail")
    assert _attr(tag, "role") == "navigation", "#icon-rail must have role=navigation"
    label = _attr(tag, "aria-label")
    assert label, "#icon-rail must have a non-empty aria-label naming the rail"


# ── #23: unwired static aria-busy removed from #chat-container ──


def test_chat_container_has_no_unwired_static_aria_busy():
    html = _read()
    tag = _tag_for_id(html, "chat-container")
    assert _attr(tag, "aria-busy") is None, (
        "#chat-container's aria-busy=false was static and never toggled by "
        "any JS — it should be removed rather than left as a misleading decoy"
    )
    # The region role/label (unrelated finding, not part of this batch) must
    # still be intact.
    assert _attr(tag, "role") == "region"
    assert _attr(tag, "aria-label") == "Chat area"
