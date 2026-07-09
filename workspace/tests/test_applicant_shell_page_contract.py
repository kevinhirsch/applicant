"""P0-3 shell / page view-contract — the window-manager retirement gate.

This is the positive contract that REPLACES the retired floating-window /
modal-stack primitive. P0-3 turned the product surface into a fixed 3-pane
shell — ``sidebar | permanent chat center | #applicant-gadget-rail`` — where
every former floating window is now reachable either as a rail gadget or as a
full hash-routed page.

What "retired" means here (and what this file pins): the floating-window /
modal-stack primitive is the AppKit window kit ``static/js/appkitWindow.js``
(the ``AppkitWindow`` class, the ``AppkitSlots`` z-anchor engine, the
``_modalStack`` push/pop, the ``.ow-scrim`` dim, the ``nextWindowZ`` band
authority, minimize/restore-to-dock, ``dismissTop``/``stackIds``) and its sole
dependency ``windowResize.js``. That kit is RETIRED FROM THE ACTIVE PRODUCT
SURFACE — it is not imported by any wired module, not loaded by any
``<script>`` tag, and has no external runtime call site — so the shell never
constructs a floating window. The kit file itself is deliberately LEFT IN TREE
as a dormant vendored asset (it is the FR-UIKIT/T13 "Window kit"; its existence
is a hard regression gate in ``tests/bdd/.../uikit_registry.py``), so this
contract pins the primitive's ABSENCE FROM THE SURFACE (unwired) rather than
the file's deletion — retiring a primitive from the product surface is about
what the surface loads and runs, not about deleting a vendored file.

The four halves of the DoD this pins:
  1. login lands in the 3-pane shell;
  2. the rail is a STATIC flex sibling (no scrim / focus-trap / window-manager
     of its own);
  3. each gadget expands to its full page via the SAME existing
     ``window.openApplicant*`` launcher (a hash-routed ``.modal`` page, never a
     floating window);
  4. NO floating-window primitive is wired into the default surface.

It also pins the ``hashRouter.js`` "one surface at a time" arbiter that took
over the window-stack's job: navigating to a new surface CLOSES the previously
active one (surfaces never stack), while the native chat pane is the persistent
backdrop that neither closes nor is closed.

Coverage here is strictly ADDITIVE to ``test_applicant_shell_gadget_rail.py``
(the rail half) and does not weaken the live ``ui.js`` ``initModalA11y``
Escape-arbiter coverage in ``test_applicant_round1_remainder_modalstack.py`` —
that helper is the shared DIALOG a11y trap (styledConfirm / the routed pages),
not the retired floating-window kit, and stays.

Each assertion was hand-verified to go RED when the piece it protects is
reverted (e.g. re-adding an ``import`` of appkitWindow.js into a wired module,
or wiring a ``window.AppkitWindowKit.create(...)`` call site), then restored to
GREEN.
"""

from __future__ import annotations

import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_INDEX_HTML = _REPO / "static" / "index.html"
_STYLE_CSS = _REPO / "static" / "style.css"
_APP_JS = _REPO / "static" / "app.js"  # the orchestrator lives at static/app.js, not static/js/
_RAIL_JS = _JS_DIR / "applicantRail.js"
_HASHROUTER_JS = _JS_DIR / "hashRouter.js"

# The floating-window / modal-stack kit files (dormant vendored assets; must be
# unwired from the active product surface).
_RETIRED_FILES = ("appkitWindow.js", "windowResize.js")

# Launcher modules whose full-page surfaces the gadgets expand into.
_LAUNCHER_FILES = ("applicantTracker.js", "applicantToday.js", "applicantResults.js")


@pytest.fixture(scope="module")
def index_src() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_src() -> str:
    return _APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rail_src() -> str:
    return _RAIL_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def router_src() -> str:
    return _HASHROUTER_JS.read_text(encoding="utf-8")


def _all_shipped_js() -> list[pathlib.Path]:
    """Every shipped, surface-loadable JS file: the ``static/app.js`` entrypoint
    (loaded LAST by ``index.html`` — the shell orchestrator, one level ABOVE
    ``static/js/``) plus every module under ``static/js/`` at ANY depth
    (``editor/``, ``research/``, ``compare/``, … are all shipped and reachable).
    Scanning the full recursive surface — not just top-level ``static/js/*.js`` —
    is what makes the retirement guards below actually cover the entrypoint and
    any nested module an equivalent import could hide in."""
    files = list(_JS_DIR.rglob("*.js"))
    app_entry = _REPO / "static" / "app.js"
    if app_entry.exists():
        files.append(app_entry)
    return sorted(files)


def _wired_surface_js() -> list[pathlib.Path]:
    """Every shipped JS file EXCEPT the retired kit itself. Asserting over this
    set proves the kit is not wired into any OTHER (surface) module — the kit
    defining its own class/globals internally is not a surface wiring."""
    retired = set(_RETIRED_FILES)
    return [p for p in _all_shipped_js() if p.name not in retired]


