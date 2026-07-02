"""Regression coverage for the §G Content-routes design-audit fix batch,
Notes/Email slice (items 139, 140, 141, 142, 144), confined to
``static/js/notes.js`` and ``static/js/emailInbox.js`` (+ the CSS facts they
depend on in ``static/style.css``).

Follows the convention of ``tests/bdd/steps/test_enh_uia11y_steps.py`` /
``workspace/tests/test_applicant_round1_chatmind.py``: every fact is read
from the actual static file content via ``pathlib`` + regex — no browser, no
DOM, no real socket.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore via ``git checkout``) per the batch's test-coverage DoD.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
NOTES_JS = JS_DIR / "notes.js"
EMAIL_JS = JS_DIR / "emailInbox.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_css_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


# ── #139: .note-color-* body pastel removed, top-edge stripe remains ──────

def test_note_color_rules_no_longer_pastel_the_body():
    """The generic `.note-color-*` rule on the note BODY must no longer set
    a pastel `background`/`border-color` — only the existing top-edge
    inset-stripe (`box-shadow: inset 0 2px ...`) remains as the color
    marker. The separate `.note-form.note-color-*` `!important` rule for
    the live color-picker preview is a distinct concern and stays alone."""
    css = _read(STYLE_CSS)
    for color in ("red", "orange", "yellow", "green", "blue", "purple"):
        # The plain (non `.note-form`-scoped) rule.
        m = re.search(
            r"(?<!\.note-form)\.note-color-" + color + r"\s*\{([^}]*)\}",
            css,
        )
        assert m, f"expected a .note-color-{color} rule"
        block = m.group(1)
        assert re.search(r"box-shadow:\s*inset 0 2px", block), (
            f".note-color-{color} must keep the top-edge inset-stripe marker"
        )
        assert "background:" not in block, (
            f".note-color-{color} must not set a pastel background on the note body"
        )
        assert "border-color:" not in block, (
            f".note-color-{color} must not set a pastel border-color on the note body"
        )

    # The .note-form live-preview override is a deliberately different,
    # untouched concern — it still pastels the form background with !important.
    form_red = re.search(r"\.note-form\.note-color-red\s*\{([^}]*)\}", css)
    assert form_red, "expected the .note-form.note-color-red live-preview rule to still exist"
    assert "background:" in form_red.group(1) and "!important" in form_red.group(1), (
        ".note-form's own live color-picker preview rule should remain untouched"
    )


# ── #140: fired-sticky reminder marker is static, no infinite glow ────────

def test_reminder_fired_sticky_marker_has_no_animation():
    """`.note-card-reminder-fired-sticky` must be a static outline/box-shadow
    with no `animation` property — the old `infinite` glow loop is gone."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"\.note-card\.note-card-reminder-fired-sticky\s*\{([^}]*)\}", css
    )
    assert m, "expected a .note-card.note-card-reminder-fired-sticky rule"
    block = m.group(1)
    assert "animation" not in block, (
        "the fired-sticky reminder marker must not animate (was an infinite glow)"
    )
    assert re.search(r"outline:\s*1px solid", block) or re.search(
        r"box-shadow:", block
    ), "expected a static outline/box-shadow to still mark the fired-sticky state"


def test_reminder_fired_marker_is_still_a_one_shot_animation():
    """Sibling sanity check: `.note-card-reminder-fired` (distinct from the
    `-sticky` variant above) was already a one-shot, non-infinite animation
    and is untouched by this fix — it must not regress to `infinite`."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"\.note-card\.note-card-reminder-fired\s*\{([^}]*)\}", css
    )
    assert m, "expected a .note-card.note-card-reminder-fired rule"
    assert "infinite" not in m.group(1), (
        ".note-card-reminder-fired must stay a one-shot (non-infinite) animation"
    )


# ── #141: emailInbox.js empty-state builder ────────────────────────────────

def test_email_empty_state_has_symbol_guidance_and_real_ctas():
    """`_buildEmailEmptyState()` must render a symbol + guidance text +
    Compose/Connect-account CTA buttons (a first-class empty state), not a
    reused plain loading-text row."""
    src = _read(EMAIL_JS)
    fn = re.search(
        r"function _buildEmailEmptyState\(\) \{(.*?)\n\}\n", src, re.S
    )
    assert fn, "expected a _buildEmailEmptyState() function"
    body = fn.group(1)
    assert "email-empty-state" in body, "expected the empty-state wrapper class"
    assert "<svg" in body, "expected a symbol/icon in the empty state"
    assert "email-empty-msg" in body, "expected guidance text in the empty state"
    assert re.search(
        r'<button type="button" class="cal-btn cal-btn-primary" id="email-empty-compose">Compose</button>',
        body,
    ), "expected a real Compose CTA button"
    assert re.search(
        r'<button type="button" class="cal-btn" id="email-empty-connect">Connect account</button>',
        body,
    ), "expected a real Connect-account CTA button"
    assert "_composeNew()" in body and "_openIntegrationsSettings()" in body, (
        "the CTAs must be wired to real actions, not dead buttons"
    )

    # And it must actually be used when the inbox list is empty.
    assert "list.appendChild(_buildEmailEmptyState());" in src, (
        "expected the empty-state builder to be used when _emails is empty"
    )


# ── #142: base unread-email dot standardized to --sys-blue ────────────────

def test_unread_email_dot_defaults_to_sys_blue():
    """The base unread-email indicator dot must default to `--sys-blue`;
    the distinct urgency-score override (red=urgent/orange=reply-soon) is
    a separate signal and must be left in place."""
    src = _read(EMAIL_JS)
    m = re.search(r"let _unreadColor = '([^']+)';", src)
    assert m, "expected a default _unreadColor variable"
    assert m.group(1) == "var(--sys-blue)", (
        "the base unread dot color must default to --sys-blue"
    )
    # The urgency overrides are a distinct, still-present signal.
    assert "score >= 3" in src and "score === 2" in src, (
        "the urgent/reply-soon urgency overrides must remain in place"
    )


# ── #144: rail pulses rest under prefers-reduced-motion ────────────────────

def test_rail_pulses_disabled_under_reduced_motion():
    """`rail-notes-pulse` (`.rail-notes-badge.fired`, `.tool-notes-dot`) and
    `rail-min-pulse` (`.rail-minimized::after`) must rest un-animated under
    `prefers-reduced-motion: reduce`."""
    css = _read(STYLE_CSS)
    for m in re.finditer(
        r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*?)\n\s*\}\s*\n",
        css,
        re.S,
    ):
        block = m.group(1)
        if "rail-notes-badge.fired" in block:
            reduced_block = block
            break
    else:
        raise AssertionError(
            "expected a prefers-reduced-motion block covering the rail pulses"
        )
    assert ".rail-notes-badge.fired" in reduced_block
    assert ".tool-notes-dot" in reduced_block
    assert ".rail-minimized::after" in reduced_block
    assert re.search(r"animation:\s*none", reduced_block), (
        "expected animation: none inside the reduced-motion rail-pulse block"
    )

    # And the animations themselves must still exist un-gated at rest (i.e.
    # this is a reduced-motion override, not a full removal like #123).
    assert "rail-notes-pulse" in _strip_css_comments(css).replace(reduced_block, "")
    assert "rail-min-pulse" in _strip_css_comments(css).replace(reduced_block, "")
