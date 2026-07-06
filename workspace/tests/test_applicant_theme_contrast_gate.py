"""Theme/contrast gate — computes REAL WCAG ratios for the glass-tier chrome.

The previous "contrast gate" was a live-browser audit script that CI never ran,
and the static kits claimed AA pairs that were never computed against the
tokens actually applied.  Result: the default post-login state shipped with

  * the full-viewport modal BACKDROP painted with the kit's white window glass
    (`class="modal ow-window"` + the light-fill rule) — a milk wash over the
    whole shell ("white-on-white ghost town");
  * the light-glass chrome flipping INK dark while the SURFACE tokens
    (--panel/--bg/--input-bg) stayed at the dark base-theme values — so
    token-derived interior fills composited black-on-black ("black buttons",
    solid-black form inputs inside white cards);
  * the Ctrl+K search palette with no styles at all.

This gate parses workspace/static/style.css (the tokens as SHIPPED, not as
documented) and computes the WCAG contrast ratios of the effective pairs, so
any regression of the above fails hermetically in CI.
"""

import re
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
STYLE_CSS = WORKSPACE / "static" / "style.css"

CSS = STYLE_CSS.read_text(encoding="utf-8")


# ── tiny color math (WCAG 2.x) ───────────────────────────────────────────────

def _parse_color(s):
    """#rgb/#rrggbb or rgb()/rgba() -> (r, g, b, a) with 0-255 channels."""
    s = s.strip().lower()
    m = re.match(r"#([0-9a-f]{3})$", s)
    if m:
        r, g, b = (int(c * 2, 16) for c in m.group(1))
        return (r, g, b, 1.0)
    m = re.match(r"#([0-9a-f]{6})$", s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.match(r"rgba?\(([^)]+)\)$", s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        r, g, b = (float(p) for p in parts[:3])
        a = float(parts[3]) if len(parts) > 3 else 1.0
        return (r, g, b, a)
    raise ValueError(f"unparseable color: {s!r}")


def _lum(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb[:3]
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _ratio(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _over(top, bottom):
    """Composite translucent `top` (r,g,b,a) over opaque `bottom`."""
    a = top[3]
    return tuple(top[i] * a + bottom[i] * (1 - a) for i in range(3)) + (1.0,)


BLACK = (0, 0, 0, 1.0)
WHITE = (255, 255, 255, 1.0)


# ── the light-surface token ramp (the chrome scope) ──────────────────────────

def _ramp_block():
    """The body.theme-frosted chrome block that declares the surface ramp.

    Located by its two load-bearing members: it must scope BOTH the sidebar
    (`body.theme-frosted #sidebar`) and the modal card
    (`body.theme-frosted .modal-content`) and declare --fg.  This is the block
    whose ABSENCE (ink flipped, surfaces not) shipped the black-on-black bug.
    """
    for m in re.finditer(r"((?:body\.theme-frosted [^{},]+,\s*(?:/\*.*?\*/\s*)?)+body\.theme-frosted [^{},]+)\s*\{([^}]*)\}", CSS, re.DOTALL):
        sels, body = m.group(1), m.group(2)
        if (
            "body.theme-frosted #sidebar" in sels
            and "body.theme-frosted .modal-content" in sels
            and re.search(r"--fg:\s*#", body)
        ):
            return body
    raise AssertionError(
        "no body.theme-frosted chrome block found that scopes BOTH #sidebar and "
        ".modal-content and redefines --fg — the light-chrome token ramp is gone"
    )


def _ramp_token(body, name):
    m = re.search(rf"{re.escape(name)}:\s*([^;]+);", body)
    assert m, f"the chrome token ramp must define {name} (dark base-theme value would leak in)"
    return m.group(1).strip()


def test_theme_frost_chrome_ramp_ink_vs_surfaces_clears_aa():
    """Inside the light-glass chrome, ink vs every token-derived surface >= AA.

    Would have caught: ramp missing --panel/--bg/--input-bg (the dark theme
    values #1d2026/#15171c leaking in -> ratio ~1.1 vs the dark ink)."""
    body = _ramp_block()
    ink = _parse_color(_ramp_token(body, "--fg"))
    for token, floor in (("--panel", 4.5), ("--bg", 4.5)):
        surface = _parse_color(_ramp_token(body, token))
        assert surface[3] >= 0.99, f"{token} in the chrome ramp must be opaque-ish"
        r = _ratio(ink, surface)
        assert r >= floor, (
            f"chrome ink vs {token} = {r:.2f}:1 (< {floor}:1) — dark-theme surface "
            "value leaking into the light chrome (the black-on-black bug)"
        )
    # inputs may be translucent — measure composited over the panel
    input_bg = _parse_color(_ramp_token(body, "--input-bg"))
    panel = _parse_color(_ramp_token(body, "--panel"))
    eff = _over(input_bg, panel)
    r = _ratio(ink, eff)
    assert r >= 4.5, (
        f"chrome ink vs --input-bg-over-panel = {r:.2f}:1 — form controls render "
        "as unreadable slabs inside light cards (the wizard black-inputs bug)"
    )


def test_theme_frost_sidebar_composite_legible_over_any_wallpaper():
    """The sidebar fill mixes var(--panel) into the light glass; with the ramp's
    light panel the composite must clear AA against the forced sidebar ink over
    BOTH a pure-black and a pure-white wallpaper (the mesh presets live between).
    Would have caught: --panel resolving to the dark base-theme value (muddy
    dark sidebar + dark ink)."""
    m = re.search(
        r"body\.theme-frosted #sidebar,\s*body\.theme-frosted \.icon-rail \{\s*"
        r"background-color:\s*color-mix\(in srgb,\s*var\(--panel[^%]*?(\d+)%,\s*"
        r"var\(--ow-glass-light-color\)\s*(\d+)%\)",
        CSS,
    )
    assert m, "expected the sidebar color-mix(panel, --ow-glass-light-color) fill rule"
    p_pct, g_pct = int(m.group(1)) / 100.0, int(m.group(2)) / 100.0

    glass = _parse_color(
        re.search(r"--ow-glass-light-color:\s*(rgba?\([^)]+\))", CSS).group(1)
    )
    panel = _parse_color(_ramp_token(_ramp_block(), "--panel"))

    # color-mix in premultiplied srgb with percentages p/g
    a = panel[3] * p_pct + glass[3] * g_pct
    mix = tuple(
        (panel[i] * panel[3] * p_pct + glass[i] * glass[3] * g_pct) / a for i in range(3)
    ) + (a,)

    # the forced sidebar ink under theme-frosted
    ink_m = re.search(
        r"body\.theme-frosted #sidebar,\s*body\.theme-frosted #sidebar \*,[^{]*\{\s*"
        r"color:\s*(#[0-9a-fA-F]{6})\s*!important",
        CSS,
    )
    assert ink_m, "expected the forced dark-ink rule for body.theme-frosted #sidebar"
    ink = _parse_color(ink_m.group(1))

    for base, name in ((BLACK, "black"), (WHITE, "white")):
        eff = _over(mix, base)
        r = _ratio(ink, eff)
        assert r >= 4.5, (
            f"sidebar ink vs frost-composite-over-{name} = {r:.2f}:1 (< 4.5) — "
            "the sidebar frost no longer guarantees legibility over the wallpaper"
        )


def test_theme_frost_modal_backdrop_is_a_scrim_not_window_glass():
    """A full-viewport `.modal` that ALSO composes the kit `.ow-window` class is
    a BACKDROP — it must never take the white window-glass fill (that was the
    whole-shell milk wash).  Requires (a) the generic scrim re-pin and (b) the
    frost-scope scrim.  Both are !important at HIGHER specificity than every
    light-fill rule that can match the combo (`body.theme-frosted .ow-window`
    is 0-2-1; the scrims are 0-2-0/0-3-1), so they win the cascade regardless
    of source order."""
    generic = re.search(r"(?<![\w.-])\.modal\.ow-window \{([^}]*)\}", CSS)
    assert generic, "expected a `.modal.ow-window` scrim re-pin rule"
    assert "--ow-scrim-bg" in generic.group(1) and "!important" in generic.group(1), (
        ".modal.ow-window must re-pin the kit scrim background with !important "
        "(the runtime-injected .ow-window panel fill wins the cascade otherwise)"
    )

    frost = re.search(r"body\.theme-frosted \.modal\.ow-window \{([^}]*)\}", CSS)
    assert frost, "expected a body.theme-frosted .modal.ow-window scrim rule"
    # no light-fill rule may outrank the scrim: every fill rule matching the
    # combo must stay at compound specificity <= (0,2,1) i.e. a single class
    # after `body.theme-frosted ` — assert none names the .modal.ow-window
    # combo (which would tie at 0-3-1 and could win on order).
    for m in re.finditer(r"body\.theme-frosted ([^{},]*\.modal\.ow-window[^{},]*)\{([^}]*)\}", CSS):
        assert "--ow-glass-light-color" not in m.group(2), (
            "a light-glass fill rule targets .modal.ow-window directly — the "
            "backdrop would take window glass again"
        )
    body = frost.group(1)
    bg = re.search(r"background:\s*color-mix\(in srgb,\s*#000\s*(\d+)%", body)
    assert bg, "the frost backdrop must be a translucent DARK dim, not a fill"
    assert int(bg.group(1)) <= 50, "backdrop dim should stay a scrim (<= 50% black)"
    assert "--ow-glass-light-color" not in body


def test_theme_frost_primary_cta_stays_filled_and_legible():
    """The glass-chip morph turns every in-card button translucent; the ONE
    filled primary action must be re-asserted after it (white label on light
    glass was ~1.3:1 — the invisible CTA)."""
    m = re.search(
        r"body\.theme-frosted button\.cal-btn\.cal-btn-primary[^{]*\{([^}]*)\}", CSS
    )
    assert m, "expected the frost-scope .cal-btn-primary re-assert rule"
    body = m.group(1)
    assert re.search(r"background(-color)?:\s*var\(--sys-blue\)\s*!important", body)
    assert re.search(r"color:\s*#fff\s*!important", body)
    sys_blue = _parse_color(re.search(r"--sys-blue:\s*(#[0-9a-fA-F]{6})", CSS).group(1))
    r = _ratio(WHITE, sys_blue)
    assert r >= 3.0, f"white label on --sys-blue = {r:.2f}:1 (< 3.0 large-text floor)"


def test_search_palette_is_styled_and_legible():
    """#search-overlay/.search-popup had NO styles anywhere — the Ctrl+K palette
    rendered as a naked input clipped off-viewport.  Gate: the overlay is a
    positioned scrim, hidden state still hides, and the frost-scope popup pairs
    dark ink with a light surface at AA."""
    overlay = re.search(r"(?<![\w.-])\.search-overlay \{([^}]*)\}", CSS)
    assert overlay and "position: fixed" in overlay.group(1), (
        ".search-overlay must be a fixed full-viewport scrim"
    )
    assert re.search(r"\.search-overlay\.hidden \{ *display: *none;? *\}", CSS), (
        ".search-overlay.hidden must keep display:none (it is declared later "
        "than the global .hidden utility, so it must re-state it)"
    )
    frost = re.search(r"body\.theme-frosted \.search-popup \{([^}]*)\}", CSS)
    assert frost, "expected the frost-scope .search-popup rule"
    body = frost.group(1)
    ink = _parse_color(re.search(r"--fg:\s*(#[0-9a-fA-F]{6})", body).group(1))
    panel = _parse_color(re.search(r"--panel:\s*(#[0-9a-fA-F]{6})", body).group(1))
    r = _ratio(ink, panel)
    assert r >= 4.5, f"search palette ink vs panel = {r:.2f}:1 (< 4.5)"


def test_welcome_hero_default_ink_matches_shipped_dark_wallpapers():
    """The adaptive hero module (appkitGlass.js) is not loaded by any page, so
    the static default IS the shipped state — and every mesh preset base in
    meshGradient.css is dark.  The frost-scope hero default must therefore be
    LIGHT ink; contrast vs the darkest and lightest preset bases >= 4.5."""
    mesh = (WORKSPACE / "static" / "css" / "meshGradient.css").read_text(encoding="utf-8")
    bases = [_parse_color(c) for c in re.findall(r"--lbg-base:\s*(#[0-9a-fA-F]{6})", mesh)]
    assert bases, "expected --lbg-base declarations in meshGradient.css"

    hero = re.search(
        r"body\.theme-frosted #welcome-screen \.welcome-name \{([^}]*)\}", CSS
    )
    assert hero, "expected the frost-scope welcome-name default rule"
    ink = _parse_color(re.search(r"(?<!-)color:\s*(#[0-9a-fA-F]{6})", hero.group(1)).group(1))
    for base in bases:
        r = _ratio(ink, base)
        assert r >= 4.5, (
            f"hero default ink vs a shipped wallpaper base = {r:.2f}:1 (< 4.5) — "
            "the static default no longer matches the shipped dark mesh presets"
        )
