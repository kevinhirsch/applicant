"""Regression coverage for the three §B "Shell / Sidebar / Portal" design-audit
items that were explicitly SKIPPED by every round-1 batch (per docs/design/audits/
APPLE_GENIUS_IMPROVEMENTS.md) because they touch shared shell chrome — the sidebar
glass material, the composer's icon cluster, and the chat-title wordmark — rather
than any single applicant-owned surface. Closed out here, confined to
``workspace/static/style.css`` (read-only reference to ``workspace/static/
index.html`` for markup; no HTML/JS changes were needed).

Follows the convention of ``workspace/tests/test_applicant_round1_systemictokens.py``:
every fact is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket.

Items covered:
  - #31 (major): sidebar glass material read as light glass over a dark desktop,
    inverted vs. the reference's darker/more-opaque sidebar. Fixed with a
    token-based override (mixes in ``--panel``/``--bg``) scoped to `#sidebar` /
    `.icon-rail`, layered after the shared kube-white fill so it wins at equal
    specificity.
  - #40 (minor): composer traded the reference's single attach control for a
    loose chevron+search+terminal icon row. Full functional merge would require
    JS rewiring (moving the web-search/shell-access toggles into the overflow
    menu) — out of scope for a CSS-only pass, so this is the safe visual-only
    consolidation: the icon row now hugs its own content and shares one grouped
    pill surface instead of stretching across the bar as loose chips. No click
    handlers changed.
  - #41 (minor): the chat-title "Applicant" wordmark relied on a low color-mix
    alpha with no explicit font-weight (ghosted, thin). Floored at font-weight
    500 with a higher alpha floor instead of leaning on opacity.

Each assertion was verified by hand against the pre-fix blob (this file's own
introducing commit) to confirm it goes red on the old code and green on the
current tree.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _slice_after(src: str, marker: str, length: int = 2500) -> str:
    """Return `length` chars of `src` starting at `marker` — a small window used
    to scope a regex search near a specific, uniquely-named fix comment instead
    of matching anywhere in a 36k-line stylesheet."""
    assert marker in src, f"expected to find marker {marker!r} in style.css"
    idx = src.index(marker)
    return src[idx : idx + length]


# ── #31: sidebar glass material reconciled (darker/more-opaque than the shared
#        light-glass fill, via existing --panel/--bg tokens, not a hand-rolled
#        color) ────────────────────────────────────────────────────────────────

def test_sidebar_glass_overridden_darker_than_shared_light_fill():
    css = _read(STYLE_CSS)
    window = _slice_after(css, "ITEM #31")

    # The override rule targets #sidebar + .icon-rail specifically (not every
    # glass surface — windows/toasts/popovers keep the original bright fill).
    assert re.search(
        r"body\.theme-frosted #sidebar,\s*\n\s*body\.theme-frosted \.icon-rail\s*\{",
        window,
    ), "expected a dedicated body.theme-frosted #sidebar/.icon-rail override rule"

    # It mixes in the theme's own (adaptive dark/light) panel tone rather than
    # painting the bare bright kube-white fill straight.
    assert re.search(
        r"background-color:\s*color-mix\(in srgb,\s*var\(--panel,\s*var\(--bg\)\)\s*55%,"
        r"\s*var\(--ow-glass-light-color\)\s*45%\)\s*!important;",
        window,
    ), "expected the sidebar fill to mix in var(--panel, var(--bg)), not a hand-rolled color"

    # And it drops the extra white top-down lift image that would otherwise wash
    # the mixed-in dark tone back toward white.
    assert re.search(r"background-image:\s*none\s*!important;", window), (
        "expected the sidebar's light-lift background-image to be dropped"
    )

    # Sanity: the override must appear strictly AFTER the shared light-glass fill
    # block (`--ow-glass-light-color) !important` painted onto #sidebar) so it
    # wins at equal specificity by source order — not before it.
    shared_fill_idx = css.index("body.theme-frosted .admin-card,")
    override_idx = css.index("ITEM #31")
    assert override_idx > shared_fill_idx, (
        "the #31 override must come after the shared light-glass fill block so "
        "it wins the cascade"
    )


def test_sidebar_override_still_wrapped_in_reduced_transparency_guard():
    """The override must stay inside `@media (prefers-reduced-transparency:
    no-preference)` — unconditionally applying it would fight the a11y solid
    fallback that forces #sidebar to a plain opaque panel under Reduce
    Transparency."""
    css = _read(STYLE_CSS)
    window = _slice_after(css, "ITEM #31", length=2500)
    media_idx = window.index("@media (prefers-reduced-transparency: no-preference)")
    rule_idx = window.index("body.theme-frosted #sidebar,\n  body.theme-frosted .icon-rail {")
    assert media_idx < rule_idx, (
        "the #31 sidebar override must be nested inside the no-preference guard"
    )


# ── #40: composer icon cluster visually consolidated into one grouped pill ─────

def test_composer_icon_row_hugs_content_instead_of_stretching():
    css = _read(STYLE_CSS)
    m = re.search(r"\.chat-input-left \{([^}]*)\}", css, re.DOTALL)
    assert m, "expected a .chat-input-left rule in style.css"
    body = m.group(1)
    assert re.search(r"flex:\s*0 1 auto;", body), (
        "expected .chat-input-left to hug its content (flex: 0 1 auto) instead "
        "of stretching to fill the bar (the old flex: 1)"
    )
    assert "flex: 1;" not in body, ".chat-input-left must no longer stretch full-width"


def test_composer_icon_row_shares_one_grouped_pill_surface():
    css = _read(STYLE_CSS)
    m = re.search(r"\.chat-input-left \{([^}]*)\}", css, re.DOTALL)
    assert m, "expected a .chat-input-left rule in style.css"
    body = m.group(1)
    assert re.search(r"background:\s*color-mix\(in srgb,\s*var\(--fg\)\s*6%,\s*transparent\);", body), (
        "expected the icon row to carry one shared grouped-pill background"
    )
    assert re.search(r"border-radius:\s*10px;", body), (
        "expected the icon row's grouped pill to have a border-radius"
    )


def test_composer_toggle_buttons_still_present_and_functional_in_markup():
    """The safe CSS-only consolidation must NOT remove or hide any control —
    the attach/overflow trigger, web-search toggle and shell-access toggle all
    stay in the DOM, visible, with their existing ids/handlers untouched."""
    html = _read(INDEX_HTML)
    for btn_id in ("overflow-plus-btn", "web-toggle-btn", "bash-toggle-btn"):
        assert f'id="{btn_id}"' in html, f"expected #{btn_id} to still exist in index.html"
    # None of them were hidden via an inline style or a `hidden` attribute.
    for btn_id in ("overflow-plus-btn", "web-toggle-btn", "bash-toggle-btn"):
        m = re.search(rf'<button[^>]*id="{btn_id}"[^>]*>', html)
        assert m, f"expected a <button id=\"{btn_id}\"> tag"
        tag = m.group(0)
        assert "display:none" not in tag and "display: none" not in tag, (
            f"#{btn_id} must not be hidden — item #40 preserves reachability"
        )
        assert " hidden" not in tag, f"#{btn_id} must not carry the hidden attribute"


# ── #41: chat-title wordmark floored at font-weight 500, not opacity-carried ───

def test_chat_meta_wordmark_has_weight_floor():
    css = _read(STYLE_CSS)
    m = re.search(r"\.chat-meta-overlay \{([^}]*)\}", css, re.DOTALL)
    assert m, "expected a .chat-meta-overlay rule in style.css"
    body = m.group(1)
    assert re.search(r"font-weight:\s*500;", body), (
        "expected .chat-meta-overlay to floor font-weight at 500 (Medium)"
    )


def test_chat_meta_wordmark_does_not_lean_on_low_opacity():
    css = _read(STYLE_CSS)
    m = re.search(r"\.chat-meta-overlay \{([^}]*)\}", css, re.DOTALL)
    assert m, "expected a .chat-meta-overlay rule in style.css"
    body = m.group(1)
    # The old resting color-mix alpha was 58% — too low to read as present over
    # a dark desktop. It must be raised well above that floor.
    color_m = re.search(r"color:\s*color-mix\(in srgb,\s*var\(--fg\)\s*(\d+)%,\s*transparent\);", body)
    assert color_m, "expected .chat-meta-overlay's resting color to be a color-mix(var(--fg) N%, transparent)"
    alpha = int(color_m.group(1))
    assert alpha >= 80, f"resting alpha must be raised well above the old 58% floor, got {alpha}%"

    hover_m = re.search(r"\.chat-meta-overlay:hover \{([^}]*)\}", css, re.DOTALL)
    assert hover_m, "expected a .chat-meta-overlay:hover rule in style.css"
    hover_body = hover_m.group(1)
    # Hover should read as fully present (solid var(--fg)), not another
    # partial-opacity mix.
    assert re.search(r"color:\s*var\(--fg\);", hover_body), (
        "expected .chat-meta-overlay:hover to use the solid var(--fg), not a "
        "further color-mix alpha trick"
    )
