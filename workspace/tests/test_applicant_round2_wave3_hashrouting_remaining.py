"""Regression coverage for the round 2 / wave 3 systemic-theme #7 FOLLOW-UP:
wiring the remaining 7 modal surfaces to ``hashRouter.js``.

``test_applicant_round2_wave3_hashrouting.py`` (already merged) built
``static/js/hashRouter.js`` and wired Portal (``#portal``) + Activity
(``#activity``) to it as proof surfaces. That commit's own report flagged
seven more surfaces as "one extra export line" away from the same
deep-linkability — this file covers that follow-up pass, confined to:

  - ``static/js/applicantDebug.js``   — token ``#debug``
  - ``static/js/applicantResults.js`` — token ``#results``
  - ``static/js/applicantUpdate.js``  — token ``#update``
  - ``static/js/applicantGallery.js`` — token ``#gallery``
  - ``static/js/applicantMind.js``    — token ``#mind``
  - ``static/js/applicantCompare.js`` — token ``#compare``
  - ``static/js/applicantChat.js``    — token ``#chat``

Each file grew the exact same shape ``applicantActivity.js`` / applicantPortal.js
established: import ``{ registerRoute, setHash, clearHash }`` from
``./hashRouter.js``; the existing internal ``_close()`` now also calls
``clearHash(token)``; a new ``export function closeApplicantX() { _close(); }``
mirrors the existing ``openApplicantX`` export (and is added to the module's
public object + ``window.applicant*Module``); the existing ``openApplicantX``
export grew an ``opts`` parameter and calls ``setHash(token)`` unless
``opts.skipHashUpdate`` is set; and ``registerRoute(token, { open:
openApplicantX, close: _close })`` runs at module-eval time. None of the 7
surfaces had a boot-time "auto-open" call site anywhere in ``app.js`` (unlike
Portal's one auto-land-on-boot caller) — confirmed by grepping
``static/app.js`` for each ``openApplicantX`` export name before writing this
suite — so, unlike Portal, none of them needed an extra ``skipHashUpdate``
guard wired in from outside the module itself.

Two testing strategies, matching the original wave-3 file's own stated
preference for real execution over text-regex wherever practical:

  1. ``applicantResults.js`` and ``applicantUpdate.js`` are loaded and RUN for
     real (not just text-matched) — their only DOM-heavy dependency is
     ``./ui.js`` (via ``./applicantCore.js``), which is redirected via the same
     ``node:module`` loader-hook substitution ``test_applicant_round1_missingkits.py``
     / ``test_applicant_round2_wave3_hashrouting.py`` established. Both files'
     import graphs are otherwise leaf-only (``applicantCore.js`` imports only
     ``ui.js``; ``applicantUpdateView.js`` imports nothing), so real execution is
     cheap and worth doing for at least these two.
  2. ``applicantDebug.js`` / ``applicantGallery.js`` / ``applicantMind.js`` /
     ``applicantCompare.js`` / ``applicantChat.js`` are verified the same way
     ``test_applicant_round2_wave2_redlinecta.py`` verifies ``documentLibrary.js``
     and the original wave-3 file verifies ``applicantPortal.js``: reading the
     actual source and asserting the exact lines exist, in context. (Their
     import graphs are in fact just as light as Results/Update's — this split
     is for breadth of technique per the task's stated preference, not because
     they were too heavy to execute.)

Every ``test_*`` here was verified failing (per the task's DoD) by temporarily
reverting the exact line(s) of source it protects, confirming the assertion
actually goes red, then restoring the original file (clean ``git diff``
afterward) before landing this file.
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
_DEBUG_JS = _JS_DIR / "applicantDebug.js"
_RESULTS_JS = _JS_DIR / "applicantResults.js"
_UPDATE_JS = _JS_DIR / "applicantUpdate.js"
_GALLERY_JS = _JS_DIR / "applicantGallery.js"
_MIND_JS = _JS_DIR / "applicantMind.js"
_COMPARE_JS = _JS_DIR / "applicantCompare.js"
_CHAT_JS = _JS_DIR / "applicantChat.js"
_APP_JS = _REPO / "static" / "app.js"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + location/history shim ──────────────────────────────────────
#
# Copied verbatim from test_applicant_round2_wave3_hashrouting.py's _DOM_SHIM
# (itself adapted from test_applicant_round1_missingkits.py) — kept as an
# exact duplicate rather than a shared import so this file has no test-to-test
# coupling and stays readable in isolation, matching this repo's existing
# convention of each wave's test file carrying its own copy of the shim.
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
globalThis.fetch = () => Promise.reject(new Error('no network in test shim'));
globalThis.AbortController = class AbortController { constructor(){ this.signal = { aborted:false }; } abort(){ this.signal.aborted = true; } };

class Loc {
  constructor(){ this._hash=''; this.pathname='/'; this.search=''; }
  get hash(){ return this._hash; }
  set hash(v){
    const nv = (v==null || v==='') ? '' : (String(v).startsWith('#') ? String(v) : '#'+v);
    if (nv === this._hash) return;
    this._hash = nv;
    win.dispatchEvent({ type: 'hashchange' });
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
  pushState(state, title, url){ globalThis.__pushStateCalls++; __loc._hash = __parseHashFromUrl(url); },
  replaceState(state, title, url){ __loc._hash = __parseHashFromUrl(url); },
};
globalThis.__simulateHashNav = function(newHash){ __loc.hash = newHash; };

const win = new WindowObj();
win.document = DOC;
win.location = __loc;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
win.history = globalThis.history;
globalThis.window = win;
"""

