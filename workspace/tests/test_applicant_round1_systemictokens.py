"""Regression coverage for the §A "systemic tokens + glass mechanics" design-audit
fix batch, items 1, 2, 7-24 (per docs/design/audits/APPLE_GENIUS_IMPROVEMENTS.md),
confined to ``workspace/static/js/theme.js``, ``workspace/static/js/appkitGlass.js``,
``workspace/static/style.css`` and ``workspace/static/index.html``.

Follows the convention of ``tests/bdd/steps/test_enh_uia11y_steps.py`` /
``workspace/tests/test_applicant_round1_calendar.py``: every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no real
socket. theme.js/appkitGlass.js run module-level DOM-touching init code on import
(the auto ``_initWithSync()`` call, the SVG host bootstrap) and pull in sibling
DOM-coupled modules (login_bg.js, colorPicker.js, ...), so — like the calendar/
onboarding/portal siblings in this same round-1 batch — they are exercised as
*source text* with brace-balanced function-body extraction, not executed under
node. Balanced-brace extraction (not a naive ``[^}]*``) is used wherever the target
function contains its own nested ``if``/blocks, so the assertions inspect the real
function body, not a truncated prefix.

Each assertion here was verified, by hand, against the actual pre-fix blob for its
introducing commit (``git show <rev>^:<path>``) to confirm it goes red on the old
code and green on the current tree, per the batch's test-coverage DoD:
  - items 1, 2 (theme.js/style.css glass-tier split-gate + house-theme rename):
    pre-image at ``6a682df^``
  - item 7 (mesh preset picker, theme.js/index.html): pre-image at ``6a682df^``
  - item 9 (adaptive backdrop samples mesh pseudo-elements, appkitGlass.js):
    pre-image at ``6a682df^``
  - item 10 (.hamburger-btn:focus-visible, style.css): pre-image at ``6a682df^``
  - item 11 (appkitGlass.js SVG-lens RADIUS 18->22): pre-image at ``f34cc35^``
  - items 12, 13, 18, 23 (--tap-min / --dur-* / --ease-standard / --text-* /
    --icon-* tokens, style.css): pre-image at ``d45e08a^``
  - item 14 (mesh-gradient animate gated on prefers-reduced-motion, theme.js) and
    item 15 (applyGlassMeshTuning + Settings sliders, theme.js/index.html):
    pre-image at ``fd769bf^`` (theme.js) / ``bf87265^`` (index.html sliders)

Out of scope (per the batch brief): items 8, 16, 20-22, 24 (confirmed already-
correct elsewhere, no new fix landed) and 17, 19 (explicitly skipped, no fix
exists) get no coverage here.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
THEME_JS = JS_DIR / "theme.js"
APPKIT_GLASS_JS = JS_DIR / "appkitGlass.js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_balanced(src: str, signature_regex: str) -> str:
    """Find `signature_regex` (must end just before the opening `{`) and return
    the BRACE-BALANCED body between `{` and its matching `}` — safe for function
    bodies that contain their own nested `if (...) { ... }` blocks, unlike a
    naive `\\{([^}]*)\\}` which stops at the first inner closing brace."""
    m = re.search(signature_regex, src)
    assert m, f"expected to find signature: {signature_regex}"
    start = m.end() - 1
    assert src[start] == "{", f"signature regex must end right before '{{': {signature_regex}"
    depth = 0
    for i in range(start, len(src)):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start + 1 : i]
    raise AssertionError(f"unbalanced braces extracting: {signature_regex}")


def _root_block(css: str) -> str:
    m = re.search(r":root\s*\{(.*?)\n\}", css, re.DOTALL)
    assert m, "expected a :root { ... } block in style.css"
    return m.group(1)


# ── #1: applyFrostedGlass delegates entirely through applyGlassTier ────────────

def test_apply_frosted_glass_delegates_through_apply_glass_tier():
    """applyFrostedGlass used to write `body.theme-frosted` independently via its
    own classList.toggle — now it is a thin re-router: it reads the CURRENT
    `glass-full` state and calls applyGlassTier(...), which is the SOLE writer of
    both `theme-frosted` and `glass-full`. This closes the split-gate bug where
    glass-full could stay set while theme-frosted got cleared (refraction with no
    frost fill underneath)."""
    src = _read(THEME_JS)
    body = _extract_balanced(src, r"export function applyFrostedGlass\(on\) \{")
    assert re.search(r"applyGlassTier\(", body), (
        "applyFrostedGlass must delegate through applyGlassTier(...)"
    )
    # Must NOT independently write theme-frosted (that would reintroduce the
    # split-gate bug even though applyGlassTier is also called).
    assert not re.search(r"classList\.(toggle|add|remove)\(\s*['\"]theme-frosted['\"]", body), (
        "applyFrostedGlass must not touch the theme-frosted class directly; "
        f"body was: {body!r}"
    )
    # The vestigial house-theme class-write must be gone too.
    assert "house-theme" not in body


# ── #2: house-theme fully renamed to theme-frosted (zero occurrences) ──────────

def test_house_theme_codename_is_fully_renamed():
    """Every `house-theme` class reference was renamed to `theme-frosted` across
    theme.js, appkitGlass.js, style.css and index.html — zero occurrences of the
    old class name should remain in any of the four in-scope files."""
    for path in (THEME_JS, APPKIT_GLASS_JS, STYLE_CSS, INDEX_HTML):
        src = _read(path)
        assert "house-theme" not in src, f"stale house-theme reference in {path}"
    # And the replacement class is actually in active use (not just absent-absent).
    assert "theme-frosted" in _read(THEME_JS)
    assert "theme-frosted" in _read(STYLE_CSS)


# ── #7: mesh wallpaper preset is a real picker, not hard-pinned to 'aurora' ────

def test_mesh_preset_is_a_real_picker_not_hard_pinned():
    """The in-app glass wallpaper's mesh preset used to be a hard literal
    ('aurora') in the mountMeshGradient() call inside ensureGlassWallpaper. Now
    there's an exported MESH_PRESETS catalog + applyGlassMeshPreset() setter, the
    mount call reads the live _glassMeshPreset variable, and Settings exposes a
    matching <select> the user can actually change."""
    src = _read(THEME_JS)
    m = re.search(
        r"export const MESH_PRESETS\s*=\s*\[([^\]]*)\]",
        src,
    )
    assert m, "expected an exported MESH_PRESETS array"
    presets = [p.strip().strip("'\"") for p in m.group(1).split(",")]
    assert presets == ["sunset", "aurora", "ocean", "gold", "lavender"], presets

    assert re.search(r"export function applyGlassMeshPreset\(preset\)", src), (
        "expected an exported applyGlassMeshPreset(preset) setter"
    )

    wallpaper_body = _extract_balanced(src, r"function ensureGlassWallpaper\(on\) \{")
    assert "preset: _glassMeshPreset" in wallpaper_body, (
        "ensureGlassWallpaper's mountMeshGradient(...) call must read the live "
        "_glassMeshPreset variable"
    )
    assert "preset: 'aurora'" not in wallpaper_body, (
        "the mesh preset must no longer be hard-pinned to the 'aurora' literal"
    )

    # And Settings actually exposes a picker with the same catalog.
    html = _read(INDEX_HTML)
    select_m = re.search(
        r'<select id="theme-mesh-preset-select"[^>]*>(.*?)</select>', html, re.DOTALL
    )
    assert select_m, "expected a #theme-mesh-preset-select <select> in index.html"
    option_values = set(re.findall(r'<option value="([^"]+)"', select_m.group(1)))
    assert option_values == {"aurora", "sunset", "ocean", "gold", "lavender"}


# ── #9: adaptive backdrop sampler reads the mesh gradient's pseudo-elements ────

def test_adaptive_backdrop_samples_mesh_gradient_pseudo_elements():
    """buildBackdrop()'s adaptive color sampler used to read only #__wp's flat,
    mirrored base color. The mesh wallpaper actually paints its color LOBES on
    the .login-bg-gradient element's ::before/::after pseudo-elements (CSS can't
    be read via getComputedStyle(el) — only getComputedStyle(el, pseudo)), so the
    sampler now explicitly samples those two pseudo-elements too."""
    src = _read(APPKIT_GLASS_JS)
    body = _extract_balanced(src, r"function buildBackdrop\(\) \{")
    assert ".login-bg-gradient" in body, "expected the mesh gradient selector to be sampled"
    assert "::before" in body and "::after" in body, (
        "expected both pseudo-elements to be sampled"
    )
    assert re.search(r"getComputedStyle\(\s*meshEl\s*,\s*pseudo\s*\)", body), (
        "expected a getComputedStyle(meshEl, pseudo) call sampling the pseudo-elements"
    )


# ── #10: .hamburger-btn gets a real :focus-visible ring ─────────────────────────

def test_hamburger_btn_has_focus_visible_ring():
    """.hamburger-btn set `outline: none` unconditionally with no replacement,
    so keyboard focus had no visible indicator at all. A :focus-visible rule now
    restores a real ring."""
    css = _read(STYLE_CSS)
    m = re.search(r"\.hamburger-btn:focus-visible\s*\{([^}]*)\}", css)
    assert m, "expected a .hamburger-btn:focus-visible rule in style.css"
    rule = m.group(1)
    assert re.search(r"outline:\s*2px\s+solid\s+var\(--sys-blue\)", rule), rule
    assert re.search(r"outline-offset:\s*2px", rule), rule


# ── #11: appkitGlass.js SVG-lens RADIUS synced to --ow-glass-radius (documented
#         proportional undershoot — 22, not an exact match to the 26px CSS var) ──

def test_svg_lens_radius_synced_to_26px_glass_radius():
    """RADIUS (the corner radius the SVG-refraction squircle profile is built
    around) was stale at 18 against style.css's --ow-glass-radius, which was
    bumped to 26px. It's now 22 — deliberately still under 26 (a documented
    proportional undershoot so the lens band sits inside the visible corner),
    so this pins the exact expected value rather than equality with the CSS
    var."""
    src = _read(APPKIT_GLASS_JS)
    m = re.search(r"var RADIUS\s*=\s*(\d+);", src)
    assert m, "expected a `var RADIUS = <n>;` declaration"
    assert m.group(1) == "22", f"expected RADIUS to be 22, got {m.group(1)}"
    # And the CSS var it tracks is documented at 26px (sanity: the two must
    # differ, or the "proportional undershoot" comment above is a lie).
    css = _read(STYLE_CSS)
    assert "--ow-glass-radius: 26px;" in css


# ── #12: --tap-min: 44px is a real token, not just a var() fallback ────────────

def test_tap_min_token_is_defined():
    """--tap-min was referenced everywhere as `var(--tap-min, 44px)` with no real
    token behind the fallback. It's now defined for real in :root."""
    root = _root_block(_read(STYLE_CSS))
    assert re.search(r"--tap-min:\s*44px;", root), (
        "expected --tap-min: 44px; defined in :root"
    )


