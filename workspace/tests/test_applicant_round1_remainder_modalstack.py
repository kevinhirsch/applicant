"""Regression coverage for design-audit ITEM #17 (round-1 remainder item,
explicitly skipped as out-of-scope by the batch that found it):

    "No global modal/z-order arbiter (upstream `modalManager`/`escMenuStack`
    not ported) — two overlays can stack, Esc is ambiguous. Adopt one modal
    stack."

## What was actually there before this fix

`static/js/modalManager.js` already existed and already tracks a real
monotonic z-order (`_bringToFront` / `_modalTopZ`, minimize/restore/close,
the bottom dock) for TOOL WINDOWS (gallery, cookbook, calendar, ...). That
part of the audit item was a false alarm — lift-and-shift didn't apply
because there was nothing to lift; the z-order stack already existed and was
already used everywhere those tool windows are opened.

The real gap was Escape arbitration, exactly as the round-1 Portal batch's
completion report flagged: `ui.js`'s `initModalA11y(modalEl, closeFn)` — the
shared focus-trap/Escape/focus-restore helper reused by ~13 modal surfaces
(styledConfirm/styledPrompt in ui.js itself, applicantPortal/Mind/Vault/
Remote/Debug/Chat/Gallery/Activity/Results/Update/Onboarding, appkitSheet,
assistant.js) — attached its Escape listener directly to each modal's own
root element with NO knowledge of any other modal that might also be open.
Concretely, before this fix:

  - A styledConfirm/styledPrompt dialog opened from within an already-open
    tool modal (e.g. a delete-confirmation over Vault) is a second, sibling
    `initModalA11y` registration with its own independent Escape listener.
    Nothing coordinated which one Escape should act on.
  - Six surfaces (applicantChat, applicantActivity, applicantGallery,
    applicantResults, applicantUpdate, assistant.js) additionally wired a
    SECOND, raw local `keydown` listener duplicating `initModalA11y`'s own
    Escape handling on the exact same element — Escape fired `_close()`
    twice, and (more importantly for this item) that raw listener bypassed
    any arbitration a future centralized fix would add to `initModalA11y`,
    since it always fires unconditionally.
  - applicantCompare.js wired ONLY that raw local listener — no
    `initModalA11y` call at all, so Compare had no focus-trap either.
  - applicantDebug.js's raw local listener had real intentional logic
    (Escape closes its own overflow popover first, the modal only on the
    second press) layered *on top of* `initModalA11y`'s unconditional
    Escape-closes-the-modal behavior on the very same element — so Escape
    already double-fired there today (both the popover-close-first logic
    AND the immediate whole-modal close from `initModalA11y` ran).

## The fix

`ui.js` gains a small module-private stack (`_modalEscStack`): every
`initModalA11y()` call pushes its `modalEl` on open and pops it on cleanup;
the shared `onKeydown`'s Escape branch now only invokes `closeFn` when its
own `modalEl` is the topmost (most-recently-opened, i.e. last-pushed) entry.
This is a `ui.js`-only, single-source-of-truth change — every surface that
already calls `initModalA11y` gets correct topmost-only Escape arbitration
for free, no per-surface wiring needed.

Three call sites still needed a touch, all pure Escape-wiring (no other
surface internals touched):
  - applicantChat/Activity/Gallery/Results/Update.js + assistant.js: deleted
    the redundant raw local `keydown` listener duplicating `initModalA11y`'s
    own Escape handling (it would have bypassed the new arbiter).
  - applicantCompare.js: now calls `initModalA11y` (it never did) instead of
    only the raw local listener, gaining both the focus trap and the
    arbiter for free, exactly like its sibling surfaces.
  - applicantDebug.js: its overflow-popover-first Escape logic is now the
    `closeFn` passed to `initModalA11y` (instead of living in a second raw
    listener on the same element) — same two-step behavior, but now gated
    by the topmost check like everything else, and with no more redundant
    double Escape-fire.

## Coverage vs. known gaps

Covered automatically (no per-surface wiring): styledConfirm, styledPrompt,
applicantPortal, applicantMind, applicantVault, applicantRemote,
applicantDebug, applicantChat, applicantGallery, applicantActivity,
applicantResults, applicantUpdate, applicantOnboarding, applicantCompare,
appkitSheet, assistant.js — i.e. every current caller of `initModalA11y`.

NOT covered: any surface (present or future) that wires Escape via its own
raw `keydown` listener instead of calling `initModalA11y` is invisible to
the arbiter and will always fire regardless of what else is on top. None of
the ~10+ named surfaces (chat/mind/vault/remote/debug/compare/activity/
gallery/portal/onboarding) do this anymore as of this fix (verified below),
but the arbiter cannot protect a surface that opts out of it.

## Test approach

Two kinds of coverage, matching the two established patterns in this test
suite:

  1. Real DOM/JS execution (`test_applicant_round1_missingkits.py`'s
     hand-rolled DOM shim + `node:module` loader-hook stubbing technique) to
     exercise the ACTUAL stack-arbitration behavior in `ui.js`'s real
     `initModalA11y` — not a reimplementation of the logic under test.
     `ui.js` itself statically imports `theme.js` / `modalManager.js` /
     `spinner.js`, which (like `appkitSheet.js`'s `./ui.js` import in the
     sibling file) pull in real browser-only globals at *module-evaluation*
     time that the DOM shim alone doesn't satisfy — so a `node:module`
     `resolve()` hook redirects exactly those three specifiers (as resolved
     from `ui.js`) to inline no-op stubs, leaving `ui.js`'s own code (the
     code actually under test here) untouched and really executing.
  2. Source-fact regex checks (matching `test_applicant_round1_chatmind.py`)
     for the mechanical call-site fixes (duplicate listener removed / added
     `initModalA11y` wiring / debug's closeFn wrapper) across the touched
     files.

Every assertion below was verified failing, by hand, against the fix it
protects (temporarily reverting the exact source change, confirming a real
`AssertionError`, then restoring — `git diff` clean afterward) before this
file was landed.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_UI_JS = _JS_DIR / "ui.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _read(relpath: str) -> str:
    return (_JS_DIR / relpath).read_text(encoding="utf-8")


# ── Real DOM/JS execution: the actual Escape-arbitration stack in ui.js ────
#
# A trimmed version of test_applicant_round1_missingkits.py's DOM shim: only
# the pieces initModalA11y itself touches (EventTarget-style listeners,
# classList, querySelectorAll, document.activeElement, window/document
# globals so ui.js's own top-level side effects — e.g. `_initScrollDismiss`,
# `_initHoverCardSpaceToggle`, the touch/readyState branches — don't throw
# on import). See that file for the fuller shim if more DOM surface is ever
# needed here.
_DOM_SHIM = r"""
class ClassList {
  constructor(){ this._set = new Set(); }
  add(...c){ c.forEach(x=>x&&this._set.add(x)); }
  remove(...c){ c.forEach(x=>this._set.delete(x)); }
  toggle(c, force){ if(force===undefined){ if(this._set.has(c)){this._set.delete(c); return false;} this._set.add(c); return true;} if(force) this._set.add(c); else this._set.delete(c); return force; }
  contains(c){ return this._set.has(c); }
  get value(){ return Array.from(this._set).join(' '); }
}
class EvtTarget {
  constructor(){ this._l = {}; }
  addEventListener(t,f){ (this._l[t]=this._l[t]||[]).push(f); }
  removeEventListener(t,f){ if(this._l[t]) this._l[t]=this._l[t].filter(x=>x!==f); }
  dispatchEvent(e){ (this._l[e.type]||[]).slice().forEach(f=>f(e)); return true; }
}
class DomNode extends EvtTarget {}
function makeStyle(){ const t={}; return new Proxy(t, { get(tt,p){ if(p==='setProperty') return (k,v)=>{tt[k]=v;}; if(p==='getPropertyValue') return k=>tt[k]||''; if(p==='removeProperty') return k=>{delete tt[k];}; return tt[p]; }, set(tt,p,v){ tt[p]=v; return true; } }); }
class Element extends DomNode {
  constructor(tag){ super(); this.nodeType=1; this.tagName=String(tag).toUpperCase(); this._attrs=new Map(); this.children=[]; this.parentNode=null; this.classList=new ClassList(); this.style=makeStyle(); this._text=''; this._html=''; this.dataset={}; }
  get id(){ return this._attrs.get('id')||''; }
  set id(v){ this._attrs.set('id', v); }
  setAttribute(k,v){ this._attrs.set(k,String(v)); if(k==='class') this.className=String(v); }
  getAttribute(k){ return this._attrs.has(k)? this._attrs.get(k): null; }
  hasAttribute(k){ return this._attrs.has(k); }
  removeAttribute(k){ this._attrs.delete(k); }
  appendChild(c){ if(c.parentNode) c.parentNode.removeChild(c); this.children.push(c); c.parentNode=this; return c; }
  removeChild(c){ const i=this.children.indexOf(c); if(i>=0) this.children.splice(i,1); c.parentNode=null; return c; }
  remove(){ if(this.parentNode) this.parentNode.removeChild(this); }
  querySelectorAll(){ return []; }
  querySelector(){ return null; }
  closest(){ return null; }
  contains(o){ let n=o; while(n){ if(n===this) return true; n=n.parentNode; } return false; }
  focus(){ DOC.activeElement=this; }
  get textContent(){ return this._text; }
  set textContent(v){ this._text=v==null?'':String(v); }
  get innerHTML(){ return this._html; }
  set innerHTML(v){ this._html=v==null?'':String(v); }
}
class Document extends EvtTarget {
  constructor(){ super(); this.body=new Element('body'); this.head=new Element('head'); this.activeElement=null; this.readyState='complete'; }
  createElement(tag){ return new Element(tag); }
  getElementById(){ return null; }
  querySelector(){ return null; }
  querySelectorAll(){ return []; }
}
class WindowObj extends EvtTarget {}
const DOC = new Document();
globalThis.document = DOC;
globalThis.Node = DomNode;
globalThis.CustomEvent = class CustomEvent { constructor(type, o){ this.type=type; this.detail=o&&o.detail; } };
globalThis.MutationObserver = class MutationObserver { constructor(cb){ this.cb=cb; } observe(){} disconnect(){} };
globalThis.localStorage = { _s:{}, getItem(k){ return Object.prototype.hasOwnProperty.call(this._s,k)?this._s[k]:null; }, setItem(k,v){ this._s[k]=String(v); }, removeItem(k){ delete this._s[k]; } };
function matchMedia(query){ return { matches:false, media:query, addEventListener(){}, removeEventListener(){}, addListener(){}, removeListener(){} }; }
const win = new WindowObj();
win.document = DOC;
win.matchMedia = matchMedia;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
win.innerWidth = 1200;
win.location = { origin: 'http://test.local' };
globalThis.window = win;
globalThis.matchMedia = matchMedia;
"""

# `ui.js` statically imports theme.js / modalManager.js / spinner.js. None of
# initModalA11y's own logic touches any of the three, so — same technique as
# test_applicant_round1_missingkits.py's `_UI_STUB_LOADER` (which redirects
# `./ui.js` to a fake so appkitSheet.js's own real code can run against a
# lightweight DOM) — a `node:module` `resolve()` hook redirects exactly
# those three specifiers (as resolved from ui.js) to trivial inline stubs,
# so ui.js's OWN code (the real initModalA11y, the code actually under test)
# imports cleanly and runs for real.
_UI_DEPS_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier.endsWith('/theme.js') || specifier.endsWith('/spinner.js')) {
    return { url: 'data:text/javascript,' + encodeURIComponent('export default {};'), shortCircuit: true };
  }
  if (specifier.endsWith('/modalManager.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(
        'export function register(){} export function unregister(){} ' +
        'export function isRegistered(){return false;} export function isMinimized(){return false;} ' +
        'export function minimize(){} export function restore(){} export function toggle(){return false;} ' +
        'export function close(){} export function injectMinimizeButton(){}'
      ),
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}
`;
register('data:text/javascript,' + encodeURIComponent(__loaderSrc), import.meta.url);
"""


