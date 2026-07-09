"""Surface-consistency gate — every chrome surface flips cleanly between the
light and dark themes, and same-class surfaces share one colour.

The workspace shipped with an ad-hoc surface palette: windows, menus and cards
each reached for either ``var(--panel)`` OR ``var(--bg)`` by author whim.  On
the DARK theme those two tokens are different colours (``--panel`` #111 vs
``--bg`` #282c34), and on the LIGHT theme too (#fff vs #f5f5f5) — so a document
library window (``--bg``) rendered a visibly different colour from a settings
window (``--panel``): light surfaces beside dark surfaces on the same theme.

The fix is a named elevation ramp (``--surface-base/-raised/-overlay/-inset``)
in ``:root`` that aliases the theme-flipping ``--panel``/``--bg`` tokens, plus a
migration of the stray surfaces onto it.  This gate pins that contract so a new
window/menu/card can't quietly re-introduce the split:

* the ramp exists in ``:root`` and every tier aliases a token that ``:root.light``
  actually redefines (so the surface flips with the theme);
* every WINDOW body (``.modal-content`` family) that paints a solid fill uses the
  RAISED tier — never ``--bg`` (the inset tier) or a raw theme-flippable hex;
* every floating MENU/dropdown/popover that paints a solid fill uses the RAISED
  or OVERLAY tier — never ``--bg`` or a raw hex;
* no window/menu/card/sidebar/pane selector hardcodes a light-or-dark hex fill
  (which would stay one colour while the theme flipped around it).

It parses the SHIPPED ``static/style.css`` + ``static/index.html`` (tokens as
served, not as documented), so any regression fails hermetically in CI.
"""

import re
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
CSS = (WORKSPACE / "static" / "style.css").read_text(encoding="utf-8")
INDEX = (WORKSPACE / "static" / "index.html").read_text(encoding="utf-8")


# ── rule iteration ───────────────────────────────────────────────────────────

def _rules():
    """Yield (selector, body) for every top-level CSS rule (declarations only —
    nested @media blocks surface their inner rules too since the regex matches
    the innermost brace pairs)."""
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        yield m.group(1).strip(), m.group(2)


def _fill(body):
    """The solid background FILL of a rule, or None. Returns the raw value for
    the last ``background``/``background-color`` declaration; skips rules with
    no background decl."""
    val = None
    for m in re.finditer(r"background(?:-color)?\s*:\s*([^;]+);", body):
        val = m.group(1).strip()
    return val


def _leaf(sel):
    """The final compound of a selector — the element the rule actually paints.
    ``.modal-content .grab-handle`` → ``.grab-handle`` (a child, not the window),
    so ancestor-scoped child rules don't get mistaken for the surface itself."""
    # drop leading comments, collapse combinators to spaces, take the last token
    sel = re.sub(r"/\*.*?\*/", " ", sel, flags=re.DOTALL)
    sel = re.sub(r"\s*[>+~]\s*", " ", sel).strip()
    return sel.split()[-1] if sel.split() else sel


def _is_form_control(leaf):
    return bool(re.search(r"\binput\b|\btextarea\b|\bselect\b|\[type=", leaf))


def _primary_token(val):
    """The leading token of a fill value, normalized: strips ``!important`` and
    reads only the FIRST token of a ``var(--x, fallback)`` (the fallback never
    paints when --x is defined, which it always is). ``var(--panel, var(--bg))``
    → ``--panel``. Returns None for non-var fills."""
    val = val.replace("!important", "").strip()
    m = re.match(r"var\(\s*(--[\w-]+)", val)
    return m.group(1) if m else None


RAISED_TOKENS = {"--surface-raised", "--panel"}
OVERLAY_TOKENS = {"--surface-overlay", "--surface-raised", "--panel"}


# A theme-flippable literal colour (the thing that must NOT be hardcoded on a
# surface): white-ish or near-black hexes. Translucent rgba() scrims/tints and
# gradients are allowed (they composite over whatever token surface is behind).
_FLIPPABLE_HEX = re.compile(
    r"#(?:fff(?:fff)?|f[0-9a-f]f[0-9a-f]f[0-9a-f]|eaeaea|eee(?:eee)?|fafafa|fcfcfc"
    r"|000(?:000)?|111(?:111)?|1[0-9a-f]{5}|22[0-9a-f]{3}|282c34|1d2026)\b",
    re.I,
)

def _is_scrim_or_tint(val):
    """A fill that legitimately isn't a flat surface token: a translucent scrim,
    a color-mix/gradient tint, or a non-colour keyword. These sit OVER a surface
    and are theme-agnostic by construction, so they're out of scope."""
    low = val.lower()
    if low.split()[0] in ("transparent", "none", "inherit", "initial", "unset", "currentcolor"):
        return True
    if "color-mix" in low or "gradient" in low:
        return True
    # translucent rgba/hsla (alpha < 1) is a scrim/veil, not a surface fill
    m = re.search(r"(?:rgba|hsla)\([^)]*,\s*(0?\.\d+|0)\s*\)", low)
    if m:
        return True
    return False


def _theme_scoped(sel):
    s = sel.lower()
    return "theme-frosted" in s or "house-theme" in s or s.startswith(":root")


# ── the ramp contract ────────────────────────────────────────────────────────