# ``applicantResults.js`` / ``applicantUpdate.js`` need ``./ui.js`` stubbed —
# same node:module loader-hook substitution technique the earlier waves
# established. `initModalA11y` returns a cleanup fn; `showToast`/`styledConfirm`
# are no-ops these two files don't actually invoke on the paths exercised below.
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
# 1. applicantResults.js — real production file, real execution
# ══════════════════════════════════════════════════════════════════════════


def test_results_self_registers_the_results_route(node_available):
    script = f"""
        await import('file://{_RESULTS_JS}');
        console.log(JSON.stringify({{ hasRoute: window.applicantHashRouter.hasRoute('results') }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"hasRoute": True}


def test_results_open_sets_hash_and_exposes_close(node_available):
    script = f"""
        const mod = await import('file://{_RESULTS_JS}');
        console.log(JSON.stringify({{ hasClose: typeof mod.closeApplicantResults === 'function' }}));
        await mod.openApplicantResults();
        console.log(JSON.stringify({{ hash: window.location.hash }}));
    """
    out_lines = _run_node_multi(script, with_ui_stub=True)
    assert out_lines[0] == {"hasClose": True}
    assert out_lines[1] == {"hash": "#results"}


def test_results_close_clears_hash_and_hides_modal(node_available):
    script = f"""
        const mod = await import('file://{_RESULTS_JS}');
        await mod.openApplicantResults();
        const hashWhileOpen = window.location.hash;
        const hiddenWhileOpen = document.getElementById('applicant-results-modal').classList.contains('hidden');
        mod.closeApplicantResults();
        const hashAfterClose = window.location.hash;
        const hiddenAfterClose = document.getElementById('applicant-results-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ hashWhileOpen, hiddenWhileOpen, hashAfterClose, hiddenAfterClose }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {
        "hashWhileOpen": "#results",
        "hiddenWhileOpen": False,
        "hashAfterClose": "",
        "hiddenAfterClose": True,
    }