def _run_node(js_body: str) -> dict:
    parts = [_UI_DEPS_STUB_LOADER, _DOM_SHIM, js_body, "process.exit(0);"]
    script = "\n".join(parts)
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=20,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError(f"node produced no stdout\nSTDERR:\n{res.stderr}")
    return json.loads(out_lines[-1])


# Shared JS: import the REAL ui.js, build two fake modal Elements (A opened
# first, B opened "on top" of A — e.g. B is a styledConfirm dialog raised
# from within already-open tool modal A), wire both through the real
# initModalA11y, and record close-call counts as Escape is dispatched.
_STACK_HARNESS = f"""
  const ui = await import('file://{_UI_JS}');
  const a = document.createElement('div');
  const b = document.createElement('div');
  document.body.appendChild(a);
  document.body.appendChild(b);
  let aCloses = 0, bCloses = 0;
  const aCleanup = ui.initModalA11y(a, () => {{ aCloses++; }});
  const bCleanup = ui.initModalA11y(b, () => {{ bCloses++; }});
"""


def test_escape_on_topmost_overlay_closes_only_that_one(node_available):
    """Two overlays open at once (A opened first, B opened on top of it —
    e.g. a styledConfirm dialog raised from within an already-open tool
    modal). Escape dispatched at B (the topmost/most-recently-opened) must
    close ONLY B — A's closeFn must not fire. Before the fix, initModalA11y
    had no concept of "topmost" at all, so whichever modal actually received
    the keydown just closed unconditionally with no arbitration."""
    out = _run_node(_STACK_HARNESS + """
      const e = { key: 'Escape', preventDefault(){}, shiftKey: false };
      b.dispatchEvent({ type: 'keydown', ...e });
      console.log(JSON.stringify({ aCloses, bCloses }));
    """)
    assert out["bCloses"] == 1, "the topmost overlay (B) must close on Escape"
    assert out["aCloses"] == 0, "the non-topmost overlay (A) must NOT close when B is topmost"