def test_surface_ramp_is_defined_and_flips_with_the_theme():
    """``:root`` defines the four surface tiers, each aliases --panel or --bg,
    and ``:root.light`` redefines both underlying tokens so the aliases flip."""
    root = re.search(r":root\s*\{(.*?)\n\}", CSS, re.DOTALL)
    assert root, "no :root block"
    root_body = root.group(1)
    tiers = {}
    for tier in ("base", "raised", "overlay", "inset"):
        m = re.search(rf"--surface-{tier}\s*:\s*([^;]+);", root_body)
        assert m, f"--surface-{tier} must be defined in :root (the elevation ramp)"
        tiers[tier] = m.group(1).strip()
        assert tiers[tier] in ("var(--panel)", "var(--bg)"), (
            f"--surface-{tier} must alias --panel or --bg (a theme-flipping token), "
            f"got {tiers[tier]!r} — a raw value would not flip between themes"
        )
    # raised must be a raised token, inset the canvas token (elevation intact)
    assert tiers["raised"] == "var(--panel)"
    assert tiers["inset"] == "var(--bg)"

    light = re.search(r":root\.light\s*\{(.*?)\n\}", CSS, re.DOTALL)
    assert light, "no :root.light block"
    for tok in ("--panel", "--bg"):
        assert re.search(rf"{tok}\s*:\s*#", light.group(1)), (
            f":root.light must redefine {tok} — otherwise surfaces aliasing it "
            "would not flip on the light theme"
        )


# ── window / menu family consistency ─────────────────────────────────────────

def test_every_window_body_uses_the_raised_surface_tier():
    """Every ``.modal-content`` window body that paints a solid fill uses the
    RAISED tier — the doclib/tasks/cookbook/group-picker windows used to grab
    ``--bg`` and read a different colour from every other window."""
    offenders = []
    for sel, body in _rules():
        if _theme_scoped(sel):
            continue
        # only the window BODY itself — leaf compound ends in *modal-content
        if not _leaf(sel).endswith("modal-content"):
            continue
        val = _fill(body)
        if val is None or _is_scrim_or_tint(val):
            continue
        if _primary_token(val) not in RAISED_TOKENS:
            offenders.append((sel[:60], val))
    assert not offenders, (
        "window bodies must fill with the raised surface tier "
        f"(var(--surface-raised) / var(--panel)); off-tier fills: {offenders}"
    )


def test_floating_menus_use_the_overlay_tier():
    """Dropdowns / overflow menus / popovers that paint a solid fill use the
    overlay (or raised) tier — never ``--bg`` or a raw hex. The email/langpicker/
    reminder menus used to sit on ``--bg`` while every other menu used --panel."""
    menu_sel = re.compile(
        r"\.(?:[\w-]*dropdown|[\w-]*-menu|[\w-]*popover|overflow-menu|"
        r"[\w-]*suggest|[\w-]*autocomplete|"
        r"model-picker-menu|note-reminder-menu|email-more-menu)\b"
    )
    offenders = []
    for sel, body in _rules():
        if _theme_scoped(sel):
            continue
        leaf = _leaf(sel)
        # the menu SURFACE itself (leaf is the menu), not a child/control/state
        if not menu_sel.search(leaf) or _is_form_control(leaf):
            continue
        if re.search(r":hover|:focus|:active|divider|::", leaf):
            continue
        val = _fill(body)
        if val is None or _is_scrim_or_tint(val):
            continue
        if _primary_token(val) not in OVERLAY_TOKENS:
            offenders.append((sel[:60], val))
    assert not offenders, (
        "floating menus must fill with the overlay/raised surface tier; "
        f"off-tier fills: {offenders}"
    )


def test_no_chrome_surface_hardcodes_a_theme_flippable_hex():
    """No window/menu/card/sidebar/pane selector paints a solid raw light-or-dark
    hex — that colour would stay fixed while the theme flipped around it. Scrims,
    tints, gradients and media overlays are exempt (they composite over a token
    surface). Regression backstop for the whole chrome layer."""
    chrome = re.compile(
        r"modal-content|\.ow-window|#sidebar\b|\.sidebar\b|icon-rail(?![\w])|"
        r"[\w-]*-pane\b|admin-card|cookbook-card|task-preset-card|"
        r"[\w-]*dropdown|[\w-]*-menu\b|popover"
    )
    # media-overlay / control selectors that legitimately sit on top of images
    exempt = re.compile(
        r"gallery|-play\b|-fav\b|-dl\b|-nav\b|-rotate|lightbox|canvas|preview|"
        r"checkbox|::after|::before|:hover|:focus|:active|backdrop|scrim|-input\b|"
        r"stoplight|scrollbar"
    )
    offenders = []
    for sel, body in _rules():
        if _theme_scoped(sel) or not chrome.search(sel) or exempt.search(sel):
            continue
        val = _fill(body)
        if val is None or _is_scrim_or_tint(val):
            continue
        if "var(" not in val and _FLIPPABLE_HEX.search(val):
            offenders.append((sel[:60], val))
    assert not offenders, (
        "chrome surfaces must derive their fill from a surface token, not a raw "
        f"theme-flippable hex: {offenders}"
    )


def test_cookbook_window_inline_fill_uses_the_ramp():
    """The Cookbook window sets its ``.modal-content`` fill inline in index.html;
    it must use the ramp (not raw ``--bg``) so it matches every other window."""
    m = re.search(r'id="cookbook-modal".*?<div class="modal-content"[^>]*style="([^"]*)"',
                  INDEX, re.DOTALL)
    assert m, "cookbook-modal .modal-content inline style not found"
    style = m.group(1)
    bg = re.search(r"background\s*:\s*([^;\"]+)", style)
    assert bg, "cookbook modal-content should declare a background inline"
    assert bg.group(1).strip() == "var(--surface-raised)", (
        f"cookbook window inline fill must be var(--surface-raised), got {bg.group(1)!r} "
        "— a raw --bg leaves it a different colour from every other window"
    )
