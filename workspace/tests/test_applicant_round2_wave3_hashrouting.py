"""Regression coverage for round 2 / wave 3, systemic theme #7 / Top-25 §4E:
"16 transient modals, zero URL routing, one-way deep-links... Add hash
routing, '← back to Pending'" (the redline → "Continue to submit" CTA half of
that item already shipped in ``documentLibrary.js`` — not touched here).

This wave adds:

  - ``static/js/hashRouter.js`` — a brand-new, generic hash-routing utility.
    Surfaces register a ``{open, close}`` pair under a plain-word hash token
    (``'portal'``, ``'activity'``); the router keeps ``location.hash`` in
    sync with whichever registered surface is open (deep-link on
    load/refresh, browser back/forward, no clobbering an unrelated hash like
    a session id or the ``#email=`` one-shot deep link those two already
    own — see the module's own header comment).
  - ``applicantPortal.js`` / ``applicantActivity.js`` wired to it: each
    self-registers its existing ``open.../_close`` pair at module-eval time,
    calls ``setHash``/``clearHash`` from its own open/close, and exports a
    ``close...`` counterpart to its existing ``open...`` export. Activity
    additionally grows a "← Back to Pending" header affordance, shown only
    when it was opened via the router (a deep link), that calls the
    existing ``window.applicantPortalModule.openApplicantPortal()`` seam.
  - ``app.js`` sequences registration (both surfaces self-register during
    their own dynamic-import evaluation, before app.js's promises resolve),
    guards the pre-existing automatic "land on Portal" boot behavior so a
    deep link to a *different* registered surface (e.g. ``#activity``)
    doesn't get Portal stacked on top of it, and starts the router listening.

Two testing strategies, per the task's stated preference for real execution
over text-regex wherever practical:

  1. ``hashRouter.js`` itself — brand-new, DOM-adjacent (``location``,
     ``history``, ``hashchange``) logic with no server-side surface — is
     exercised with real ``node`` execution against a from-scratch
     location/history/DOM shim (adapted from the reusable one in
     ``test_applicant_round1_missingkits.py``: real Element/Document/window
     objects, not string templates).
  2. ``applicantActivity.js`` is loaded and run for real too (not just
     text-matched) — its only DOM-heavy dependency is ``./ui.js``, which is
     redirected via the same ``node:module`` loader-hook substitution
     ``test_applicant_round1_missingkits.py`` established, to a tiny stub
     exposing the handful of functions Activity actually calls
     (``initModalA11y``, ``esc``, ``showToast``). ``applicantPortal.js`` is
     NOT loaded for real here: its import graph pulls in
     ``applicantOnboarding.js`` (owned by a different concurrent agent this
     round — out of scope to touch, and risky to depend on for a test that
     must stay green independent of that file's own churn),
     ``applicantRemote.js`` and ``emailLibrary/applicantDigest.js``, none of
     which are needed to prove the hash-routing contract this wave adds (the
     exact same contract is already proven against the real Activity file).
     Portal's own wiring is instead verified the same way
     ``test_applicant_round2_wave2_redlinecta.py`` verifies
     ``documentLibrary.js``: reading the actual source and asserting the
     exact lines exist, in context. ``app.js``'s boot-sequencing guard is
     covered the same way (it is pure promise/branch wiring around already
     -covered functions, not new DOM logic worth a shim for).

Every ``test_*`` here was verified failing (per the task's DoD) by
temporarily reverting the exact line(s) of source it protects, confirming
the assertion actually goes red, then restoring the original file (clean
``git diff`` afterward) before landing this file.
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
_HASH_ROUTER_JS = _JS_DIR / "hashRouter.js"
_PORTAL_JS = _JS_DIR / "applicantPortal.js"
_ACTIVITY_JS = _JS_DIR / "applicantActivity.js"
_APP_JS = _REPO / "static" / "app.js"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + location/history shim (real objects, real event dispatch) ──
#
# Adapted from test_applicant_round1_missingkits.py's _DOM_SHIM, plus a
# `window.location` / `history` model rich enough to exercise hash routing:
#   - `history.pushState(...)` mutates the hash WITHOUT firing 'hashchange'
#     (matches the real DOM — this is exactly what hashRouter.js relies on
#     to avoid feedback loops between its own setHash/clearHash calls and
#     its own hashchange listener).
#   - setting `location.hash = ...` directly DOES fire 'hashchange' — used
#     by `__simulateHashNav` below to stand in for a real navigation event
#     (typed URL, clicked `<a href="#x">`, or browser back/forward).
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
  get className(){ return this.classList.value; }
  set className(v){ this.classList=new ClassList(); (v||'').split(/\s+/).filter(Boolean).forEach(c=>this.classList.add(c)); }
  setAttribute(k,v){ this._attrs.set(k,String(v)); if(k==='class') this.className=String(v); }
  getAttribute(k){ return this._attrs.has(k)? this._attrs.get(k): null; }
  hasAttribute(k){ return this._attrs.has(k); }
  removeAttribute(k){ this._attrs.delete(k); }
  appendChild(c){ if(c.parentNode) c.parentNode.removeChild(c); this.children.push(c); c.parentNode=this; return c; }
  removeChild(c){ const i=this.children.indexOf(c); if(i>=0) this.children.splice(i,1); c.parentNode=null; return c; }
  remove(){ if(this.parentNode) this.parentNode.removeChild(this); }
  insertBefore(n,ref){ if(n.parentNode) n.parentNode.removeChild(n); if(ref==null) this.children.push(n); else { const i=this.children.indexOf(ref); this.children.splice(i<0?this.children.length:i,0,n); } n.parentNode=this; return n; }
  get isConnected(){ let n=this; while(n.parentNode) n=n.parentNode; return n===DOC.body || n===DOC.head; }
  querySelectorAll(sel){ return collectDescendants(this).filter(e=>matchesSelector(e,sel)); }
  querySelector(sel){ return this.querySelectorAll(sel)[0]||null; }
  closest(sel){ let n=this; while(n && n.tagName){ if(matchesSelector(n,sel)) return n; n=n.parentNode; } return null; }
  contains(o){ let n=o; while(n){ if(n===this) return true; n=n.parentNode; } return false; }
  focus(){ DOC.activeElement=this; }
  get textContent(){ return this._text; }
  set textContent(v){ this._text=v==null?'':String(v); this.children=[]; this._html=''; }
  get innerHTML(){ return this._html; }
  set innerHTML(v){ this.children=[]; this._html=v==null?'':String(v); _parseHTMLInto(this, this._html); }
  insertAdjacentHTML(pos, html){ this._html+=html; _parseHTMLInto(this, html); }
}
function collectDescendants(el, acc){ acc=acc||[]; for(const c of el.children){ acc.push(c); collectDescendants(c, acc); } return acc; }
// Minimal HTML->DOM parser for `innerHTML =` (needed because applicantActivity.js
// builds its whole modal from one big template-literal `.innerHTML = \`...\`` and
// then does `.querySelector('#...')` against the result — unlike the appkitSheet
// kits this shim was originally written for, which build DOM node-by-node via
// createElement/appendChild and never needed this). Good enough for the
// controlled, hand-written modal markup under test here: nested tags, quoted
// attributes, self-closing/void tags, SVG child elements (treated as plain
// elements — nothing here calls SVG-specific APIs). Not a general HTML parser.
const _VOID_TAGS = new Set(['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']);
function _parseHTMLInto(container, html){
  const tagRe = /<!--[\s\S]*?-->|<\/([a-zA-Z0-9-]+)\s*>|<([a-zA-Z0-9-]+)((?:\s+[a-zA-Z_:][-a-zA-Z0-9_:.]*(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*)\s*(\/?)\s*>/g;
  const stack = [container];
  let m;
  while ((m = tagRe.exec(html))) {
    const [whole, closeTag, openTag, attrsStr, selfClose] = m;
    if (whole.startsWith('<!--')) continue;
    if (closeTag) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName.toLowerCase() === closeTag.toLowerCase()) { stack.length = i; break; }
      }
      continue;
    }
    if (openTag) {
      const el = new Element(openTag);
      const attrRe = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("([^"]*)"|'([^']*)'|[^\s"'>]+))?/g;
      let am;
      while ((am = attrRe.exec(attrsStr || ''))) {
        const name = am[1];
        const val = am[3] !== undefined ? am[3] : (am[4] !== undefined ? am[4] : (am[2] || ''));
        el.setAttribute(name, val);
      }
      stack[stack.length - 1].appendChild(el);
      if (!selfClose && !_VOID_TAGS.has(openTag.toLowerCase())) stack.push(el);
    }
  }
}
function testBase(el, base){
  if(base==='*'||base==='') return true;
  if(base[0]==='#') return el.id===base.slice(1);
  if(base[0]==='.') return el.classList.contains(base.slice(1));
  if(base[0]==='['){ const m=base.match(/^\[([a-zA-Z0-9_-]+)(?:=("[^"]*"|'[^']*'))?\]$/); if(!m) return false; if(!el.hasAttribute(m[1])) return false; if(m[2]!==undefined) return el.getAttribute(m[1])===m[2].slice(1,-1); return true; }
  return el.tagName && el.tagName.toLowerCase()===base.toLowerCase();
}
function matchesSimple(el, sel){
  const notClauses=[]; let base=sel.replace(/:not\(([^)]*)\)/g,(m,inner)=>{notClauses.push(inner); return '';}).trim();
  if(base && !testBase(el, base)) return false;
  for(const nc of notClauses) if(testBase(el, nc)) return false;
  return true;
}
function matchesSelector(el, sel){ return sel.split(',').some(s=>matchesSimple(el, s.trim())); }
function findById(el, id){ if(el.id===id) return el; for(const c of el.children){ const r=findById(c,id); if(r) return r; } return null; }
class Document extends EvtTarget {
  constructor(){ super(); this.body=new Element('body'); this.head=new Element('head'); this.activeElement=null; }
  createElement(tag){ return new Element(tag); }
  getElementById(id){ return findById(this.body,id) || findById(this.head,id); }
  querySelector(sel){ return this.body.querySelector(sel) || this.head.querySelector(sel); }
  querySelectorAll(sel){ return [...this.body.querySelectorAll(sel), ...this.head.querySelectorAll(sel)]; }
}
class WindowObj extends EvtTarget {}
const DOC = new Document();
globalThis.document = DOC;
globalThis.Node = DomNode;
globalThis.CustomEvent = class CustomEvent { constructor(type, o){ this.type=type; this.detail=o&&o.detail; } };
globalThis.MutationObserver = class MutationObserver { constructor(cb){ this.cb=cb; } observe(){} disconnect(){} };
globalThis.localStorage = { _s:{}, getItem(k){ return Object.prototype.hasOwnProperty.call(this._s,k)?this._s[k]:null; }, setItem(k,v){ this._s[k]=String(v); }, removeItem(k){ delete this._s[k]; } };
// Deterministic — no real network in this shim; _fetchJSON's own try/catch
// turns this into a calm error state, which is all the Activity integration
// test needs (it asserts on modal/hash/button state, not fetched data).
globalThis.fetch = () => Promise.reject(new Error('no network in test shim'));
globalThis.AbortController = class AbortController { constructor(){ this.signal = { aborted:false }; } abort(){ this.signal.aborted = true; } };

class Loc {
  constructor(){ this._hash=''; this.pathname='/'; this.search=''; }
  get hash(){ return this._hash; }
  set hash(v){
    const nv = (v==null || v==='') ? '' : (String(v).startsWith('#') ? String(v) : '#'+v);
    if (nv === this._hash) return;
    this._hash = nv;
    win.dispatchEvent({ type: 'hashchange' }); // real browsers fire this on a direct location.hash set
  }
}
const __loc = new Loc();
function __parseHashFromUrl(url){
  const s = String(url == null ? '' : url);
  const i = s.indexOf('#');
  return i >= 0 ? s.slice(i) : '';
}
globalThis.__pushStateCalls = 0;
globalThis.history = {
  pushState(state, title, url){ globalThis.__pushStateCalls++; __loc._hash = __parseHashFromUrl(url); }, // no hashchange — matches the real DOM
  replaceState(state, title, url){ __loc._hash = __parseHashFromUrl(url); },
};
// Stand-in for a real navigation event (back/forward, typed URL, clicked
// <a href="#x">) — the one case that legitimately fires 'hashchange'.
globalThis.__simulateHashNav = function(newHash){ __loc.hash = newHash; };

const win = new WindowObj();
win.document = DOC;
win.location = __loc;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
win.history = globalThis.history;
globalThis.window = win;
"""