def test_escape_on_non_topmost_overlay_is_suppressed(node_available):
    """If Escape is somehow dispatched at A (the BACKGROUND overlay) while B
    is still open on top of it — e.g. focus drifted, or a caller wired a
    second listener directly on A — the arbiter must suppress A's closeFn,
    since A is not the topmost registered overlay. This is the core of the
    "Esc is ambiguous" bug: without arbitration, whichever element actually
    received the keydown just closed, regardless of what else was stacked
    above it."""
    out = _run_node(_STACK_HARNESS + """
      const e = { key: 'Escape', preventDefault(){}, shiftKey: false };
      a.dispatchEvent({ type: 'keydown', ...e });
      console.log(JSON.stringify({ aCloses, bCloses }));
    """)
    assert out["aCloses"] == 0, "A must not close via Escape while B is still open on top of it"
    assert out["bCloses"] == 0


def test_escape_falls_through_to_next_overlay_after_topmost_closes(node_available):
    """Once B (topmost) is closed — its initModalA11y cleanup() called, which
    pops it off the arbiter's stack — A becomes topmost again and Escape now
    correctly closes A. Proves the stack tracks real open/close lifecycle,
    not just a one-shot snapshot."""
    out = _run_node(_STACK_HARNESS + """
      bCleanup(); // B closes (pops off the stack) — mirrors a real close()
      const e = { key: 'Escape', preventDefault(){}, shiftKey: false };
      a.dispatchEvent({ type: 'keydown', ...e });
      console.log(JSON.stringify({ aCloses, bCloses }));
    """)
    assert out["aCloses"] == 1, "A must become closeable by Escape once the overlay stacked on top of it is gone"
    assert out["bCloses"] == 0