# ── 1. Login lands in the 3-pane shell ─────────────────────────────────────

def test_shell_has_three_static_panes_in_order(index_src: str) -> None:
    """The authenticated surface (index.html) is the fixed 3-pane shell laid
    out left→center→right as static flex siblings: sidebar, the permanent chat
    center, then the gadget rail."""
    assert 'id="sidebar"' in index_src, "left pane: the nav sidebar"
    assert 'id="chat-container"' in index_src, "center pane: the permanent chat surface"
    assert 'id="applicant-gadget-rail"' in index_src, "right pane: the gadget rail"

    sidebar = index_src.index('id="sidebar"')
    chat = index_src.index('id="chat-container"')
    rail = index_src.index('id="applicant-gadget-rail"')
    assert sidebar < chat < rail, "panes must be ordered sidebar | chat | rail"


def test_chat_center_is_the_permanent_pane_and_rail_is_its_sibling(index_src: str) -> None:
    """The chat center is a real <main> region and the rail sits AFTER </main>
    as a sibling — the rail is not nested inside the chat pane, and neither is a
    floating window over the other."""
    assert re.search(r"<main[^>]*id=\"chat-container\"", index_src), "chat center is a <main> region"
    main_close = index_src.index("</main>")
    rail = index_src.index('id="applicant-gadget-rail"')
    assert rail > main_close, "the rail is a sibling AFTER </main>, not nested inside the chat pane"
    # It is a landmark <aside>, not a modal/window overlay.
    assert re.search(r"<aside[^>]*id=\"applicant-gadget-rail\"", index_src), "rail is an <aside> landmark"


def test_shell_loads_the_rail_module_as_es_module(index_src: str) -> None:
    assert re.search(
        r"<script[^>]*type=\"module\"[^>]*src=\"/static/js/applicantRail\.js\"", index_src
    ), "the rail module must load as an ES module in the shell"


def test_boot_lands_on_the_home_base_within_the_shell_not_a_floating_window(app_src: str) -> None:
    """After setup completes, boot lands the user on the Pending/Today home
    base rendered INSIDE the shell (openApplicantPortal), then seeds the
    one-surface view tracker and starts hash routing — no floating window is
    spawned on landing."""
    assert "openApplicantPortal({ skipHashUpdate: true })" in app_src, (
        "boot lands on the Portal/Today home base (a shell surface), not a window"
    )
    assert "setActive('portal')" in app_src, "boot seeds the one-surface view tracker"
    assert "initHashRouting()" in app_src, "boot starts the page/view router"
    # The landing must not construct a floating-window surface.
    assert "AppkitWindowKit.create" not in app_src and "new AppkitWindow" not in app_src


# ── 2. The rail is a static flex sibling (no window-manager of its own) ─────

def test_rail_is_a_landmark_column_not_a_floating_window(rail_src: str) -> None:
    """The rail owns only its own #applicant-gadget-rail mount as a
    complementary landmark. It spawns NO floating-window / modal-stack
    machinery: no ow-window/ow-scrim, no .modal scaffold, no focus-trap of its
    own, no window-manager kit, no z-band."""
    assert "role', 'complementary'" in rail_src or 'role="complementary"' in rail_src, (
        "the rail mounts as a complementary landmark column"
    )
    for banned in (
        "ow-window",
        "ow-scrim",
        'class="modal',
        "initModalA11y",   # the rail is a persistent pane, not a trapped modal
        "AppkitWindow",
        "nextWindowZ",
        "position: fixed",
        "position:fixed",
    ):
        assert banned not in rail_src, f"the rail must not use the retired window primitive ({banned!r})"


def test_rail_reserves_a_column_in_css_not_a_floating_overlay() -> None:
    css = _STYLE_CSS.read_text(encoding="utf-8")
    assert ".applicant-gadget-rail" in css, "the rail must reserve a layout column via CSS"


# ── 3. Each gadget expands to its full PAGE via the existing launcher ───────

def test_gadgets_expand_via_existing_window_launchers(rail_src: str) -> None:
    """One click opens the matching full page through the SAME launcher the
    page module already exports — never a floating/modal-stack window."""
    for launcher in (
        "window.openApplicantTracker",
        "window.openApplicantToday",
        "window.openApplicantResults",
        "window.applicantActivityModule",
    ):
        assert launcher in rail_src, f"gadget must reuse the existing {launcher} launcher"