# `applicantActivity.js` (and, transitively through applicantCore.js) needs
# `./ui.js` stubbed — same node:module loader-hook substitution technique
# test_applicant_round1_missingkits.py established (copied verbatim below,
# just with a `showToast` no-op added to the exported object — Activity's
# own `esc` comes from applicantCore.js, which already falls back to its
# own regex escaper when `uiModule.esc` isn't a function, so the stub
# doesn't need to provide one).
_UI_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === './ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(
        'export function initModalA11y(el, closeFn) {' +
        'globalThis.__initModalA11yCalls = (globalThis.__initModalA11yCalls||0) + 1;' +
        'globalThis.__initModalA11yClose = closeFn;' +
        'return function(){ globalThis.__initModalA11yCleanupCalls = (globalThis.__initModalA11yCleanupCalls||0) + 1; };' +
        '}' +
        'const uiModule = { showToast: function(){}, initModalA11y };' +
        'export default uiModule;'
      ),
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}
`;
register('data:text/javascript,' + encodeURIComponent(__loaderSrc), import.meta.url);
"""


def _run_node(js_body: str, *, with_ui_stub: bool = False) -> dict:
    parts = []
    if with_ui_stub:
        parts.append(_UI_STUB_LOADER)
    parts.append(_DOM_SHIM)
    parts.append(js_body)
    parts.append("process.exit(0);")
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


# ══════════════════════════════════════════════════════════════════════════
# 1. hashRouter.js — the generic utility, real execution
# ══════════════════════════════════════════════════════════════════════════


def test_module_shape_and_window_export(node_available):
    """Public API surface + the `window.applicantHashRouter` mirror (same
    pattern as `window.applicant*Module` throughout this codebase)."""
    script = f"""
        const mod = await import('file://{_HASH_ROUTER_JS}');
        console.log(JSON.stringify({{
          hasRegisterRoute: typeof mod.registerRoute === 'function',
          hasHasRoute: typeof mod.hasRoute === 'function',
          hasSetHash: typeof mod.setHash === 'function',
          hasClearHash: typeof mod.clearHash === 'function',
          hasCurrentHashToken: typeof mod.currentHashToken === 'function',
          hasInitHashRouting: typeof mod.initHashRouting === 'function',
          windowExport: window.applicantHashRouter === mod.default,
        }}));
    """
    out = _run_node(script)
    assert out == {
        "hasRegisterRoute": True,
        "hasHasRoute": True,
        "hasSetHash": True,
        "hasClearHash": True,
        "hasCurrentHashToken": True,
        "hasInitHashRouting": True,
        "windowExport": True,
    }


def test_deep_link_present_at_boot_opens_the_matching_route(node_available):
    """The core "refresh with the hash present re-opens it" contract:
    location.hash is set (simulating a page that loaded with a deep link)
    BEFORE the module is even imported — matching a real page load, where
    the URL's hash is present before any script runs, let alone before
    initHashRouting() is called. (Setting it after import wouldn't actually
    exercise the fix this guards: hashRouter.js's own internal bootstrap
    state is captured at *module-eval* time.)"""
    script = f"""
        window.location.hash = '#activity'; // present before the module (and its internal state) even loads
        const {{ registerRoute, initHashRouting, hasRoute }} = await import('file://{_HASH_ROUTER_JS}');
        let opens = 0, closes = 0;
        registerRoute('activity', {{ open: () => {{ opens++; }}, close: () => {{ closes++; }} }});
        console.log(JSON.stringify({{ hasRouteBefore: hasRoute('activity') }}));
        initHashRouting();
        console.log(JSON.stringify({{ opens, closes }}));
    """
    res = subprocess.run(
        ["node", "--input-type=module", "-e", "\n".join([_DOM_SHIM, script, "process.exit(0);"])],
        cwd=_REPO, capture_output=True, timeout=20, text=True,
    )
    assert res.returncode == 0, f"node failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}"
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert json.loads(lines[0]) == {"hasRouteBefore": True}
    assert json.loads(lines[1]) == {"opens": 1, "closes": 0}


def test_no_hash_at_boot_opens_nothing(node_available):
    """Absent a hash, initHashRouting() must not call any registered open()
    — the router only acts on a route it actually matches."""
    script = f"""
        const {{ registerRoute, initHashRouting }} = await import('file://{_HASH_ROUTER_JS}');
        let opens = 0;
        registerRoute('portal', {{ open: () => {{ opens++; }}, close: () => {{}} }});
        initHashRouting();
        console.log(JSON.stringify({{ opens }}));
    """
    out = _run_node(script)
    assert out == {"opens": 0}


def test_setHash_pushes_and_is_idempotent(node_available):
    """setHash updates location.hash but does not re-push (and does not
    itself fire hashchange / re-invoke any route) when already current —
    calling it a second time with the same token must not add a second
    history entry (checked via the shim's history.pushState call counter,
    since a same-value push is otherwise indistinguishable from a no-op by
    reading location.hash alone)."""
    script = f"""
        const {{ setHash }} = await import('file://{_HASH_ROUTER_JS}');
        let hashchangeFired = 0;
        window.addEventListener('hashchange', () => {{ hashchangeFired++; }});
        setHash('portal');
        const afterFirst = window.location.hash;
        const pushesAfterFirst = globalThis.__pushStateCalls;
        setHash('portal'); // same token again — must be a no-op, not a redundant push
        const afterSecond = window.location.hash;
        const pushesAfterSecond = globalThis.__pushStateCalls;
        console.log(JSON.stringify({{ afterFirst, afterSecond, pushesAfterFirst, pushesAfterSecond, hashchangeFired }}));
    """
    out = _run_node(script)
    assert out == {
        "afterFirst": "#portal", "afterSecond": "#portal",
        "pushesAfterFirst": 1, "pushesAfterSecond": 1,
        "hashchangeFired": 0,
    }


def test_clearHash_only_clears_its_own_token(node_available):
    """clearHash('activity') must never clobber a hash that belongs to a
    different route (or a session id, or an in-flight #email= deep link) —
    only clearHash('portal') may touch '#portal'."""
    script = f"""
        const {{ setHash, clearHash }} = await import('file://{_HASH_ROUTER_JS}');
        setHash('portal');
        clearHash('activity'); // wrong token — must be a no-op
        const afterWrongClear = window.location.hash;
        clearHash('portal'); // right token — must clear
        const afterRightClear = window.location.hash;
        console.log(JSON.stringify({{ afterWrongClear, afterRightClear }}));
    """
    out = _run_node(script)
    assert out == {"afterWrongClear": "#portal", "afterRightClear": ""}


def test_clearHash_never_touches_an_unrelated_session_hash(node_available):
    """sessions.js owns bare `#<sessionId>` hashes — clearHash for a
    registered route token must leave an unrelated hash completely alone."""
    script = f"""
        const {{ clearHash }} = await import('file://{_HASH_ROUTER_JS}');
        window.location.hash = '#some-session-uuid-123';
        clearHash('portal');
        console.log(JSON.stringify({{ hash: window.location.hash }}));
    """
    out = _run_node(script)
    assert out == {"hash": "#some-session-uuid-123"}


def test_browser_back_closes_the_open_surface(node_available):
    """The back/forward contract: a real navigation event (not a pushState)
    that moves the hash away from an open route's token must call that
    route's close(), and must NOT call open() for a token with no
    registered route."""
    script = f"""
        const {{ registerRoute, initHashRouting, setHash }} = await import('file://{_HASH_ROUTER_JS}');
        let opens = 0, closes = 0;
        registerRoute('portal', {{ open: () => {{ opens++; }}, close: () => {{ closes++; }} }});
        initHashRouting();
        setHash('portal'); // user opened Portal via a launcher (opens the route out-of-band, like the real callers do)
        opens++; // the real caller's own open() call, mirrored here
        __simulateHashNav(''); // browser Back
        console.log(JSON.stringify({{ opens, closes, hashAfterBack: window.location.hash }}));
    """
    out = _run_node(script)
    assert out == {"opens": 1, "closes": 1, "hashAfterBack": ""}


def test_hash_forward_between_two_registered_routes_closes_then_opens(node_available):
    """Navigating directly from one registered route's hash to another's
    (e.g. clicking a second deep link without going through '') must close
    the first and open the second — not leave both "open"."""
    script = f"""
        const {{ registerRoute, initHashRouting }} = await import('file://{_HASH_ROUTER_JS}');
        const log = [];
        registerRoute('portal', {{ open: () => log.push('portal-open'), close: () => log.push('portal-close') }});
        registerRoute('activity', {{ open: () => log.push('activity-open'), close: () => log.push('activity-close') }});
        window.location.hash = '#portal';
        initHashRouting();
        __simulateHashNav('#activity');
        console.log(JSON.stringify(log));
    """
    out = _run_node(script)
    assert out == ["portal-open", "portal-close", "activity-open"]


def test_reverting_lastToken_sentinel_breaks_deep_link_on_boot(node_available):
    """Guards the specific fix that makes 'refresh with the hash already
    present' work: initializing `_lastToken` from the current hash (instead
    of a sentinel the current hash can never equal) makes the very first
    _applyFromHash() call see "nothing changed" and skip opening. This test
    exercises the *shipped* behavior (sentinel) and is paired with a
    by-hand revert during development, per the DoD, to confirm this exact
    scenario is what would go red."""
    script = f"""
        window.location.hash = '#portal'; // present before the module (and its internal state) even loads
        const {{ registerRoute, initHashRouting }} = await import('file://{_HASH_ROUTER_JS}');
        let opens = 0;
        registerRoute('portal', {{ open: () => {{ opens++; }}, close: () => {{}} }});
        initHashRouting();
        console.log(JSON.stringify({{ opens }}));
    """
    out = _run_node(script)
    assert out == {"opens": 1}


# ══════════════════════════════════════════════════════════════════════════
# 2. applicantActivity.js — real production file, real execution
# ══════════════════════════════════════════════════════════════════════════


def test_activity_self_registers_the_activity_route(node_available):
    """Importing the real applicantActivity.js must, as a side effect of
    module evaluation (no boot/DOM-ready needed), register 'activity' with
    hashRouter.js — this is what lets app.js await the dynamic import and
    know registration already happened, with no extra wiring."""
    script = f"""
        await import('file://{_ACTIVITY_JS}');
        console.log(JSON.stringify({{ hasRoute: window.applicantHashRouter.hasRoute('activity') }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"hasRoute": True}


def test_activity_open_sets_hash_and_exposes_close(node_available):
    """openApplicantActivity() (the real, unmodified-signature export) must
    update location.hash to '#activity', and the module must export a
    closeApplicantActivity counterpart (mirrors openApplicantPortal /
    closeApplicantPortal)."""
    script = f"""
        const mod = await import('file://{_ACTIVITY_JS}');
        console.log(JSON.stringify({{ hasClose: typeof mod.closeApplicantActivity === 'function' }}));
        await mod.openApplicantActivity();
        console.log(JSON.stringify({{ hash: window.location.hash }}));
    """
    out_lines_script = script
    res = subprocess.run(
        ["node", "--input-type=module", "-e", "\n".join([_UI_STUB_LOADER, _DOM_SHIM, out_lines_script, "process.exit(0);"])],
        cwd=_REPO, capture_output=True, timeout=20, text=True,
    )
    assert res.returncode == 0, f"node failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}"
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    assert json.loads(lines[0]) == {"hasClose": True}
    assert json.loads(lines[1]) == {"hash": "#activity"}


def test_activity_close_clears_hash_and_hides_modal(node_available):
    """closeApplicantActivity() must hide the modal AND clear '#activity'
    from the URL — the "hash clears when the surface closes" contract."""
    script = f"""
        const mod = await import('file://{_ACTIVITY_JS}');
        await mod.openApplicantActivity();
        const hashWhileOpen = window.location.hash;
        const hiddenWhileOpen = document.getElementById('applicant-activity-modal').classList.contains('hidden');
        mod.closeApplicantActivity();
        const hashAfterClose = window.location.hash;
        const hiddenAfterClose = document.getElementById('applicant-activity-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ hashWhileOpen, hiddenWhileOpen, hashAfterClose, hiddenAfterClose }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {
        "hashWhileOpen": "#activity",
        "hiddenWhileOpen": False,
        "hashAfterClose": "",
        "hiddenAfterClose": True,
    }


def test_activity_back_to_pending_link_only_shows_when_opened_via_route(node_available):
    """The "← Back to Pending" header affordance must stay hidden for a
    normal in-app open (e.g. clicking the rail button — no `viaRoute`
    flag), and appear only for the hash-router-driven open (a deep link),
    per the task's "when it implies you came from Pending" scoping."""
    script = f"""
        const mod = await import('file://{_ACTIVITY_JS}');
        await mod.openApplicantActivity(); // plain in-app open — no viaRoute
        const hiddenForPlainOpen = document.getElementById('applicant-activity-back-portal').style.display === 'none';
        await mod.openApplicantActivity({{ viaRoute: true }}); // hash-router-driven open
        const visibleForRouteOpen = document.getElementById('applicant-activity-back-portal').style.display !== 'none';
        console.log(JSON.stringify({{ hiddenForPlainOpen, visibleForRouteOpen }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"hiddenForPlainOpen": True, "visibleForRouteOpen": True}


def test_activity_back_to_pending_click_calls_openApplicantPortal_and_closes_activity(node_available):
    """Clicking "← Back to Pending" must call the existing
    window.applicantPortalModule.openApplicantPortal() seam (the SAME
    cross-lane seam applicantChat.js / documentLibrary.js already use — no
    new open logic invented here) and close the Activity modal."""
    script = f"""
        const mod = await import('file://{_ACTIVITY_JS}');
        let portalOpened = 0;
        window.applicantPortalModule = {{ openApplicantPortal: () => {{ portalOpened++; }} }};
        await mod.openApplicantActivity({{ viaRoute: true }});
        document.getElementById('applicant-activity-back-portal').dispatchEvent({{ type: 'click' }});
        const hiddenAfter = document.getElementById('applicant-activity-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ portalOpened, hiddenAfter }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"portalOpened": 1, "hiddenAfter": True}


def test_activity_hashchange_back_closes_the_modal(node_available):
    """End-to-end through the real file: open Activity via the hash router
    path (deep link present at boot), then simulate browser Back — the
    modal must actually close (not just the isolated router-unit-test
    contract; this drives the real DOM the real module built)."""
    script = f"""
        await import('file://{_ACTIVITY_JS}'); // self-registers 'activity' at eval time
        window.applicantHashRouter.initHashRouting(); // no hash yet — no-op
        __simulateHashNav('#activity'); // deep link arrives
        const openedHidden = document.getElementById('applicant-activity-modal').classList.contains('hidden');
        __simulateHashNav(''); // browser Back
        const closedHidden = document.getElementById('applicant-activity-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ openedHidden, closedHidden }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"openedHidden": False, "closedHidden": True}


# ══════════════════════════════════════════════════════════════════════════
# 3. applicantPortal.js — source-level wiring (see module docstring for why
#    this file isn't loaded for real execution: its import graph reaches
#    applicantOnboarding.js, owned by a different concurrent agent this
#    round, plus applicantRemote.js / applicantDigest.js — none needed to
#    re-prove a contract already exercised for real against Activity above).
# ══════════════════════════════════════════════════════════════════════════


def test_portal_imports_hashRouter_and_registers_the_portal_route():
    src = _read(_PORTAL_JS)
    assert "from './hashRouter.js'" in src
    assert re.search(
        r"registerRoute\(\s*'portal'\s*,\s*\{\s*open:\s*openApplicantPortal\s*,\s*close:\s*_close\s*\}\s*\)",
        src,
    ), "expected Portal to self-register its existing open/close pair under the 'portal' token"


def test_portal_open_sets_hash_unless_skipped():
    src = _read(_PORTAL_JS)
    m = re.search(r"export async function openApplicantPortal\(opts\) \{(.*?)\n\}", src, re.S)
    assert m, "expected openApplicantPortal(opts) to accept an opts arg"
    body = m.group(1)
    assert "setHash('portal')" in body
    assert "skipHashUpdate" in body


def test_portal_close_clears_hash_and_is_exported():
    src = _read(_PORTAL_JS)
    m = re.search(r"function _close\(\) \{(.*?)\n\}", src, re.S)
    assert m, "expected the existing _close() to still exist"
    assert "clearHash('portal')" in m.group(1)
    assert re.search(r"export function closeApplicantPortal\(\)\s*\{\s*_close\(\);\s*\}", src), (
        "expected a closeApplicantPortal export mirroring openApplicantPortal"
    )
    # ...and actually exposed on the public module object, same as openApplicantPortal.
    assert re.search(r"applicantPortalModule = \{[^}]*\bcloseApplicantPortal\b", src)


def test_portal_boot_time_auto_open_skips_hash_update():
    """The ONE caller that must not touch location.hash is app.js's
    automatic "land on Portal" boot-time open — everything else (explicit
    launcher clicks, the redline CTA, hash-router replays) should sync the
    URL. Guard against that one call silently losing its opt-out."""
    src = _read(_APP_JS)
    assert re.search(
        r"portal\.openApplicantPortal\(\{\s*skipHashUpdate:\s*true\s*\}\)", src
    ), "expected app.js's automatic boot-time Portal open to pass skipHashUpdate: true"


def test_app_js_registers_hash_router_readiness_after_both_surfaces_load():
    src = _read(_APP_JS)
    assert "_hashRouterReady" in src
    assert "./js/hashRouter.js" in src
    # Must wait for BOTH dynamic imports before considering routes registered
    # (both self-register at module-eval time — see the Activity/Portal
    # tests above — so waiting for the import promises is sufficient; no
    # extra registerRoute() calls belong in app.js itself).
    assert re.search(r"Promise\.all\(\[\s*_portalReady\s*,\s*_activityReady\s*\]\)", src)


def test_app_js_guards_default_portal_landing_against_a_different_deep_link():
    """A deep link to a different registered surface (e.g. '#activity')
    must win over the default "auto-land on Portal" boot behavior — else
    Portal would stack on top of whatever the user followed a link to."""
    src = _read(_APP_JS)
    m = re.search(r"\.then\(async \(wizardShown\) => \{(.*?)\n    \}\)\n    \.catch", src, re.S)
    assert m, "expected the onboarding-chain .then(async (wizardShown) => {...}) block"
    body = m.group(1)
    assert "router.hasRoute(hashToken)" in body
    assert "router.initHashRouting()" in body
    assert "hashToken !== 'portal'" in body


def test_app_js_still_imports_activity_and_update_and_onboarding_unconditionally():
    """Sanity check that the pre-existing unconditional imports (Activity,
    Update, Onboarding) are still present and unconditional — this wave
    must not have accidentally gated any of them behind the new routing
    logic."""
    src = _read(_APP_JS)
    assert "import('./js/applicantActivity.js')" in src
    assert "import('./js/applicantUpdate.js').catch(() => null);" in src
    assert "import('./js/applicantOnboarding.js')" in src


# ══════════════════════════════════════════════════════════════════════════
# 4. Denylist hygiene (per the task's standing instruction)
# ══════════════════════════════════════════════════════════════════════════


#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text
#: (a prior agent broke CI by embedding them literally — see
#: test_applicant_round2_wave1_clickabletoasts.py for the same precaution).
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_files_are_denylist_clean():
    for path in (_HASH_ROUTER_JS, pathlib.Path(__file__)):
        text = path.read_text(encoding="utf-8").lower()
        for first, second in _DENYLIST_CODENAME_HALVES:
            codename = first + second
            assert codename not in text, f"denylist hit {codename!r} in {path}"