def test_results_skip_hash_update_opt_out(node_available):
    """``opts.skipHashUpdate`` must suppress the setHash call, mirroring
    Portal/Activity's own opt-out contract, so a future boot-time auto-open
    caller (should one ever be added for Results) has the same escape hatch
    available without further changes to this file."""
    script = f"""
        const mod = await import('file://{_RESULTS_JS}');
        await mod.openApplicantResults({{ skipHashUpdate: true }});
        console.log(JSON.stringify({{ hash: window.location.hash }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"hash": ""}


def test_results_hashchange_deep_link_opens_the_real_modal(node_available):
    """End-to-end through the real file: a deep link arriving at boot opens
    the actual Results modal via the router, not just the isolated
    registration contract."""
    script = f"""
        await import('file://{_RESULTS_JS}');
        window.applicantHashRouter.initHashRouting();
        __simulateHashNav('#results');
        const openedHidden = document.getElementById('applicant-results-modal').classList.contains('hidden');
        __simulateHashNav('');
        const closedHidden = document.getElementById('applicant-results-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ openedHidden, closedHidden }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"openedHidden": False, "closedHidden": True}


# ══════════════════════════════════════════════════════════════════════════
# 2. applicantUpdate.js — real production file, real execution
# ══════════════════════════════════════════════════════════════════════════


def test_update_self_registers_the_update_route(node_available):
    script = f"""
        await import('file://{_UPDATE_JS}');
        console.log(JSON.stringify({{ hasRoute: window.applicantHashRouter.hasRoute('update') }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"hasRoute": True}


def test_update_open_sets_hash_and_exposes_close(node_available):
    script = f"""
        const mod = await import('file://{_UPDATE_JS}');
        console.log(JSON.stringify({{ hasClose: typeof mod.closeApplicantUpdate === 'function' }}));
        await mod.openApplicantUpdate();
        console.log(JSON.stringify({{ hash: window.location.hash }}));
    """
    out_lines = _run_node_multi(script, with_ui_stub=True)
    assert out_lines[0] == {"hasClose": True}
    assert out_lines[1] == {"hash": "#update"}


def test_update_close_clears_hash_and_hides_modal(node_available):
    script = f"""
        const mod = await import('file://{_UPDATE_JS}');
        await mod.openApplicantUpdate();
        const hashWhileOpen = window.location.hash;
        const hiddenWhileOpen = document.getElementById('applicant-update-modal').classList.contains('hidden');
        mod.closeApplicantUpdate();
        const hashAfterClose = window.location.hash;
        const hiddenAfterClose = document.getElementById('applicant-update-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ hashWhileOpen, hiddenWhileOpen, hashAfterClose, hiddenAfterClose }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {
        "hashWhileOpen": "#update",
        "hiddenWhileOpen": False,
        "hashAfterClose": "",
        "hiddenAfterClose": True,
    }


def test_update_hashchange_back_closes_the_real_modal(node_available):
    script = f"""
        await import('file://{_UPDATE_JS}');
        window.applicantHashRouter.initHashRouting();
        __simulateHashNav('#update');
        const openedHidden = document.getElementById('applicant-update-modal').classList.contains('hidden');
        __simulateHashNav('');
        const closedHidden = document.getElementById('applicant-update-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ openedHidden, closedHidden }}));
    """
    out = _run_node(script, with_ui_stub=True)
    assert out == {"openedHidden": False, "closedHidden": True}


def _run_node_multi(js_body: str, *, with_ui_stub: bool = False) -> list:
    """Like _run_node but returns every JSON line printed (not just the last),
    for scripts that log more than once."""
    parts = []
    if with_ui_stub:
        parts.append(_UI_STUB_LOADER)
    parts.append(_DOM_SHIM)
    parts.append(js_body)
    parts.append("process.exit(0);")
    script = "\n".join(parts)
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO, capture_output=True, timeout=20, text=True,
    )
    assert res.returncode == 0, f"node failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}"
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


# ══════════════════════════════════════════════════════════════════════════
# 3. applicantDebug.js / applicantGallery.js / applicantMind.js /
#    applicantCompare.js / applicantChat.js — source-level wiring, mirroring
#    how the original wave-3 file verifies applicantPortal.js (see its module
#    docstring): reading the actual production source and asserting the exact
#    lines exist, in context.
# ══════════════════════════════════════════════════════════════════════════

# (path, token, open export name, close export name, internal close fn name,
#  modal-open-opts-arg name used in the export's signature)
_SOURCE_SURFACES = [
    (_DEBUG_JS, "debug", "openApplicantDebug", "closeApplicantDebug"),
    (_GALLERY_JS, "gallery", "openApplicantGallery", "closeApplicantGallery"),
    (_MIND_JS, "mind", "openApplicantMind", "closeApplicantMind"),
    (_COMPARE_JS, "compare", "openApplicantCompare", "closeApplicantCompare"),
    (_CHAT_JS, "chat", "openApplicantChat", "closeApplicantChat"),
]


@pytest.mark.parametrize("path,token,open_name,close_name", _SOURCE_SURFACES)
def test_surface_imports_hashRouter(path, token, open_name, close_name):
    src = _read(path)
    assert "from './hashRouter.js'" in src
    assert "registerRoute" in src and "setHash" in src and "clearHash" in src


