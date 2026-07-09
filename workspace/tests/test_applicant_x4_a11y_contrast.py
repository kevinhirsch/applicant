"""X-4 (Accessibility pass) — WCAG-AA contrast sweep across the base theme system.

``test_applicant_theme_contrast_gate.py`` already pins the frosted/glass CHROME
ramp (``body.theme-frosted``) at AA. This file extends the sweep to the base
light/dark theme tokens (``:root`` = dark defaults, ``:root.light`` = the light
theme override) that the golden path (digest -> review -> approve) actually
renders text against, so the toggle in the "recent theme-surface work" the
CLAUDE.md instructions call out doesn't quietly regress one theme while
fixing the other.

Scope, deliberately narrow: the base --fg/--bg/--panel pair (used almost
everywhere as body text), and the two golden-path-specific tokens this pass
introduced (``--redline-add``/``--redline-del``, the review step's fallback
+/- indicators) plus the Portal urgency badges and the new skip-link. This is
NOT a sweep of the entire ~40 semantic tokens in the vendored base stylesheet
(``--color-success``/``--color-warning``/``--color-muted``/etc. as arbitrary
text) — several of those do NOT clear AA as plain text in the light theme
(e.g. ``--color-warning`` text on ``--bg`` is ~1.8:1), but they are vendored,
shared across dozens of non-Applicant surfaces, and retuning them is a
separate, much larger effort explicitly out of this story's surgical scope
(see the X-4 backlog entry in docs/backlog/road-to-market.md for the honest
gap this leaves).

Pure source-text + arithmetic, no browser/DOM — same convention as the
existing gate.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[1]
STYLE_CSS = WORKSPACE / "static" / "style.css"
CSS = STYLE_CSS.read_text(encoding="utf-8")


# ── tiny color math (WCAG 2.x) — mirrors test_applicant_theme_contrast_gate.py ──

def _parse_color(s):
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


def _mix(top, bottom, pct):
    """Composite `top` at `pct` opacity over opaque `bottom` (both (r,g,b[,a]))."""
    return tuple(top[i] * pct + bottom[i] * (1 - pct) for i in range(3)) + (1.0,)


BLACK = (0, 0, 0, 1.0)
WHITE = (255, 255, 255, 1.0)


# ── locate the base :root (dark) and :root.light blocks ─────────────────────

def _root_block(light: bool) -> str:
    """The base `:root { ... }` (dark defaults) or `:root.light { ... }`
    override block. Several OTHER `:root { ... }` blocks exist further down
    the sheet (inside `@media (prefers-*)` accessibility blocks) — identify
    the real theme block by the tokens unique to it (`--redline-add`, which
    X-4 defines only in these two theme blocks)."""
    pattern = r"root\.light \{([^}]*)\}" if light else r"(?<!\.)root \{([^}]*)\}"
    for m in re.finditer(pattern, CSS):
        if "--redline-add" in m.group(1):
            return m.group(1)
    raise AssertionError(
        f"expected a {'`:root.light`' if light else '`:root`'} block defining "
        "--redline-add (the X-4 theme token) — base theme block not found"
    )


def _token(body: str, name: str) -> str:
    m = re.search(rf"{re.escape(name)}:\s*([^;]+);", body)
    assert m, f"expected {name} in the theme block"
    return m.group(1).strip()


# ── base text/surface pairs, both themes ─────────────────────────────────────

def test_base_theme_fg_vs_bg_and_panel_clears_aa_in_both_themes():
    """--fg is the default body text color; --bg/--panel are the two surfaces
    almost every screen (including the whole golden path) paints it over."""
    for light in (False, True):
        body = _root_block(light)
        fg = _parse_color(_token(body, "--fg"))
        bg = _parse_color(_token(body, "--bg"))
        panel = _parse_color(_token(body, "--panel"))
        label = "light" if light else "dark"
        r_bg = _ratio(fg, bg)
        r_panel = _ratio(fg, panel)
        assert r_bg >= 4.5, f"[{label}] --fg vs --bg = {r_bg:.2f}:1 (< 4.5)"
        assert r_panel >= 4.5, f"[{label}] --fg vs --panel = {r_panel:.2f}:1 (< 4.5)"


# ── the redline review step (golden path: review) ────────────────────────────

def test_redline_add_del_tokens_clear_aa_on_the_review_card_surface_both_themes():
    """The daily loop's review step (documentLibrary.js `.doclib-applicant-
    redline` fallback +/- list) paints --redline-add/--redline-del AS TEXT over
    the `.memory-item` card surface: `color-mix(var(--fg) 3%, transparent)`
    composited over `--bg`. The shared --color-success/--color-danger tokens
    do NOT both clear AA here in both themes (danger ~2.4:1 in dark, success
    ~2.4:1 in light) — X-4 introduced dedicated per-theme tokens instead of
    retuning the shared ones (see style.css comments). Pin the fix."""
    # the .memory-item background composition, parsed so a future edit to the
    # mix percentage or base tokens is caught rather than silently drifting.
    m = re.search(
        r"\.memory-item \{[^}]*background:\s*color-mix\(in srgb,\s*var\(--fg\)\s*(\d+)%,\s*transparent\)",
        CSS,
    )
    assert m, "expected .memory-item's color-mix(var(--fg) N%, transparent) background rule"
    fg_pct = int(m.group(1)) / 100.0

    for light in (False, True):
        body = _root_block(light)
        fg = _parse_color(_token(body, "--fg"))
        bg = _parse_color(_token(body, "--bg"))
        card_surface = _mix(fg, bg, fg_pct)
        add = _parse_color(_token(body, "--redline-add"))
        dele = _parse_color(_token(body, "--redline-del"))
        label = "light" if light else "dark"
        r_add = _ratio(add, card_surface)
        r_del = _ratio(dele, card_surface)
        assert r_add >= 4.5, f"[{label}] --redline-add vs review card surface = {r_add:.2f}:1 (< 4.5)"
        assert r_del >= 4.5, f"[{label}] --redline-del vs review card surface = {r_del:.2f}:1 (< 4.5)"


# ── Portal urgency badges (golden path: digest / today) ─────────────────────

def test_portal_urgency_badges_clear_aa():
    """applicantPortal.js `_urgencyBadge` paints fixed-color text (#fff / #000,
    theme-independent) over --color-danger / --color-warning backgrounds —
    pin both at AA (badge text is 10px/600 weight, well under the "large
    text" threshold, so the 4.5:1 floor applies)."""
    js = (WORKSPACE / "static" / "js" / "applicantPortal.js").read_text(encoding="utf-8")
    danger_m = re.search(r"background:var\(--color-danger,(#[0-9a-fA-F]{3,6})\).*?color:(#[0-9a-fA-F]{3,6})", js)
    warn_m = re.search(r"background:var\(--color-warning,(#[0-9a-fA-F]{3,6})\).*?color:(#[0-9a-fA-F]{3,6})", js)
    assert danger_m and warn_m, "expected the Overdue/Due soon urgency badge style strings"

    color_danger = _parse_color(_token(_root_block(False), "--color-danger"))
    color_warning = _parse_color(_token(_root_block(False), "--color-warning"))
    danger_text = _parse_color(danger_m.group(2))
    warn_text = _parse_color(warn_m.group(2))

    r_danger = _ratio(danger_text, color_danger)
    r_warn = _ratio(warn_text, color_warning)
    assert r_danger >= 4.5, f"Overdue badge text vs --color-danger = {r_danger:.2f}:1 (< 4.5)"
    assert r_warn >= 4.5, f"Due soon badge text vs --color-warning = {r_warn:.2f}:1 (< 4.5)"


# ── the new skip-to-content link ─────────────────────────────────────────────

def test_skip_link_clears_aa():
    """The X-4 skip-to-content link (index.html) is the first focusable
    element on the page — it must be legible the instant it appears."""
    m = re.search(r"\.skip-link \{([^}]*)\}", CSS)
    assert m, "expected a .skip-link rule"
    body = m.group(1)
    bg_m = re.search(r"background:\s*var\(--sys-blue,\s*(#[0-9a-fA-F]{6})\)", body)
    color_m = re.search(r"(?<!-)color:\s*(#[0-9a-fA-F]{3,6})", body)
    assert bg_m and color_m, "expected the skip-link's background/color declarations"
    bg = _parse_color(bg_m.group(1))
    fg = _parse_color(color_m.group(1))
    r = _ratio(fg, bg)
    assert r >= 4.5, f"skip-link text vs background = {r:.2f}:1 (< 4.5)"


# ── Denylist hygiene (per the standing white-label instruction) ─────────────
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = Path(__file__).read_text(encoding="utf-8").lower()
    for first, second in _DENYLIST_CODENAME_HALVES:
        assert (first + second) not in text