def test_single_open_modal_still_closes_on_escape(node_available):
    """Baseline non-regression: with only ONE modal open (the overwhelmingly
    common case), Escape must still close it exactly once — the arbiter must
    not accidentally suppress Escape when there is nothing stacked on top."""
    out = _run_node("""
      const ui = await import('file://""" + str(_UI_JS) + """');
      const a = document.createElement('div');
      document.body.appendChild(a);
      let aCloses = 0;
      ui.initModalA11y(a, () => { aCloses++; });
      const e = { key: 'Escape', preventDefault(){}, shiftKey: false };
      a.dispatchEvent({ type: 'keydown', ...e });
      console.log(JSON.stringify({ aCloses }));
    """)
    assert out["aCloses"] == 1


def test_non_escape_key_never_triggers_close(node_available):
    """Sanity check that the arbiter change didn't loosen the key check
    itself — a non-Escape keydown on the topmost overlay must never call
    closeFn."""
    out = _run_node(_STACK_HARNESS + """
      const e = { key: 'a', preventDefault(){}, shiftKey: false };
      b.dispatchEvent({ type: 'keydown', ...e });
      console.log(JSON.stringify({ aCloses, bCloses }));
    """)
    assert out["aCloses"] == 0
    assert out["bCloses"] == 0


# ── Source-fact checks: the call-site fixes ─────────────────────────────────