@pytest.mark.parametrize("path,token,open_name,close_name", _SOURCE_SURFACES)
def test_surface_registers_its_route_with_the_internal_close(path, token, open_name, close_name):
    src = _read(path)
    assert re.search(
        r"registerRoute\(\s*'" + re.escape(token) + r"'\s*,\s*\{\s*open:\s*" + re.escape(open_name)
        + r"\s*,\s*close:\s*_close\s*\}\s*\)",
        src,
    ), f"expected {path.name} to self-register {open_name!r} / _close under the {token!r} token"


@pytest.mark.parametrize("path,token,open_name,close_name", _SOURCE_SURFACES)
def test_surface_open_sets_hash_unless_skipped(path, token, open_name, close_name):
    src = _read(path)
    m = re.search(r"export async function " + re.escape(open_name) + r"\(opts\) \{(.*?)\n\}", src, re.S)
    assert m, f"expected {open_name}(opts) to accept an opts arg in {path.name}"
    body = m.group(1)
    assert f"setHash('{token}')" in body
    assert "skipHashUpdate" in body


@pytest.mark.parametrize("path,token,open_name,close_name", _SOURCE_SURFACES)
def test_surface_close_clears_hash_and_is_exported(path, token, open_name, close_name):
    src = _read(path)
    # The internal _close() must call clearHash(token) somewhere in its body —
    # search from its definition up to the next top-level function/const to
    # scope the match to just that function (mirrors the exact-body regex the
    # original wave-3 file uses for applicantPortal.js's _close()).
    m = re.search(r"function _close\(\) \{(.*?)\n\}", src, re.S)
    assert m, f"expected the existing _close() to still exist in {path.name}"
    assert f"clearHash('{token}')" in m.group(1), f"{path.name}'s _close() must clearHash({token!r})"
    assert re.search(
        r"export function " + re.escape(close_name) + r"\(\)\s*\{\s*_close\(\);\s*\}",
        src,
    ), f"expected a {close_name} export mirroring {open_name} in {path.name}"


@pytest.mark.parametrize("path,token,open_name,close_name", _SOURCE_SURFACES)
def test_surface_close_exposed_on_the_public_module_object(path, token, open_name, close_name):
    src = _read(path)
    # The module object literal (e.g. `const applicantDebugModule = { ... }`)
    # must list the new close export alongside the pre-existing open export.
    m = re.search(r"const applicant\w+Module = \{([^}]*)\}", src, re.S)
    assert m, f"expected a module object literal in {path.name}"
    body = m.group(1)
    assert open_name in body
    assert close_name in body


# ══════════════════════════════════════════════════════════════════════════
# 4. No boot-time auto-open call site exists for any of these 7 tokens — the
#    one thing that WOULD additionally require an outside `skipHashUpdate`
#    guard (the way app.js's Portal auto-land call does). Confirms the task's
#    own "check if any of these 7 need the same guard" instruction: none do.
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "open_name",
    [
        "openApplicantDebug", "openApplicantResults", "openApplicantUpdate",
        "openApplicantGallery", "openApplicantMind", "openApplicantCompare",
        "openApplicantChat",
    ],
)
def test_app_js_has_no_auto_open_call_site_for_this_surface(open_name):
    """Unlike Portal's one boot-time auto-land caller (guarded with
    `skipHashUpdate: true` in app.js), none of these 7 surfaces are ever
    opened automatically from app.js — every call site is a real user click
    (a launcher) or the hash router itself replaying a deep link. If a future
    change ever adds an automatic open here, it must thread `skipHashUpdate`
    through the same way Portal's does; this test simply guards that no such
    ungated call site has crept in unnoticed."""
    src = _read(_APP_JS)
    assert open_name not in src, (
        f"{open_name} is now called from app.js — if this is a new boot-time "
        "auto-open, it must pass { skipHashUpdate: true } the way Portal's does"
    )


# ══════════════════════════════════════════════════════════════════════════
# 5. Denylist hygiene (per the task's standing instruction)
# ══════════════════════════════════════════════════════════════════════════

_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for first, second in _DENYLIST_CODENAME_HALVES:
        codename = first + second
        assert codename not in text, f"denylist hit {codename!r} in {pathlib.Path(__file__).name}"