# ── #13: motion tokens (--dur-fast/-base/-slow, --ease-standard) are defined ───

def test_motion_tokens_are_defined():
    """Durations/easing were ad-hoc literals scattered through the sheet with no
    named tokens. :root now defines the tokenized ramp with the documented
    values."""
    root = _root_block(_read(STYLE_CSS))
    assert re.search(r"--dur-fast:\s*0\.08s;", root), "missing --dur-fast: 0.08s;"
    assert re.search(r"--dur-base:\s*0\.2s;", root), "missing --dur-base: 0.2s;"
    assert re.search(r"--dur-slow:\s*0\.3s;", root), "missing --dur-slow: 0.3s;"
    assert re.search(
        r"--ease-standard:\s*cubic-bezier\(0\.4,\s*0,\s*0\.2,\s*1\);", root
    ), "missing --ease-standard: cubic-bezier(0.4, 0, 0.2, 1);"


# ── #14: mesh-gradient animation is gated on prefers-reduced-motion ────────────

def test_mesh_gradient_animate_gated_on_reduced_motion():
    """ensureGlassWallpaper's mountMeshGradient(...) call used to always pass
    `animate: true`, relying entirely on a CSS !important override to actually
    stop the motion under prefers-reduced-motion. mountMeshGradient's own
    contract is that the CALL SITE must respect the media query — so it's now
    gated with `animate: !prefersReducedMotion()`, sourced from login_bg.js."""
    src = _read(THEME_JS)
    assert re.search(
        r"import\s*\{\s*mountMeshGradient\s*,\s*prefersReducedMotion\s*\}\s*from\s*['\"]\./login_bg\.js['\"]",
        src,
    ), "expected theme.js to import prefersReducedMotion alongside mountMeshGradient"

    body = _extract_balanced(src, r"function ensureGlassWallpaper\(on\) \{")
    assert "animate: !prefersReducedMotion()" in body, (
        "expected the mount call to gate animate on !prefersReducedMotion()"
    )
    assert "animate: true" not in body, (
        "animate must no longer be unconditionally true"
    )