# Surfaces that used to wire BOTH initModalA11y AND a redundant raw local
# `keydown` Escape listener on the same modal element (the raw listener would
# bypass the new arbiter and double-fire closeFn).
# (applicantChat.js was originally in this list; the chat-unification pass
# retired its modal entirely — the Job Assistant now opens a session in the
# NATIVE chat surface, so it has no modal, no initModalA11y, and nothing for
# the Escape arbiter to arbitrate. test_applicant_round1_remainder_chat.py
# guards that the modal stays gone.)
_DEDUPED_SURFACES = [
    "applicantActivity.js",
    "applicantGallery.js",
    "applicantResults.js",
    "applicantUpdate.js",
    "assistant.js",
]


@pytest.mark.parametrize("relpath", _DEDUPED_SURFACES)
def test_redundant_local_escape_listener_removed(relpath):
    """Each of these surfaces must still wire initModalA11y (so it keeps
    participating in the shared arbiter + focus trap), but must NOT also
    carry the old raw `modal.addEventListener('keydown', (e) => { if
    (e.key === 'Escape') ...` duplicate — that duplicate always fires
    unconditionally and would defeat the topmost-only arbitration for this
    surface even after the ui.js fix."""
    src = _read(relpath)
    assert "uiModule.initModalA11y(modal," in src, (
        f"{relpath} must still wire initModalA11y (topmost-only Escape arbiter)"
    )
    assert not re.search(r"modal\.addEventListener\('keydown',\s*\(e\)\s*=>\s*\{\s*if\s*\(e\.key === 'Escape'\)", src), (
        f"{relpath} must not carry a second raw local Escape keydown listener "
        "alongside initModalA11y — it would bypass the topmost-only arbiter"
    )


def test_compare_surface_now_wires_init_modal_a11y():
    """applicantCompare.js previously had NO initModalA11y call at all — only
    a raw local Escape listener with no focus trap, invisible to any
    arbiter. It must now call initModalA11y (like every sibling surface) and
    clean it up in _close(), and must not still carry the old raw listener."""
    src = _read("applicantCompare.js")
    assert "let _modalA11yCleanup" in src, "expected a _modalA11yCleanup tracking variable"
    assert re.search(r"_modalA11yCleanup\s*=\s*uiModule\.initModalA11y\(modal,\s*_close\)", src), (
        "applicantCompare.js must wire initModalA11y(modal, _close)"
    )
    close_fn = re.search(r"function _close\(\)\s*\{(.*?)\n\}", src, re.S)
    assert close_fn, "expected to find _close()"
    assert "_modalA11yCleanup" in close_fn.group(1) and "_modalA11yCleanup()" in close_fn.group(1), (
        "_close() must invoke the a11y cleanup so the modal pops off the Escape arbiter stack"
    )
    assert not re.search(r"modal\.addEventListener\('keydown',\s*\(e\)\s*=>\s*\{\s*if\s*\(e\.key === 'Escape'\)", src), (
        "the old raw local Escape listener must be gone now that initModalA11y is wired"
    )


