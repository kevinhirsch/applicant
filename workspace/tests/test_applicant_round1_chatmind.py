"""Regression coverage for the §C Chat/Mind design-audit fix batch (items
45-64), confined to ``static/js/applicantChat.js`` and
``static/js/applicantMind.js`` (+ the CSS facts they depend on in
``static/style.css``).

Follows the convention of ``tests/bdd/steps/test_enh_uia11y_steps.py``: every
fact is read from the actual static file content via ``pathlib`` + regex —
no browser, no DOM, no real socket. These two modules do top-level
``document``/``fetch`` work on import (they wire launchers via
``document.readyState``), so they are not importable under a bare
``node --input-type=module`` the way a dependency-free leaf module (like
``applicantUpdateView.js``) is — hence the text/regex approach throughout,
matching ``test_enh_uia11y_steps.py`` rather than ``test_applicant_update_js.py``.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore via ``git checkout``) per the batch's test-coverage DoD.
Items intentionally NOT covered here (native chat.js scope, verified
already-correct, or unactioned follow-ups) are 45-47, 51, 57-61, 63-64 —
see the module-level CLAUDE.md batch notes; no fix exists for those in this
pass, so there is nothing to regression-test.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
CHAT_JS = JS_DIR / "applicantChat.js"
MIND_JS = JS_DIR / "applicantMind.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── Double-glass composer flattened (item #46, lower-risk half) ────────────

def test_chat_composer_double_glass_is_flattened():
    """The composer bar (`.chat-input-bar`) inside the chat modal used to carry
    its own frosted-glass layer stacked on top of the modal's own glass. A
    scoped override for `#applicant-chat-modal .chat-input-bar` under both
    glass themes must flatten it (transparent bg, no backdrop-filter, no
    shadow) — verified against style.css, not the JS (the fix lives in CSS)."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"body\.theme-frosted\s+#applicant-chat-modal\s+\.chat-input-bar,\s*"
        r"body\.glass-full\s+#applicant-chat-modal\s+\.chat-input-bar\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected a scoped #applicant-chat-modal .chat-input-bar override in style.css"
    block = m.group(1)
    assert re.search(r"background:\s*transparent\s*!important", block)
    assert re.search(r"backdrop-filter:\s*none\s*!important", block)
    assert re.search(r"box-shadow:\s*none\s*!important", block)


# ── Mind panel initial-focus target fix (tabindex moved to the wrapper) ────

def test_mind_dialog_wrapper_carries_tabindex_not_close_button():
    """`initModalA11y` focuses the first focusable node inside the dialog.
    Without a tabindex on the dialog wrapper itself, that first focusable node
    was the Close button (the first real <button> in the async-loaded
    markup), so opening Mind silently focus-ringed Close. The wrapper
    (`.admin-card[role=dialog]`) must be the first focusable node — i.e. carry
    its own tabindex="0" ahead of the close button in document order."""
    src = _read(MIND_JS)
    dialog_idx = src.index('class="admin-card" role="dialog"')
    close_idx = src.index('applicant-mind-close')
    assert dialog_idx < close_idx, "dialog wrapper markup must precede the close button"
    # tabindex="0" must appear on the dialog wrapper, between the dialog open
    # tag and the close button — not merely somewhere else in the file.
    between = src[dialog_idx:close_idx]
    assert re.search(r'tabindex\s*=\s*"0"', between), (
        "expected tabindex=\"0\" on the dialog wrapper ahead of the close button"
    )


# ── Memory-empty state: italic + alignment styling (Mind-scoped override) ──

def test_mind_memory_empty_state_overrides_italic_and_alignment():
    """The shared `.memory-empty` empty state (native Brain modal + Mind
    panel) is center-aligned italic gray by default, which reads as
    decorative and floats away from a left-aligned section header. The Mind
    panel scopes its own override: `#applicant-mind-modal .memory-empty` must
    set `font-style: normal` and `text-align: left`, without touching the
    native Brain modal's own (unscoped) `.memory-empty` look."""
    css = _read(STYLE_CSS)
    # The base (unscoped) rule stays italic + centered — untouched sibling.
    base = re.search(r"(?<!#applicant-mind-modal )\.memory-empty\s*\{([^}]*)\}", css)
    assert base, "expected the base .memory-empty rule to still exist"
    assert "italic" in base.group(1)
    assert "center" in base.group(1)
    # The Mind-scoped override corrects both facts.
    scoped = re.search(r"#applicant-mind-modal\s+\.memory-empty\s*\{([^}]*)\}", css)
    assert scoped, "expected a #applicant-mind-modal .memory-empty override in style.css"
    scoped_block = scoped.group(1)
    assert re.search(r"font-style:\s*normal", scoped_block)
    assert re.search(r"text-align:\s*left", scoped_block)


# ── Chat bubble tail radius: was 0, now 6px ─────────────────────────────────

def test_chat_bubble_tail_corners_are_not_zero():
    """Item #53: a hard 0px tail corner on `.msg-user` / `.msg-ai` read as a
    clipped-off edge, not a tail. Both bubble corners nearest the sender must
    carry a small non-zero radius (6px) instead of 0."""
    css = _read(STYLE_CSS)

    user_block = re.search(r"\.msg-user\s*\{([^}]*)\}", css)
    assert user_block, "expected a .msg-user rule"
    user_radius = re.search(r"border-radius:\s*([^;]+);", user_block.group(1))
    assert user_radius, ".msg-user must set border-radius"
    user_corners = user_radius.group(1).split()
    assert len(user_corners) == 4, f"expected 4 border-radius values, got {user_corners!r}"
    # bottom-right is the tail corner for a right-aligned (sent) bubble
    assert user_corners[2] == "6px", f".msg-user tail corner must be 6px, got {user_corners!r}"

    ai_block = re.search(r"\.msg-ai\s*\{([^}]*)\}", css)
    assert ai_block, "expected a .msg-ai rule"
    ai_radius = re.search(r"border-radius:\s*([^;]+);", ai_block.group(1))
    assert ai_radius, ".msg-ai must set border-radius"
    ai_corners = ai_radius.group(1).split()
    assert len(ai_corners) == 4, f"expected 4 border-radius values, got {ai_corners!r}"
    # bottom-left is the tail corner for a left-aligned (received) bubble
    assert ai_corners[3] == "6px", f".msg-ai tail corner must be 6px, got {ai_corners!r}"


