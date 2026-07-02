"""Regression coverage for docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md's
exhaustive2/03_performance.md lens items #9, #13, and #14, confined entirely to
``workspace/static/style.css`` (no JS/engine changes in this batch).

  #9  Per-bubble backdrop-filter on every chat message. `.msg-ai`/`.msg-user`
      under the frosted glass theme carried their own `blur(22px)
      saturate(...)` backdrop-filter — dozens of independent offscreen
      backdrop composites per scrolled frame on a long transcript. Flattened
      to `backdrop-filter: none` — the bubbles already carry a flat
      translucent `background-color` fill, so the frosted-glass LOOK is kept
      via that tint alone; only the window chrome (`.ow-window`) still
      samples the real backdrop.

  #13 Zero CSS containment anywhere. Added `content-visibility: auto` (+
      `contain-intrinsic-size`) to background/unfocused `.ow-window`
      instances (scoped via the kit's own `.ow-focused` state class so the
      window the user is actually looking at is never affected) and to the
      long scroll-list containers (`.chat-history` transcript, and the
      `.ow-list-row`-based lists in Memory/Tasks (`.memory-list`), Library
      (`.doclib-grid`), Email (`.email-list`), and Debug
      (`.applicant-debug-list`)). Added `contain: layout paint` to the two
      modal-body containment boundaries named by the audit: the base
      `.modal-content` rule and `.ow-window .ow-body`.

  #14 Stacked glass-on-glass backdrop-filter chains. Two concrete,
      provably-always-nested cases were flattened so only the outermost
      surface in the chain still samples the backdrop:
        * `.ow-controls button` (the window traffic-light cluster) — per
          appkitWindow.js it is ONLY ever rendered inside an `.ow-titlebar`
          inside an `.ow-window`, so its own blur(10px) re-sampled a backdrop
          the window (blur(30/22px)) already sampled a layer down. It keeps
          its existing solid `color-mix()` disc fill for its material look.
        * `.admin-card` nested inside an `.ow-window` (Settings/Memory/Tasks/
          etc.) — a NEW scoped override (`.ow-window > .ow-body .admin-card`)
          disables its own blur(22px) without touching the base `.admin-card`
          rule, so a standalone (non-windowed) admin-card elsewhere keeps its
          own blur untouched.
      `.send-btn`/`.odec-confirm`/`.odec-opt`/`.ow-dismiss` were deliberately
      LEFT with their own backdrop-filter — their nesting inside an
      already-glassed surface is not guaranteed (`.ow-dismiss` is explicitly
      documented in appkitWindow.js as also covering non-window dismissible
      strips/banners), so flattening them would risk a surface that floats
      directly over the wallpaper losing its only backdrop sample.

Follows the convention of test_applicant_round1_chatmind.py: every fact is
read from the actual current style.css content via plain regex-over-source-
text — no browser, no DOM. Each assertion here was verified, by hand, to
actually go red when the underlying fix is reverted (revert source -> rerun
-> see the assertion fail -> restore via `git checkout`) before being left in
this final, passing form.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"


def _read() -> str:
    return STYLE_CSS.read_text(encoding="utf-8")


# ── Brace balance sanity (cheap, catches a malformed edit outright) ────────

def test_style_css_braces_are_balanced():
    css = _read()
    assert css.count("{") == css.count("}"), (
        f"style.css brace mismatch: {css.count('{')} open vs {css.count('}')} close"
    )


# ── Item #9: chat bubbles no longer sample the backdrop per-message ────────

def test_msg_ai_bubble_has_no_backdrop_filter():
    css = _read()
    m = re.search(r"body\.theme-frosted \.msg-ai \{([^}]*)\}", css)
    assert m, "expected the body.theme-frosted .msg-ai rule"
    block = m.group(1)
    assert re.search(r"backdrop-filter:\s*none\s*!important", block), (
        ".msg-ai must flatten backdrop-filter to none (item #9)"
    )
    assert re.search(r"-webkit-backdrop-filter:\s*none\s*!important", block)
    # the flat translucent fill that keeps the glass LOOK must still be there
    assert re.search(r"background-color:\s*rgba\(56,60,68,var\(--ai-scrim-alpha", block), (
        ".msg-ai must keep its flat rgba() tint fill as the (now sole) glass look"
    )


def test_msg_user_bubble_has_no_backdrop_filter():
    css = _read()
    m = re.search(r"body\.theme-frosted \.msg-user \{([^}]*)\}", css)
    assert m, "expected the body.theme-frosted .msg-user rule"
    block = m.group(1)
    assert re.search(r"backdrop-filter:\s*none\s*!important", block), (
        ".msg-user must flatten backdrop-filter to none (item #9)"
    )
    assert re.search(r"-webkit-backdrop-filter:\s*none\s*!important", block)
    assert re.search(r"background-color:\s*rgba\(10,132,255,0\.80\)", block), (
        ".msg-user must keep its flat system-blue rgba() tint fill"
    )


def test_msg_bubbles_no_longer_reference_blur_in_theme_frosted_rule():
    """Belt-and-braces: neither bubble rule's OWN block should mention blur()
    any more (the backdrop-filter properties are what carried it)."""
    css = _read()
    for selector in (r"\.msg-ai", r"\.msg-user"):
        m = re.search(rf"body\.theme-frosted {selector} \{{([^}}]*)\}}", css)
        assert m, f"expected the rule for {selector}"
        assert "blur(" not in m.group(1), f"{selector} must not blur its own backdrop"


# ── Item #14: nested glass-on-glass chains flattened ────────────────────────

def test_ow_controls_button_excluded_from_shared_btn_glass_group():
    """`.ow-controls button` must NOT be part of the shared backdrop-sampling
    selector group (`.send-btn`/`.odec-confirm`/`.odec-opt`/`.ow-dismiss`) any
    more — it always lives inside an already-glassed `.ow-window`."""
    css = _read()
    m = re.search(
        r"body\.theme-frosted \.send-btn,\s*"
        r"body\.theme-frosted \.odec-confirm,\s*"
        r"body\.theme-frosted \.odec-opt,\s*"
        r"body\.theme-frosted \.ow-dismiss \{([^}]*)\}",
        css,
    )
    assert m, "expected the trimmed send-btn/odec-confirm/odec-opt/ow-dismiss group"
    block = m.group(1)
    assert re.search(r"backdrop-filter:\s*var\(--ow-btn-glass\)", block), (
        "the remaining group members must keep their own backdrop sample"
    )
    # and .ow-controls button must not appear anywhere in that selector list
    assert ".ow-controls button" not in m.group(0)


def test_ow_controls_button_has_no_backdrop_filter_declaration():
    """`.ow-controls button` gets its own dedicated rule (for the shared
    transition) but must carry no backdrop-filter declaration anywhere in the
    frosted theme — it rides the window's own blur one layer down."""
    css = _read()
    # every body.theme-frosted rule whose selector list includes exactly
    # ".ow-controls button" (not a compound like ".ow-window .ow-body .ow-controls button")
    for m in re.finditer(r"body\.theme-frosted ([^{]*)\{([^}]*)\}", css):
        selectors = m.group(1)
        if re.search(r"(^|,\s*)\.ow-controls button(\s*,|\s*$)", selectors.strip()):
            block = m.group(2)
            assert "backdrop-filter" not in block, (
                f".ow-controls button rule must not set backdrop-filter, got: {selectors!r}"
            )