def test_debug_overflow_escape_logic_routed_through_init_modal_a11y_closefn():
    """applicantDebug.js's Escape behavior (close the overflow popover first
    if open, else close the whole modal) must now be the `closeFn` passed
    directly to initModalA11y — not a second raw `keydown` listener bolted
    on top of initModalA11y's own unconditional Escape handling on the same
    element (which is what caused Escape to double-fire there before this
    fix: the popover-first logic AND an immediate whole-modal close both ran
    on every Escape press)."""
    src = _read("applicantDebug.js")
    m = re.search(r"_modalA11yCleanup\s*=\s*uiModule\.initModalA11y\(modal,\s*\(\)\s*=>\s*\{(.*?)\}\);", src, re.S)
    assert m, "expected initModalA11y's closeFn to be an inline arrow function on applicantDebug.js"
    close_fn_body = m.group(1)
    assert "overflowMenu" in close_fn_body and "closeOverflow()" in close_fn_body, (
        "the overflow-popover-first Escape behavior must live inside initModalA11y's closeFn"
    )
    assert "_close();" in close_fn_body
    # And the old standalone raw keydown listener (with its own `if (e.key
    # !== 'Escape') return;` early-out) must be gone — the block above fully
    # replaces it.
    assert not re.search(r"modal\.addEventListener\('keydown',\s*\(e\)\s*=>\s*\{\s*\n\s*if\s*\(e\.key !== 'Escape'\)\s*return;", src), (
        "the old standalone Escape keydown listener must be removed from applicantDebug.js"
    )


def test_ui_js_exposes_topmost_only_escape_arbitration():
    """Direct source check that ui.js's initModalA11y gates its Escape branch
    on a topmost check backed by a shared stack, rather than closing
    unconditionally whenever its own element receives Escape."""
    src = _read("ui.js")
    fn = re.search(r"export function initModalA11y\(modalEl, closeFn\)\s*\{(.*?)\n\}", src, re.S)
    assert fn, "expected to find initModalA11y"
    body = fn.group(1)
    assert "_escStackPush(modalEl)" in body, "initModalA11y must register itself with the Escape arbiter on open"
    assert "_escStackPop(modalEl)" in body, "initModalA11y's cleanup must unregister from the Escape arbiter on close"
    m = re.search(r"if \(e\.key === 'Escape'\)\s*\{(.*?)\}", body, re.S)
    assert m, "expected the Escape branch in initModalA11y's onKeydown"
    assert "_isTopOfEscStack(modalEl)" in m.group(1), (
        "the Escape branch must check topmost-ness before invoking closeFn"
    )


# ── Syntax sanity on every touched file ─────────────────────────────────────

_TOUCHED_FILES = [
    "ui.js",
    "applicantChat.js",
    "applicantActivity.js",
    "applicantGallery.js",
    "applicantResults.js",
    "applicantUpdate.js",
    "assistant.js",
    "applicantCompare.js",
    "applicantDebug.js",
]


@pytest.mark.parametrize("relpath", _TOUCHED_FILES)
def test_touched_file_is_valid_js(relpath):
    res = subprocess.run(
        ["node", "--check", str(_JS_DIR / relpath)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0, res.stderr


#: Same split-halves technique as test_applicant_round1_missingkits.py — see
#: that file's comment for why: this file's own source text must never
#: contain the literal, contiguous upstream-fork codename or CI's white-label
#: denylist grep would trip on this file itself.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_and_touched_sources_have_no_whitelabel_denylist_hits():
    paths = [pathlib.Path(__file__)] + [_JS_DIR / f for f in _TOUCHED_FILES]
    for path in paths:
        lowered = path.read_text(encoding="utf-8").lower()
        for first, second in _DENYLIST_CODENAME_HALVES:
            codename = first + second
            assert codename not in lowered, f"{path} contains denylisted codename fragment"