def test_launchers_open_hash_routed_pages_not_windows() -> None:
    """The launcher surfaces are full-view .modal PAGES (built via
    _ensureModalEl + display:flex) — they never construct the floating-window
    kit."""
    for name in _LAUNCHER_FILES:
        src = (_JS_DIR / name).read_text(encoding="utf-8")
        assert "_ensureModalEl()" in src, f"{name} opens a full-view page via _ensureModalEl"
        # None of the page modules construct a floating-window surface.
        assert "new AppkitWindow" not in src, f"{name} must not spawn a floating window"
        assert "AppkitWindowKit.create" not in src, f"{name} must not spawn a floating window"
        assert "AppkitSlots.register" not in src, f"{name} must not use the retired slot engine"
    # Today + Results additionally register a URL-addressable route (page view).
    for name in ("applicantToday.js", "applicantResults.js"):
        src = (_JS_DIR / name).read_text(encoding="utf-8")
        assert "registerRoute(" in src, f"{name} registers a hash-routed page view"


# ── 4. No floating-window primitive is wired into the default surface ──────

@pytest.mark.parametrize("fname", _RETIRED_FILES)
def test_no_wired_module_imports_the_retired_kit(fname: str) -> None:
    """The floating-window kit is unwired from the surface: no shipped surface
    module imports OR re-exports appkitWindow.js / windowResize.js — static
    (``from '…'``), side-effect (``import '…';``), dynamic (``import('…')``), or
    re-export barrel (``export * from '…'`` / ``export { X } from '…'``, which is
    also a module dependency that loads the kit). Match is quote-agnostic (``'…'``
    OR ``"…"``) and relative-path-agnostic (``./``, ``../js/``, ``./editor/…``
    etc.), keyed on the module *filename*, so an equivalent-but-differently-
    spelled reintroduction can't slip past. The kit's own internal import of
    windowResize.js from appkitWindow.js does not count — appkitWindow.js is
    itself retired (excluded from the surface set), and neither is loaded because
    nothing imports appkitWindow.js. Comment lines are skipped so prose that
    merely names the historical kit does not trip this."""
    # Either an `import …` (static / side-effect / dynamic) OR an
    # `export … from …` re-export, ending in a quoted specifier whose path ends
    # in <fname>, in either quote style and with any relative prefix. Covers
    # `import X from "./appkitWindow.js"`, `import './js/appkitWindow.js'`,
    # `import("../appkitWindow.js")`, and `export * from './appkitWindow.js'`.
    dep_re = re.compile(
        r"""(?:import\b[^\n;]*?|export\b[^\n;]*?\bfrom\s*)['"][^'"]*"""
        + re.escape(fname)
        + r"""['"]"""
    )
    for path in _wired_surface_js():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(("//", "*", "/*")):
                continue  # comment prose naming the kit is not a wiring
            m = dep_re.search(line)
            assert m is None, (
                f"{path.name}:{lineno} still imports/re-exports the retired {fname} "
                f"(matched: {m.group(0)!r})"
            )


@pytest.mark.parametrize("fname", _RETIRED_FILES)
def test_no_script_tag_loads_the_retired_kit(index_src: str, fname: str) -> None:
    assert f"/static/js/{fname}" not in index_src, (
        f"index.html must not load the retired {fname}"
    )


def test_no_wired_surface_calls_into_the_retired_window_manager() -> None:
    """No wired surface module may call into the floating-window kit. These are
    RUNTIME patterns (constructor / factory / kit-method calls), so lingering
    comment prose that merely names the historical kit does not trip this — but
    any real use of it does. The kit's own file is excluded (it DEFINES these);
    the point is that nothing on the active surface INVOKES them."""
    banned_runtime = (
        "new AppkitWindow(",
        "AppkitWindowKit.create(",
        "AppkitSlots.register(",
        "_appkitSeedLayout(",
        "_appkitApplyRemoteLayout(",
    )
    offenders: list[str] = []
    for path in _wired_surface_js():
        src = path.read_text(encoding="utf-8")
        for pat in banned_runtime:
            if pat in src:
                offenders.append(f"{path.name}: {pat}")
    assert not offenders, f"retired floating-window kit still invoked on the surface: {offenders}"


# ── 5. The page/view arbiter that replaced the window stack ─────────────────

def test_router_closes_the_previous_surface_instead_of_stacking(router_src: str) -> None:
    """hashRouter.js is the one-surface-at-a-time arbiter that took over the
    window stack's job: a real surface→surface navigation closes the
    previously active surface first, so surfaces never stack."""
    assert "registerRoute" in router_src, "surfaces register an open/close page view"
    assert "const crossNav" in router_src, "the router detects a real surface→surface transition"
    assert re.search(r"if \(crossNav\)", router_src), "cross-navigation is handled explicitly"
    # On cross-navigation it closes the previously-active surface.
    assert "prev.close()" in router_src, "navigating to a new surface closes the previous one"


def test_native_chat_is_the_persistent_backdrop(router_src: str) -> None:
    """The permanent chat center pane never stacks under or over another
    surface: 'chat' is exempt in BOTH directions — opening chat never closes
    the active surface, and chat never becomes the active surface that gets
    closed."""
    assert "token !== 'chat'" in router_src, "opening chat never closes the active surface"
    assert "_activeToken !== 'chat'" in router_src, "chat is never the active surface that gets closed"