def test_admin_card_nested_in_window_has_backdrop_filter_flattened():
    css = _read()
    m = re.search(
        r"body\.theme-frosted \.ow-window > \.ow-body \.admin-card \{([^}]*)\}",
        css,
    )
    assert m, "expected a scoped .ow-window > .ow-body .admin-card override"
    block = m.group(1)
    assert re.search(r"backdrop-filter:\s*none\s*!important", block)
    assert re.search(r"-webkit-backdrop-filter:\s*none\s*!important", block)


def test_standalone_admin_card_backdrop_filter_is_untouched():
    """The base (non-nested) .admin-card rule must still carry its own real
    blur — only the window-nested case was flattened. Scans every rule block
    (not just the first '.admin-card' hit, which belongs to an unrelated
    popover-tint group) for the one whose selector list names `.admin-card`
    directly (not via `.ow-window > .ow-body`) and whose body sets the shared
    chrome backdrop token."""
    css = _read()
    found = False
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = m.group(1), m.group(2)
        if (
            ".admin-card" in selectors
            and "var(--ow-glass-backdrop)" in body
            and ".ow-window >" not in selectors
        ):
            found = True
            break
    assert found, (
        "expected the base (non-nested) chrome-surfaces group to still set "
        "backdrop-filter: var(--ow-glass-backdrop) for .admin-card"
    )


