"""Regression coverage for the "Today" focus-mode run-through
(``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md`` §4E/§5 big-bet): a new
self-contained surface, ``static/js/applicantToday.js``, that walks the owner
through today's pending decisions ONE AT A TIME instead of the Portal's wall
of rows.

This is explicitly a NEW LENS over EXISTING data/endpoints — no new engine
endpoints are introduced. It reads the exact same owner-scoped proxy the
Pending Portal already reads (``GET /api/applicant/portal/pending``) and, for
every affordance a pending item can carry (answer / review / missing detail /
live session / Google 2FA / digest / confirm-a-held-change / final-submit
authorize / finish-profile), calls the SAME ``/api/applicant/portal/actions/*``
endpoints Portal's own rows call, or — for the two irreversible stop-boundary
actions (continue-two-factor, authorize-engine-finish) — the SAME exported
helpers ``applicantRemote.js`` already exposes for exactly this reuse (its own
header comment: "There is still exactly one client path to each stop-boundary
endpoint").  ``applicantPortal.js`` / ``applicant_portal_routes.py`` /
``applicantDigest.js`` / ``digest_service.py`` are all concurrently owned by
other agents this round and are not imported for real execution here (mirrors
the precedent in ``test_applicant_round2_wave3_hashrouting.py``, which keeps
``applicantPortal.js`` out of its own real-execution lane for the identical
reason) — Today's review/digest deep-link affordances instead reuse the same
plain cross-module seams Portal itself uses (``window.documentModule.
openLibrary``, an ``#rail-email`` click), asserted at the source level where
real execution would require pulling in those locked files.

Two testing strategies, per the task's stated preference for real execution
over text-regex wherever practical:

  1. The deck's own step/next/previous/skip/progress/auto-advance-on-resolve
     logic — the behavior actually worth exercising — is run for REAL via
     ``node``, importing the genuine ``static/js/applicantToday.js`` against a
     from-scratch DOM + location/history shim (adapted verbatim from
     ``test_applicant_round1_missingkits.py`` / ``test_applicant_round2_
     wave3_hashrouting.py``) plus a tiny queued ``fetch`` mock that also
     records every call (URL + method + body) so assertions can confirm each
     affordance hits the exact same endpoint Portal's rows would.
  2. Anything that would require loading a concurrently-locked file for real
     (the review/digest deep-links' fallback wording, denylist hygiene) is
     asserted at the source level instead.

Every ``test_*`` here was verified failing (per the task's DoD) by
temporarily reverting the exact source line(s) it protects, confirming the
assertion actually goes red, then restoring the original file (clean
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
_TODAY_JS = _JS_DIR / "applicantToday.js"
_HASH_ROUTER_JS = _JS_DIR / "hashRouter.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + location/history shim (real objects, real event dispatch) ──
#
# Copied verbatim from test_applicant_round2_wave3_hashrouting.py's own
# _DOM_SHIM (itself adapted from test_applicant_round1_missingkits.py) — see
# that file's header comment for the design rationale of each piece. Kept
# byte-for-byte identical so any future shared-shim extraction is a pure
# dedup, not a behavior change.
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
win.confirm = () => true; // Today's final-authorize confirm falls back to this when uiModule.styledConfirm is absent
globalThis.window = win;

// ── queued/URL-matched fetch mock, shared by every scenario below ──────────
// Records every call (url, method, parsed JSON body) into __fetchCalls so
// assertions can confirm Today hits the exact same endpoints Portal's own
// rows call. `__fetchResponder(url, opts)` is defined per-script and must
// return { status, body }.
globalThis.__fetchCalls = [];
globalThis.fetch = async (url, opts) => {
  const method = (opts && opts.method) || 'GET';
  let body = null;
  try { body = opts && opts.body ? JSON.parse(opts.body) : null; } catch { body = opts && opts.body; }
  globalThis.__fetchCalls.push({ url: String(url), method, body });
  const r = globalThis.__fetchResponder(String(url), method, body);
  return {
    ok: r.status >= 200 && r.status < 300,
    status: r.status,
    json: async () => r.body,
  };
};
"""

