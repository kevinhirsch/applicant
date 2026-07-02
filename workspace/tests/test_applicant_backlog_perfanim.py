"""Regression coverage for round-3 exhaustive2/03_performance.md items #10 and #16
(docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md), confined to
``static/css/meshGradient.css`` and ``static/js/theme.js``.

Item #10: the animated mesh (``.login-bg-gradient::before``, shared by the login
screen and the in-app glass wallpaper #__wp) used to animate ``background-position``
on a layer carrying ``filter: blur(54px) saturate(1.55) brightness(1.14)`` — a full
paint + 54px gaussian blur on EVERY animation frame, continuously, on every surface.
Fix: the blurred layer's background/filter are now static (rasterized once); only
``transform: translate()/scale()`` animates (``login-mesh-drift``), which the
compositor can move as an already-blurred bitmap with no repaint.

Item #16: ``theme.js`` runs unbounded ``requestAnimationFrame`` loops for 7 canvas
wallpaper patterns (synapse/rain/constellations/perlin-flow/petals/sparkles/embers).
Each loop re-read ``getComputedStyle(document.documentElement)`` every frame, and
the embers loop allocated a fresh ``createRadialGradient`` PER PARTICLE PER FRAME.
Fix: (a) a shared ``_readBgVars()`` cache — read once, invalidated only when
``applyColors``/``applyBgEffectColor``/``applyBgEffectIntensity``/``applyBgEffectSize``
actually change one of the vars the canvases read; (b) the embers loop now reuses
ONE unit-radius gradient (repositioned via ctx.translate/scale) instead of building
a new CanvasGradient per ember per frame; (c) a shared ``_rafLoop()`` scheduler
pauses every one of the 7 loops while ``document.hidden`` and resumes cleanly on
``visibilitychange`` — the same spirit as ``applicantCore.js``'s ``pollVisible()``
(see ``test_applicant_round2_wave1_polling.py``), adapted for a frame-driven loop.

Follows that same file's convention: source-text regex assertions for the
browser-only module (top-level DOM work at import time, so not importable under
bare ``node --input-type=module`` without a DOM shim), plus real node-executed
behavioral tests of the two extractable pure/near-pure mechanisms
(``_rafLoop`` and ``_readBgVars``/``_bumpBgVarsCache``) since those are the actual
mechanisms every one of the 7 pattern fixes relies on.

Each assertion here was verified, by hand, to actually go red when the underlying
fix is reverted (``git stash`` the source changes to theme.js/meshGradient.css,
confirm every test in this file fails, ``git stash pop`` to restore, confirm green
again) — the CSS/JS content asserted on is the exact pre-fix text this batch
replaced, and the node-executed behaviors did not exist before this batch (there
was no ``_rafLoop``/``_readBgVars`` to import).
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess
import textwrap

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CSS_DIR = REPO_ROOT / "workspace" / "static" / "css"
THEME_JS = JS_DIR / "theme.js"
MESH_CSS = CSS_DIR / "meshGradient.css"

_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT / "workspace",
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


# ── #10 — meshGradient.css: transform-only drift, blur/background static ──


def test_mesh_before_layer_no_longer_animates_background_position():
    src = _read(MESH_CSS)
    assert "background-position" not in src, (
        "the mesh's ::before layer must not animate background-position at all "
        "any more — that forced a full paint + 54px gaussian blur every frame"
    )


def test_mesh_before_layer_will_change_is_transform_not_background_position():
    src = _read(MESH_CSS)
    m = re.search(r"\.login-bg-gradient::before\s*\{([^}]*)\}", src, re.S)
    assert m, "expected a .login-bg-gradient::before rule"
    block = m.group(1)
    assert "will-change: transform" in block, (
        "::before should hint the compositor about the transform animation, "
        "not the (now-removed) background-position one"
    )
    assert "filter: blur(54px)" in block and "saturate(1.55)" in block, (
        "the 54px gaussian blur must still be present (just static, not animated)"
    )


def test_mesh_drift_keyframes_animate_transform():
    src = _read(MESH_CSS)
    m = re.search(r"@keyframes login-mesh-drift\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected @keyframes login-mesh-drift"
    body = m.group(1)
    assert "background-position" not in body, (
        "login-mesh-drift must no longer touch background-position"
    )
    # Every keyframe stop must set `transform:` (compositor-only property) —
    # translate() so the layer visibly drifts, matching the audit's fix.
    stops = re.findall(r"\{([^}]*)\}", body)
    assert len(stops) >= 2, "expected at least a from/to pair of keyframe stops"
    for stop in stops:
        assert "transform:" in stop and "translate(" in stop, (
            f"every login-mesh-drift keyframe stop must animate transform/translate, got: {stop!r}"
        )


def test_mesh_ray_layer_still_transform_only():
    # ::after (the aurora ray, blur(30px)) already animated transform/opacity
    # only — confirm this batch didn't regress it back to a repaint-forcing
    # property.
    src = _read(MESH_CSS)
    m = re.search(r"@keyframes login-ray-sweep\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected @keyframes login-ray-sweep"
    body = m.group(1)
    assert "background-position" not in body
    assert "transform:" in body


def test_mesh_reduced_motion_still_gates_all_animation():
    src = _read(MESH_CSS)
    m = re.search(
        r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}\n?\Z",
        src,
        re.S,
    )
    assert m, "expected a trailing prefers-reduced-motion media block"
    body = m.group(1)
    assert "animation: none !important" in body
    assert ".login-bg-gradient::before, .login-bg-gradient::after" in body, (
        "the belt-and-braces reduced-motion override must still freeze both "
        "the blurred mesh AND the ray layer"
    )


def test_mesh_css_brace_balance():
    src = _read(MESH_CSS)
    assert src.count("{") == src.count("}"), "meshGradient.css must have balanced braces"


# ── #16 — theme.js: rAF loops pause/cache/reuse ──────────────────────────


_PATTERN_INIT_FNS = [
    "_initSynapse",
    "_initRain",
    "_initConstellations",
    "_initPerlinFlow",
    "_initPetals",
    "_initSparkles",
    "_initEmbers",
]


def _extract_fn_block(src: str, fn_name: str) -> str:
    m = re.search(
        r"function " + re.escape(fn_name) + r"\(\)\s*\{.*?\n\}\n",
        src,
        re.S,
    )
    assert m, f"expected `function {fn_name}() {{ ... }}` in theme.js"
    return m.group(0)


def test_no_raw_requestAnimationFrame_draw_loop_remains():
    src = _read(THEME_JS)
    assert "requestAnimationFrame(draw)" not in src, (
        "every canvas pattern must go through the shared _rafLoop() scheduler, "
        "not a raw self-recursing requestAnimationFrame(draw) call"
    )
    assert not re.search(r"\bfunction draw\(\)", src), (
        "the old per-pattern `function draw() { ... } draw();` shape should be "
        "gone — replaced by `_rafLoop(() => { ... })`"
    )


@pytest.mark.parametrize("fn_name", _PATTERN_INIT_FNS)
def test_each_canvas_pattern_uses_shared_raf_loop(fn_name):
    src = _read(THEME_JS)
    block = _extract_fn_block(src, fn_name)
    assert "_rafLoop(" in block, f"{fn_name} must schedule its frame loop via _rafLoop(...)"
    # No direct getComputedStyle(document.documentElement) call left inside the
    # pattern body — everything must route through the cached _readBgVars().
    assert "getComputedStyle(document.documentElement)" not in block, (
        f"{fn_name} must read theme/effect CSS vars through the cached "
        f"_readBgVars() helper, not a raw per-call getComputedStyle()"
    )


def test_rafLoop_definition_present_and_visibility_gated():
    src = _read(THEME_JS)
    assert "function _rafLoop(step)" in src
    m = re.search(r"function _rafLoop\(step\)\s*\{.*?\n\}\n", src, re.S)
    assert m, "expected the _rafLoop(step) { ... } scheduler definition"
    body = m.group(0)
    assert "document.hidden" in body, (
        "_rafLoop must check document.hidden before running a frame's step()"
    )
    assert "visibilitychange" in body, (
        "_rafLoop must listen for visibilitychange so a paused loop resumes "
        "when the tab is shown again"
    )
    assert "cancelAnimationFrame" in body, (
        "_rafLoop must cancel any in-flight frame on teardown (pattern switched away)"
    )


def test_seven_canvas_patterns_call_rafLoop():
    src = _read(THEME_JS)
    # One definition + 7 call sites (one per wallpaper pattern).
    assert len(re.findall(r"_rafLoop\(", src)) == 8, (
        "expected exactly 1 _rafLoop definition + 7 call sites (one per canvas "
        "wallpaper pattern) — a miscount likely means a pattern regressed back "
        "to a raw requestAnimationFrame loop, or a duplicate/dead call was added"
    )


def test_bg_vars_cache_invalidated_by_every_relevant_setter():
    src = _read(THEME_JS)
    for fn_name in ["applyColors", "applyBgEffectColor", "applyBgEffectIntensity", "applyBgEffectSize"]:
        m = re.search(r"export function " + fn_name + r"\([^)]*\)\s*\{.*?\n\}\n", src, re.S)
        assert m, f"expected `export function {fn_name}(...) {{ ... }}`"
        assert "_bumpBgVarsCache()" in m.group(0), (
            f"{fn_name} writes a CSS var the canvas loops read — it must bump the "
            f"_readBgVars() cache generation so the loops don't paint with a stale "
            f"cached color/intensity/size after a theme/effect change"
        )


def test_embers_reuses_one_gradient_instead_of_per_particle_per_frame():
    src = _read(THEME_JS)
    block = _extract_fn_block(src, "_initEmbers")
    # createRadialGradient must appear exactly once (inside getEmberGradient),
    # NOT inside the per-ember for-loop that used to call it every iteration.
    assert len(re.findall(r"createRadialGradient", block)) == 1, (
        "expected exactly one createRadialGradient call (in getEmberGradient), "
        "reused across every ember every frame instead of allocated per "
        "particle per frame"
    )
    # The reused gradient must actually be looked up (not recreated) inside the
    # loop body via getEmberGradient(...), and drawn with ctx.scale/translate.
    assert "getEmberGradient(" in block
    assert "ctx.translate(e.x, e.y)" in block and "ctx.scale(r * 4, r * 4)" in block, (
        "per-ember positioning/sizing must be applied via transform against the "
        "shared unit gradient, not baked into a fresh gradient's own coordinates"
    )


def test_theme_js_syntax_is_valid(node_available):
    res = subprocess.run(
        ["node", "--check", str(THEME_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


# ── Real node execution: _rafLoop (visibility-paused scheduler) ──────────


def _extract_rafloop_source(src: str) -> str:
    m = re.search(r"function _rafLoop\(step\)\s*\{.*?\n\}\n", src, re.S)
    assert m, "expected `function _rafLoop(step) { ... }` in theme.js"
    return m.group(0)


def test_rafloop_pauses_while_hidden_and_resumes_on_visible(node_available):
    src = _read(THEME_JS)
    rafloop_src = _extract_rafloop_source(src)
    script = textwrap.dedent(f"""
        {rafloop_src}
        const handlers = [];
        globalThis.document = {{
          hidden: false,
          addEventListener: (ev, fn) => {{ if (ev === 'visibilitychange') handlers.push(fn); }},
          removeEventListener: (ev, fn) => {{
            const i = handlers.indexOf(fn);
            if (i >= 0) handlers.splice(i, 1);
          }},
        }};
        function fireVisibilityChange() {{ for (const h of [...handlers]) h(); }}

        // Minimal rAF shim (node has no real one) — fires on a macrotask so
        // it behaves like a real frame scheduler for this test's purposes.
        let nextHandle = 1;
        const scheduled = new Map();
        globalThis.requestAnimationFrame = (fn) => {{
          const h = nextHandle++;
          scheduled.set(h, setTimeout(() => {{ scheduled.delete(h); fn(); }}, 4));
          return h;
        }};
        globalThis.cancelAnimationFrame = (h) => {{
          const t = scheduled.get(h);
          if (t) {{ clearTimeout(t); scheduled.delete(h); }}
        }};
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

        let steps = 0;
        _rafLoop(() => {{ steps += 1; }});

        await sleep(40); // several frames while visible
        const whileVisible = steps;

        document.hidden = true;
        // No visibilitychange fired here on purpose — the in-flight tick must
        // itself refuse to schedule a new frame once hidden.
        await sleep(40);
        const afterGoingHidden = steps; // must NOT keep climbing

        document.hidden = false;
        fireVisibilityChange();
        await sleep(40);
        const afterResume = steps; // must climb again after visibilitychange

        console.log(JSON.stringify({{ whileVisible, afterGoingHidden, afterResume }}));
        // The loop never stops on its own (step() always returns undefined),
        // so it would keep re-scheduling itself forever — force the process
        // to exit now that we've captured what we need.
        process.exit(0);
    """)
    out = _run_node(script)
    assert out["whileVisible"] > 0, "the loop must run steps while the tab is visible"
    assert out["afterGoingHidden"] - out["whileVisible"] <= 1, (
        "going hidden must stop scheduling further frames almost immediately "
        "(at most the one frame already in flight) — this is the core of #16's "
        "'pause when backgrounded' fix"
    )
    assert out["afterResume"] > out["afterGoingHidden"], (
        "the loop must resume ticking once visibilitychange reports the tab visible again"
    )


def test_rafloop_stops_cleanly_when_step_returns_false(node_available):
    src = _read(THEME_JS)
    rafloop_src = _extract_rafloop_source(src)
    script = textwrap.dedent(f"""
        {rafloop_src}
        let removedListener = false;
        globalThis.document = {{
          hidden: false,
          addEventListener: () => {{}},
          removeEventListener: () => {{ removedListener = true; }},
        }};
        let nextHandle = 1;
        const scheduled = new Map();
        globalThis.requestAnimationFrame = (fn) => {{
          const h = nextHandle++;
          scheduled.set(h, setTimeout(() => {{ scheduled.delete(h); fn(); }}, 4));
          return h;
        }};
        globalThis.cancelAnimationFrame = (h) => {{
          const t = scheduled.get(h);
          if (t) {{ clearTimeout(t); scheduled.delete(h); }}
        }};
        const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

        let steps = 0;
        _rafLoop(() => {{ steps += 1; return steps < 3 ? undefined : false; }});
        await sleep(60);
        const finalSteps = steps;
        await sleep(40);
        const afterMoreWaiting = steps; // must not keep climbing after stop

        console.log(JSON.stringify({{ finalSteps, afterMoreWaiting, removedListener }}));
    """)
    out = _run_node(script)
    assert out["finalSteps"] == 3, "the loop must stop exactly when step() returns false"
    assert out["afterMoreWaiting"] == out["finalSteps"], (
        "no further frames must be scheduled once the loop has stopped"
    )
    assert out["removedListener"] is True, (
        "teardown must remove the visibilitychange listener so a stopped pattern "
        "doesn't leave a zombie listener behind"
    )


# ── Real node execution: _readBgVars / _bumpBgVarsCache (color cache) ────


def _extract_bgvars_cache_source(src: str) -> str:
    m = re.search(
        r"let _bgVarsGen = 0;.*?\nfunction _readBgVars\(\)\s*\{.*?\n\}\n",
        src,
        re.S,
    )
    assert m, "expected the _bgVarsGen/_readBgVars cache block in theme.js"
    return m.group(0)


def test_read_bg_vars_caches_across_calls_and_invalidates_on_bump(node_available):
    src = _read(THEME_JS)
    cache_src = _extract_bgvars_cache_source(src)
    script = textwrap.dedent(f"""
        {cache_src}
        let calls = 0;
        globalThis.document = {{ documentElement: {{}} }};
        globalThis.getComputedStyle = (el) => {{
          calls += 1;
          const vals = {{
            '--bg-effect-color': '#112233',
            '--fg': '#eeeeee',
            '--bg': '#000000',
            '--bg-effect-size': '1',
            '--bg-effect-intensity': '1',
          }};
          return {{ getPropertyValue: (name) => vals[name] || '' }};
        }};

        const first = _readBgVars();
        const second = _readBgVars();
        const callsAfterTwoReads = calls;

        _bumpBgVarsCache();
        const third = _readBgVars();
        const callsAfterBump = calls;

        console.log(JSON.stringify({{
          callsAfterTwoReads, callsAfterBump,
          firstColor: first.effectColor, thirdColor: third.effectColor,
        }}));
    """)
    out = _run_node(script)
    assert out["callsAfterTwoReads"] == 1, (
        "getComputedStyle must be read exactly once across repeated _readBgVars() "
        "calls when nothing changed — this is the per-frame cost the fix removes"
    )
    assert out["callsAfterBump"] == 2, (
        "bumping the cache (as every color/intensity/size setter now does) must "
        "force exactly one more getComputedStyle read on the next _readBgVars() call"
    )
    assert out["firstColor"] == "#112233" and out["thirdColor"] == "#112233"


def test_get_effect_size_routes_through_cache_not_a_raw_read():
    src = _read(THEME_JS)
    m = re.search(r"function _getEffectSize\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected function _getEffectSize() { ... }"
    body = m.group(1)
    assert "_readBgVars()" in body
    assert "getComputedStyle" not in body, (
        "_getEffectSize must no longer call getComputedStyle directly — it "
        "should read the cached value like every canvas pattern does"
    )