# ── Item #13: CSS containment ───────────────────────────────────────────────

def test_unfocused_windows_get_content_visibility_auto():
    css = _read()
    m = re.search(r"\.ow-window:not\(\.ow-focused\) \{([^}]*)\}", css)
    assert m, "expected a .ow-window:not(.ow-focused) containment rule"
    block = m.group(1)
    assert re.search(r"content-visibility:\s*auto", block)
    assert re.search(r"contain-intrinsic-size:\s*\S+", block)


def test_content_visibility_is_only_ever_declared_twice_and_both_scoped():
    """`content-visibility: auto;` as an actual declaration (not a comment
    mention) must appear in exactly the two rules this batch added: the
    `:not(.ow-focused)` window rule and the long-list-container rule. In
    particular it must never land on a bare, unconditional `.ow-window { }`
    rule (which would also skip rendering for the currently-focused window
    the user is looking at — the scroll-anchoring/measurement risk the audit
    calls out)."""
    css = _read()
    declarations = list(re.finditer(r"content-visibility:\s*auto;", css))
    assert len(declarations) == 2, (
        f"expected exactly 2 content-visibility declarations, found {len(declarations)}"
    )
    # a bare, unconditional ".ow-window {" rule (line-anchored so it can't
    # match ".ow-window:not(.ow-focused) {" or a compound/nested selector)
    # must never exist in the file at all.
    assert not re.search(r"^[ \t]*\.ow-window \{", css, re.MULTILINE), (
        "content-visibility must not be reachable via a bare, unconditional "
        ".ow-window rule"
    )


def test_long_scroll_list_containers_get_content_visibility_auto():
    css = _read()
    m = re.search(
        r"\.chat-history,\s*"
        r"\.memory-list,\s*"
        r"\.doclib-grid,\s*"
        r"\.email-list,\s*"
        r"\.applicant-debug-list \{([^}]*)\}",
        css,
    )
    assert m, (
        "expected a shared content-visibility rule for the chat transcript + "
        "the .ow-list-row-based Memory/Tasks/Library/Email/Debug list containers"
    )
    block = m.group(1)
    assert re.search(r"content-visibility:\s*auto", block)
    assert re.search(r"contain-intrinsic-size:\s*\S+", block)


def test_modal_content_base_rule_has_layout_paint_containment():
    css = _read()
    # anchored to line-start (with only leading whitespace) so this can't
    # accidentally match an id-scoped variant like "#foo .modal-content {"
    m = re.search(r"^[ \t]*\.modal-content \{([^}]*)\}", css, re.MULTILINE)
    assert m, "expected the base .modal-content rule"
    assert re.search(r"contain:\s*layout paint", m.group(1)), (
        ".modal-content must carry `contain: layout paint` (item #13)"
    )


def test_ow_window_ow_body_scroll_rule_has_layout_paint_containment():
    css = _read()
    m = re.search(r"^[ \t]*\.ow-window \.ow-body \{([^}]*)\}", css, re.MULTILINE)
    assert m, "expected the .ow-window .ow-body scrollbar-gutter rule"
    assert re.search(r"contain:\s*layout paint", m.group(1)), (
        ".ow-window .ow-body must carry `contain: layout paint` (item #13)"
    )