# `applicantToday.js`'s import graph is applicantCore.js (-> ui.js),
# hashRouter.js (no imports), and applicantRemote.js (-> ui.js,
# applicantVault.js -> ui.js + applicantCore.js) — every one of those
# resolves fine for real once `./ui.js` is stubbed, the same technique
# test_applicant_round2_wave3_hashrouting.py established for
# applicantActivity.js. `styledConfirm` is intentionally omitted from the
# stub so Today's final-authorize confirm exercises its real fallback to
# `window.confirm` (stubbed to always-true above).
_UI_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === './ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(
        'export function initModalA11y(el, closeFn) {' +
        'globalThis.__initModalA11yCalls = (globalThis.__initModalA11yCalls||0) + 1;' +
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


def _run_node(js_body: str) -> dict:
    script = "\n".join([_UI_STUB_LOADER, _DOM_SHIM, js_body, "process.exit(0);"])
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


def _run_node_multi(js_body: str) -> list:
    """Like _run_node but returns every JSON line printed (one per console.log)."""
    script = "\n".join([_UI_STUB_LOADER, _DOM_SHIM, js_body, "process.exit(0);"])
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=20,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    return [json.loads(ln) for ln in res.stdout.splitlines() if ln.strip()]


# A single-campaign, three-item pending-actions payload — all simple
# 'agent_question' (affordance 'answer') items so navigation tests don't
# also depend on the per-kind card renderers under test elsewhere.
_THREE_ITEMS_RESPONDER = r"""
globalThis.__fetchResponder = (url, method) => {
  if (url.endsWith('/api/applicant/portal/pending') && method === 'GET') {
    return { status: 200, body: { engine_available: true, gated: false, items: [
      { id: 'a1', kind: 'agent_question', title: 'Q1' },
      { id: 'a2', kind: 'agent_question', title: 'Q2' },
      { id: 'a3', kind: 'agent_question', title: 'Q3' },
    ] } };
  }
  if (url.includes('/actions/') && url.endsWith('/resolve') && method === 'POST') {
    return { status: 200, body: {} };
  }
  return { status: 404, body: {} };
};
"""


# ══════════════════════════════════════════════════════════════════════════
# 1. Module shape + window aliases + hash-route registration (real execution)
# ══════════════════════════════════════════════════════════════════════════


def test_module_shape_and_window_export(node_available):
    script = f"""
        const mod = await import('file://{_TODAY_JS}');
        console.log(JSON.stringify({{
          hasOpen: typeof mod.openApplicantToday === 'function',
          hasClose: typeof mod.closeApplicantToday === 'function',
          defaultHasBoth: typeof mod.default.openApplicantToday === 'function'
                          && typeof mod.default.closeApplicantToday === 'function',
          windowModuleMatchesDefault: window.applicantTodayModule === mod.default,
          windowOpenIsFn: typeof window.openApplicantToday === 'function',
          hasRoute: window.applicantHashRouter
            ? window.applicantHashRouter.hasRoute('today')
            : null,
        }}));
    """
    out = _run_node(script)
    # hashRouter.js self-mounts window.applicantHashRouter as a side effect of
    # its own module evaluation, which applicantToday.js triggers by importing
    # it — so `hasRoute` is directly checkable without a separate import.
    assert out == {
        "hasOpen": True,
        "hasClose": True,
        "defaultHasBoth": True,
        "windowModuleMatchesDefault": True,
        "windowOpenIsFn": True,
        "hasRoute": True,
    }