# ── #15: applyGlassMeshTuning + two Settings sliders (speed/intensity) ─────────

def test_mesh_tuning_function_and_sliders_exist():
    """The in-app wallpaper's drift speed/intensity were hard-pinned (34s/0.5),
    unlike the login screen's admin-exposed knobs. applyGlassMeshTuning(speed,
    intensity) now clamps and applies both live, and Settings exposes two
    matching range sliders."""
    src = _read(THEME_JS)
    body = _extract_balanced(
        src, r"export function applyGlassMeshTuning\(speed, intensity\) \{"
    )
    assert re.search(r"Math\.max\(8,\s*Math\.min\(60,", body), (
        "expected speed to be clamped to [8, 60]"
    )
    assert re.search(r"Math\.max\(0\.4,\s*Math\.min\(1\.4,", body), (
        "expected intensity to be clamped to [0.4, 1.4]"
    )

    html = _read(INDEX_HTML)
    speed_m = re.search(r'<input type="range" id="theme-mesh-speed"[^>]*>', html)
    intensity_m = re.search(r'<input type="range" id="theme-mesh-intensity"[^>]*>', html)
    assert speed_m, "expected a #theme-mesh-speed range slider in index.html"
    assert intensity_m, "expected a #theme-mesh-intensity range slider in index.html"