# ── .msg-ai bubble: fit-content width by default ────────────────────────────

def test_msg_ai_bubble_defaults_to_fit_content_width():
    """Item #54: `.msg-ai` must hug its content (`width: fit-content`) by
    default rather than stretching to the fixed max-width, matching the
    `.msg-user` bubble's behavior for short replies."""
    css = _read(STYLE_CSS)
    ai_block = re.search(r"\.msg-ai\s*\{([^}]*)\}", css)
    assert ai_block, "expected a .msg-ai rule"
    assert re.search(r"width:\s*fit-content\s*;", ai_block.group(1)), (
        ".msg-ai must default to width: fit-content"
    )


# ── Reading-measure caps: 68ch (chat bubbles) / 66ch (Mind panel body) ─────

def test_chat_bubble_body_caps_reading_measure_at_68ch():
    """Item #55: a message bubble's `.body` text must cap at 68ch so a wide
    window can't stretch a reply into an uncomfortable line length."""
    css = _read(STYLE_CSS)
    body_block = re.search(r"\.msg\s+\.body\s*\{([^}]*)\}", css)
    assert body_block, "expected a .msg .body rule"
    assert re.search(r"max-width:\s*68ch\s*;", body_block.group(1))


def test_mind_body_caps_reading_measure_at_66ch():
    """The Mind panel's own body wrapper (`.applicant-mind-body`) caps prose
    at 66ch — the sibling reading-measure fix for the Mind panel."""
    src = _read(MIND_JS)
    assert re.search(r'class="applicant-mind-body"[^>]*max-width:\s*66ch', src), (
        "expected the Mind panel body wrapper to cap at max-width:66ch"
    )


# ── Remaining bare "Loading…" replaced with the shared loadingHTML() ──────

def test_chat_modal_open_uses_shared_loading_helper():
    """Item #56 (recast by the chat-unification pass): the Job Assistant's
    waits must reuse the shared `loadingHTML()` pill (imported from
    applicantCore.js) so they read as work in progress — the job-search bar
    shows it while campaigns load, and the in-thread "thinking" bubble uses
    its labelled form. No bare 'Loading…' text nodes anywhere."""
    src = _read(CHAT_JS)
    assert re.search(r"import\s*\{[^}]*\bloadingHTML\b[^}]*\}\s*from\s*'\./applicantCore\.js'", src), (
        "expected loadingHTML to be imported from the shared applicantCore helper module"
    )
    assert "bar.innerHTML = loadingHTML();" in src, (
        "the job-search bar must show the shared loadingHTML() pill while it resolves"
    )
    assert "loadingHTML('Thinking…')" in src, (
        "the in-thread thinking placeholder must reuse the shared pill"
    )
    # And no bare literal "Loading…" text node anywhere in the module.
    assert ">Loading…<" not in src


# ── Dead-end "no model connected" offline text → actionable CTA ───────────

def test_chat_offline_state_has_actionable_connect_model_cta():
    """Item #52: the offline/not-connected state used to be inert prose
    ("Open Settings -> Connect a model") with no way to act on it. It must
    now render a real primary-button CTA wired to the shared setup launcher
    (`window.launchApplicantSetup`) so there is an actual next step."""
    src = _read(CHAT_JS)
    m = re.search(r"function _renderOffline\(bar\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _renderOffline"
    fn_body = m.group(1)
    assert re.search(r'id="applicant-chat-connect-cta"', fn_body), (
        "expected a connect-a-model CTA button id in _renderOffline"
    )
    assert re.search(r'class="cal-btn cal-btn-primary"[^>]*id="applicant-chat-connect-cta"', fn_body), (
        "the CTA must render as a primary button, not a plain link/text"
    )
    assert "window.launchApplicantSetup" in fn_body, (
        "the CTA must be wired to the shared setup launcher, not dead text"
    )


# ── Duplicate Mind header text removed ──────────────────────────────────────

def test_mind_inner_section_header_is_not_a_duplicate_title():
    """Item #62: the Memory section inside the Mind panel used to repeat the
    dialog's own title ("What the assistant remembers") a second time. Its
    <h4> must now carry its own distinct label ("Memory")."""
    src = _read(MIND_JS)
    templates = re.findall(r"_body\(\)\.innerHTML = `(.*?)`;", src, re.S)
    template = next((t for t in templates if "Saved playbooks" in t), None)
    assert template, "expected to find the openApplicantMind multi-section body-render template"
    # Strip HTML comments (an explanatory dev comment referencing the old
    # duplicate title is expected to remain) before checking rendered text.
    rendered = re.sub(r"<!--.*?-->", "", template, flags=re.S)
    # The dialog's own title lives once, outside this template (in the modal
    # shell markup) — it must not be repeated a second time inside it.
    assert rendered.count("What the assistant remembers") == 0, (
        "the Memory section must not repeat the dialog's own title"
    )
    assert re.search(r"<h4[^>]*>Memory</h4>", rendered), (
        "expected the Memory section to carry its own distinct 'Memory' label"
    )