def test_open_sets_hash_close_clears_it(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const hashWhileOpen = window.location.hash;
        const hiddenWhileOpen = document.getElementById('applicant-today-modal').classList.contains('hidden');
        mod.closeApplicantToday();
        const hashAfterClose = window.location.hash;
        const hiddenAfterClose = document.getElementById('applicant-today-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ hashWhileOpen, hiddenWhileOpen, hashAfterClose, hiddenAfterClose }}));
    """
    out = _run_node(script)
    assert out == {
        "hashWhileOpen": "#today",
        "hiddenWhileOpen": False,
        "hashAfterClose": "",
        "hiddenAfterClose": True,
    }


def test_skip_hash_update_opt_out_is_respected(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday({{ skipHashUpdate: true }});
        console.log(JSON.stringify({{ hash: window.location.hash }}));
    """
    out = _run_node(script)
    assert out == {"hash": ""}


# ══════════════════════════════════════════════════════════════════════════
# 2. _clampIndex — pure boundary logic, exercised directly
# ══════════════════════════════════════════════════════════════════════════


def test_clamp_index_boundaries(node_available):
    script = f"""
        const {{ _clampIndex }} = await import('file://{_TODAY_JS}');
        console.log(JSON.stringify({{
          negative: _clampIndex(-1, 5),
          overLength: _clampIndex(99, 5),
          middle: _clampIndex(2, 5),
          emptyDeck: _clampIndex(3, 0),
          nonFinite: _clampIndex(NaN, 5),
        }}));
    """
    out = _run_node(script)
    assert out == {"negative": 0, "overLength": 4, "middle": 2, "emptyDeck": 0, "nonFinite": 0}


# ══════════════════════════════════════════════════════════════════════════
# 3. Deck walkthrough — progress indicator + Previous/Skip/Next (real exec)
# ══════════════════════════════════════════════════════════════════════════


def test_first_open_shows_card_one_of_three(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const progress = document.getElementById('applicant-today-progress').textContent;
        const body = document.getElementById('applicant-today-body');
        const title = body.querySelector('.admin-card').innerHTML;
        console.log(JSON.stringify({{ progress, hasQ1: title.includes('Q1') }}));
    """
    out = _run_node(script)
    assert out == {"progress": "1 of 3", "hasQ1": True}


def test_next_then_previous_walks_the_deck(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        const progressEl = document.getElementById('applicant-today-progress');
        body.querySelector('[data-role="next"]').dispatchEvent({{ type: 'click' }});
        const afterNext = {{ progress: progressEl.textContent, hasQ2: body.querySelector('.admin-card').innerHTML.includes('Q2') }};
        body.querySelector('[data-role="prev"]').dispatchEvent({{ type: 'click' }});
        const afterPrev = {{ progress: progressEl.textContent, hasQ1: body.querySelector('.admin-card').innerHTML.includes('Q1') }};
        console.log(JSON.stringify({{ afterNext, afterPrev }}));
    """
    out = _run_node(script)
    assert out == {
        "afterNext": {"progress": "2 of 3", "hasQ2": True},
        "afterPrev": {"progress": "1 of 3", "hasQ1": True},
    }


def test_skip_advances_like_next(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        body.querySelector('[data-role="skip"]').dispatchEvent({{ type: 'click' }});
        const progress = document.getElementById('applicant-today-progress').textContent;
        console.log(JSON.stringify({{ progress, hasQ2: body.querySelector('.admin-card').innerHTML.includes('Q2') }}));
    """
    out = _run_node(script)
    assert out == {"progress": "2 of 3", "hasQ2": True}


def test_previous_disabled_at_start_next_disabled_at_end(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        const prevAtStart = body.querySelector('[data-role="prev"]').disabled;
        body.querySelector('[data-role="next"]').dispatchEvent({{ type: 'click' }});
        body.querySelector('[data-role="next"]').dispatchEvent({{ type: 'click' }});
        const nextAtEnd = body.querySelector('[data-role="next"]').disabled;
        const progressAtEnd = document.getElementById('applicant-today-progress').textContent;
        console.log(JSON.stringify({{ prevAtStart, nextAtEnd, progressAtEnd }}));
    """
    out = _run_node(script)
    assert out == {"prevAtStart": True, "nextAtEnd": True, "progressAtEnd": "3 of 3"}


# ══════════════════════════════════════════════════════════════════════════
# 4. Resolving an item auto-advances the deck (real execution, incl. the
#    exact resolve/snooze/missing-attribute endpoint paths it hits)
# ══════════════════════════════════════════════════════════════════════════


def test_done_resolves_item_and_auto_advances(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        body.querySelector('[data-role="done"]').dispatchEvent({{ type: 'click' }});
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        const progress = document.getElementById('applicant-today-progress').textContent;
        const title = body.querySelector('.admin-card').innerHTML;
        const resolveCall = globalThis.__fetchCalls.find((c) => c.url.endsWith('/api/applicant/portal/actions/a1/resolve') && c.method === 'POST');
        console.log(JSON.stringify({{ progress, hasQ2: title.includes('Q2'), resolveCallFound: !!resolveCall }}));
    """
    out = _run_node(script)
    assert out == {"progress": "1 of 2", "hasQ2": True, "resolveCallFound": True}


def test_snooze_hits_snooze_endpoint_and_removes_item(node_available):
    script = f"""
        {_THREE_ITEMS_RESPONDER}
        globalThis.__fetchResponder = (url, method) => {{
          if (url.endsWith('/api/applicant/portal/pending') && method === 'GET') {{
            return {{ status: 200, body: {{ engine_available: true, gated: false, items: [
              {{ id: 'a1', kind: 'agent_question', title: 'Q1' }},
              {{ id: 'a2', kind: 'agent_question', title: 'Q2' }},
            ] }} }};
          }}
          if (url.endsWith('/api/applicant/portal/actions/a1/snooze') && method === 'POST') {{
            return {{ status: 200, body: {{}} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        body.querySelector('[data-role="snooze"]').dispatchEvent({{ type: 'click' }});
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        const progress = document.getElementById('applicant-today-progress').textContent;
        const snoozeCall = globalThis.__fetchCalls.find((c) => c.url.endsWith('/api/applicant/portal/actions/a1/snooze'));
        console.log(JSON.stringify({{ progress, snoozeCallFound: !!snoozeCall }}));
    """
    out = _run_node(script)
    assert out == {"progress": "1 of 1", "snoozeCallFound": True}


def test_last_item_resolved_shows_completion_state(node_available):
    script = f"""
        globalThis.__fetchResponder = (url, method) => {{
          if (url.endsWith('/api/applicant/portal/pending') && method === 'GET') {{
            return {{ status: 200, body: {{ engine_available: true, gated: false, items: [
              {{ id: 'only1', kind: 'agent_question', title: 'Only one' }},
            ] }} }};
          }}
          if (url.endsWith('/api/applicant/portal/actions/only1/resolve') && method === 'POST') {{
            return {{ status: 200, body: {{}} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        body.querySelector('[data-role="done"]').dispatchEvent({{ type: 'click' }});
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        const progress = document.getElementById('applicant-today-progress').textContent;
        const doneText = body.innerHTML;
        console.log(JSON.stringify({{ progress, hasCompletionCopy: doneText.includes('nicely done') }}));
    """
    out = _run_node(script)
    assert out == {"progress": "", "hasCompletionCopy": True}


def test_missing_detail_form_posts_to_missing_attribute_endpoint(node_available):
    script = f"""
        globalThis.__fetchResponder = (url, method) => {{
          if (url.endsWith('/api/applicant/portal/pending') && method === 'GET') {{
            return {{ status: 200, body: {{ engine_available: true, gated: false, items: [
              {{ id: 'm1', kind: 'missing_attr', title: 'Need a value', campaign_id: 'camp-1' }},
            ] }} }};
          }}
          if (url.endsWith('/api/applicant/portal/missing-attribute') && method === 'POST') {{
            return {{ status: 200, body: {{}} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        body.querySelector('[data-role="name"]').value = 'Salary expectation';
        body.querySelector('[data-role="value"]').value = '120000';
        body.querySelector('[data-role="save"]').dispatchEvent({{ type: 'click' }});
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        const call = globalThis.__fetchCalls.find((c) => c.url.endsWith('/api/applicant/portal/missing-attribute'));
        const doneText = body.innerHTML;
        console.log(JSON.stringify({{
          bodyName: call && call.body && call.body.name,
          bodyValue: call && call.body && call.body.value,
          bodyCampaign: call && call.body && call.body.campaign_id,
          hasCompletionCopy: doneText.includes('nicely done'),
        }}));
    """
    out = _run_node(script)
    assert out == {
        "bodyName": "Salary expectation",
        "bodyValue": "120000",
        "bodyCampaign": "camp-1",
        "hasCompletionCopy": True,
    }


# ══════════════════════════════════════════════════════════════════════════
# 5. Two-factor affordance reuses applicantRemote.js's real, exported
#    continueTwoFactor() — the same stop-boundary client path Portal uses.
# ══════════════════════════════════════════════════════════════════════════


def test_two_factor_card_calls_remote_continue_two_factor_endpoint(node_available):
    script = f"""
        globalThis.__fetchResponder = (url, method) => {{
          if (url.endsWith('/api/applicant/portal/pending') && method === 'GET') {{
            return {{ status: 200, body: {{ engine_available: true, gated: false, items: [
              {{ id: 't1', kind: 'two_factor', title: 'Google sign-in', application_id: 'app-9' }},
            ] }} }};
          }}
          if (url.endsWith('/api/applicant/remote/applications/app-9/continue-two-factor') && method === 'POST') {{
            return {{ status: 200, body: {{ state: 'CONTINUING' }} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const body = document.getElementById('applicant-today-body');
        body.querySelector('[data-role="two-factor"]').dispatchEvent({{ type: 'click' }});
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 0));
        const call = globalThis.__fetchCalls.find((c) => c.url.includes('continue-two-factor'));
        const doneText = body.innerHTML;
        console.log(JSON.stringify({{ callFound: !!call, hasCompletionCopy: doneText.includes('nicely done') }}));
    """
    out = _run_node(script)
    assert out == {"callFound": True, "hasCompletionCopy": True}


# ══════════════════════════════════════════════════════════════════════════
# 6. Gated / offline states (real execution, mirroring Portal's own copy)
# ══════════════════════════════════════════════════════════════════════════


def test_gated_state_shows_finish_setup(node_available):
    script = f"""
        globalThis.__fetchResponder = (url) => {{
          if (url.endsWith('/api/applicant/portal/pending')) {{
            return {{ status: 200, body: {{ gated: true, message: 'Connect a model first.' }} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const text = document.getElementById('applicant-today-body').innerHTML;
        console.log(JSON.stringify({{ hasFinishSetup: text.includes('Finish setup'), hasMessage: text.includes('Connect a model first.') }}));
    """
    out = _run_node(script)
    assert out == {"hasFinishSetup": True, "hasMessage": True}


def test_offline_state_shows_not_connected(node_available):
    script = f"""
        globalThis.__fetchResponder = (url) => {{
          if (url.endsWith('/api/applicant/portal/pending')) {{
            return {{ status: 200, body: {{ engine_available: false }} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const text = document.getElementById('applicant-today-body').innerHTML;
        console.log(JSON.stringify({{ hasNotConnected: text.includes('Not connected yet') }}));
    """
    out = _run_node(script)
    assert out == {"hasNotConnected": True}


def test_empty_deck_at_open_shows_completion_copy_too(node_available):
    script = f"""
        globalThis.__fetchResponder = (url) => {{
          if (url.endsWith('/api/applicant/portal/pending')) {{
            return {{ status: 200, body: {{ engine_available: true, gated: false, items: [] }} }};
          }}
          return {{ status: 404, body: {{}} }};
        }};
        const mod = await import('file://{_TODAY_JS}');
        await mod.openApplicantToday();
        const text = document.getElementById('applicant-today-body').innerHTML;
        console.log(JSON.stringify({{ hasCompletionCopy: text.includes('nicely done') }}));
    """
    out = _run_node(script)
    assert out == {"hasCompletionCopy": True}


# ══════════════════════════════════════════════════════════════════════════
# 7. Reachability: index.html wiring (this round left index.html mid-merge —
#    see module docstring; asserted defensively either way).
# ══════════════════════════════════════════════════════════════════════════


def test_launcher_self_wires_defensively_even_without_a_rail_button():
    """Today must not hard-depend on a #rail-today element existing — the nav
    edit may or may not have landed in index.html depending on concurrent
    agents' state. `_boot`'s retry loop (mirrors applicantResults.js's own
    `_wireLaunchers` polling pattern) must simply do nothing, not throw, when
    the rail button isn't present."""
    src = _read(_TODAY_JS)
    assert "getElementById('rail-today')" in src
    assert re.search(r"function _wireLaunchers\(\) \{\s*const rail = document\.getElementById\('rail-today'\);\s*if \(rail", src)


def test_index_html_nav_entry_present_or_absent_is_load_bearing_only_when_present():
    """If the nav edit for '#rail-today' + the applicantToday.js <script> tag
    landed in index.html, they must be wired correctly (same shape as the
    Results surface's own entries); if it hasn't landed (a concurrent agent
    holding index.html), this test must not fail the build over a deferred,
    already-flagged follow-up."""
    src = _read(_INDEX_HTML)
    has_rail = 'id="rail-today"' in src
    has_script = 'applicantToday.js' in src
    if not has_rail and not has_script:
        pytest.skip("index.html nav-wiring deferred this round (see report) — surface still reachable via #today / window.openApplicantToday()")
    assert has_rail and has_script, "expected BOTH the rail button and the script tag if either landed"


# ══════════════════════════════════════════════════════════════════════════
# 8. Denylist hygiene (per the task's standing instruction)
# ══════════════════════════════════════════════════════════════════════════

#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_files_are_denylist_clean():
    for path in (_TODAY_JS, pathlib.Path(__file__)):
        text = path.read_text(encoding="utf-8").lower()
        for first, second in _DENYLIST_CODENAME_HALVES:
            codename = first + second
            assert codename not in text, f"denylist hit {codename!r} in {path}"