# ── #18: wordmark SVG's dead empty <path> cleaned up + aria-hidden; icon tokens ─

def test_wordmark_svg_cleaned_up_and_icon_tokens_defined():
    """The welcome-hero wordmark SVG carried a dead, empty `<path d="">` (a
    leftover stroke path with no data — renders nothing) and no aria-hidden, so
    screen readers announced a purely decorative graphic. Both are fixed:
    the empty path is gone and the SVG is aria-hidden. A --icon-size/--icon-
    stroke token pair is also defined for future icon work."""
    html = _read(INDEX_HTML)
    m = re.search(r'<svg class="welcome-boat"[^>]*>.*?</svg>', html, re.DOTALL)
    assert m, "expected the .welcome-boat wordmark SVG in index.html"
    svg_markup = m.group(0)
    assert 'aria-hidden="true"' in svg_markup, "wordmark SVG must be aria-hidden"
    assert not re.search(r'<path\s+d=""', svg_markup), (
        f"wordmark SVG still has a dead empty <path d=\"\">: {svg_markup!r}"
    )

    root = _root_block(_read(STYLE_CSS))
    assert re.search(r"--icon-size:\s*1\.25rem;", root), "missing --icon-size: 1.25rem;"
    assert re.search(r"--icon-stroke:\s*2;", root), "missing --icon-stroke: 2;"


# ── #23: --text-large-title/-title/-body/-caption ramp with exact rem values ───

def test_text_scale_tokens_have_exact_values():
    """Heading sizes were ad-hoc literals with no named ramp. :root now defines
    the general-purpose chrome type scale with these exact values."""
    root = _root_block(_read(STYLE_CSS))
    expected = {
        "--text-large-title": "1.75rem",
        "--text-title": "1.25rem",
        "--text-body": "0.875rem",
        "--text-caption": "0.75rem",
    }
    for name, value in expected.items():
        pattern = re.escape(name) + r":\s*" + re.escape(value) + r";"
        assert re.search(pattern, root), f"expected {name}: {value}; in :root"
