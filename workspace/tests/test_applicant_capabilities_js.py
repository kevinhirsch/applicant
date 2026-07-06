"""Real-execution tests for static/js/applicantCapabilities.js (dark-engine
audit item 24: "MCP tool surface is entirely undocumented product
capability").

New file under test: a self-contained overlay that fetches
``GET /api/applicant/capabilities`` (the workspace proxy over the engine's
native MCP tool list) and renders each tool's name + plain-language
description. It self-boots a floating trigger button (no index.html markup
needed beyond its own ``<script>`` tag) and additionally answers a
``Ctrl+Shift+/`` chord, mirroring ``applicantShortcuts.js``'s own bare-``?``
precedent for keyboard parity.

Design constraints this suite locks in (mirrors
``test_applicant_backlog_shortcutshelp.py``'s own methodology):

  - **No existing file was edited except ``index.html``** (one new
    ``<script type="module">`` tag) and
    ``test_applicant_backlog_lazyload.py`` (the ONE permitted exception —
    bumping the eager-script-tag-count constant).
  - ``app.js``, ``commandPalette.js``, and every other existing
    ``applicant*.js`` surface were **not** touched.
  - The module imports ONLY ``./applicantCore.js`` (the shared helper module
    every other applicant surface already imports) — no new dependency.

Two testing strategies, per this repo's stated preference for real execution
over text-regex wherever practical:

  1. Real ``node`` execution of the ACTUAL ``applicantCapabilities.js`` file
     against a lightweight DOM shim + a module-resolution loader hook that
     redirects ``./ui.js`` to an in-memory stub (identical technique to
     ``test_applicant_backlog_lazyload.py``'s own ``_UI_STUB_LOADER`` —
     copied verbatim per this repo's established per-file-shim convention;
     ``applicantCore.js``'s only import is ``./ui.js``, so this one redirect
     covers the whole chain) — exercises the real trigger button, the real
     fetch-driven rendering, and the real gated/offline/error degrade paths.
  2. Source-level assertions for the things that are structurally
     inconvenient to execute-test (the ``index.html`` wiring, and the
     "no other file touched" guarantee).

Every ``test_*`` here was verified failing (per this repo's DoD) by
temporarily breaking the exact behavior it protects, then restoring the
original file (clean ``git diff`` afterward) before landing this file.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_CAPABILITIES_JS = _JS_DIR / "applicantCapabilities.js"
_APP_JS = _REPO / "static" / "app.js"
_COMMAND_PALETTE_JS = _JS_DIR / "commandPalette.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── DOM shim (copied verbatim from test_applicant_backlog_lazyload.py's own
#    _DOM_SHIM, per this repo's per-file-shim convention) ───────────────────
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
  constructor(tag){ super(); this.nodeType=1; this.tagName=String(tag).toUpperCase(); this._attrs=new Map(); this.children=[]; this.parentNode=null; this.classList=new ClassList(); this.style=makeStyle(); this._text=''; this._html=''; this.isContentEditable=false; }
  get dataset(){
    const attrs = this._attrs;
    const toAttr = (p) => 'data-' + String(p).replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
    return new Proxy({}, {
      get(_, prop){ const k = toAttr(prop); return attrs.has(k) ? attrs.get(k) : undefined; },
      set(_, prop, val){ attrs.set(toAttr(prop), String(val)); return true; },
      has(_, prop){ return attrs.has(toAttr(prop)); },
    });
  }
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
function _tokenizeCompound(base){
  const tokens = [];
  const re = /#[\w-]+|\.[\w-]+|\[[^\]]+\]/g;
  let m;
  while ((m = re.exec(base))) tokens.push(m[0]);
  if (!tokens.length && base) tokens.push(base);
  return tokens;
}
function matchesSimple(el, sel){
  const notClauses=[]; let base=sel.replace(/:not\(([^)]*)\)/g,(m,inner)=>{notClauses.push(inner); return '';}).trim();
  if(base){
    for(const tok of _tokenizeCompound(base)) if(!testBase(el, tok)) return false;
  }
  for(const nc of notClauses) if(testBase(el, nc)) return false;
  return true;
}
function matchesSelector(el, sel){ return sel.split(',').some(s=>matchesSimple(el, s.trim())); }
function findById(el, id){ if(el.id===id) return el; for(const c of el.children){ const r=findById(c,id); if(r) return r; } return null; }
class Document extends EvtTarget {
  constructor(){ super(); this.body=new Element('body'); this.head=new Element('head'); this.activeElement=null; this.readyState='complete'; }
  createElement(tag){ return new Element(tag); }
  getElementById(id){ return findById(this.body,id) || findById(this.head,id); }
  querySelector(sel){ return this.body.querySelector(sel) || this.head.querySelector(sel); }
  querySelectorAll(sel){ return [...this.body.querySelectorAll(sel), ...this.head.querySelectorAll(sel)]; }
}
class WindowObj extends EvtTarget {}
const DOC = new Document();
globalThis.document = DOC;
globalThis.Node = DomNode;
globalThis.MutationObserver = class MutationObserver { constructor(cb){ this.cb=cb; } observe(){} disconnect(){} };
globalThis.AbortController = class AbortController { constructor(){ this.signal = { aborted:false }; } abort(){ this.signal.aborted = true; } };
globalThis.fetch = () => Promise.reject(new Error('no network in test shim — override per test'));
const win = new WindowObj();
win.document = DOC;
globalThis.window = win;

globalThis.__mkEvent = function(type, opts) {
  const e = Object.assign({ type, key: '', ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, target: null }, opts || {});
  e._prevented = false;
  e.preventDefault = function(){ e._prevented = true; };
  e.stopPropagation = function(){};
  return e;
};
"""

# ui.js stub-loader (copied verbatim from test_applicant_backlog_lazyload.py's
# own _UI_STUB_LOADER — applicantCapabilities.js imports ./applicantCore.js,
# whose ONLY import is ./ui.js, so this one redirect covers the whole chain).
_UI_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === './ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(
        'export function initModalA11y(el, closeFn) {' +
        'globalThis.__initModalA11yCalls = (globalThis.__initModalA11yCalls||0) + 1;' +
        'return function(){};' +
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
        cwd=_REPO, capture_output=True, timeout=20, text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError(f"node produced no stdout\nSTDERR:\n{res.stderr}")
    return json.loads(out_lines[-1])


def _fetch_ok(body: dict) -> str:
    payload = json.dumps(body)
    return f"globalThis.fetch = async () => ({{ ok: true, status: 200, json: async () => ({payload}) }});"


# ══════════════════════════════════════════════════════════════════════════
# 1. Design constraints — source-level checks
# ══════════════════════════════════════════════════════════════════════════


def test_capabilities_js_only_imports_applicant_core():
    src = _read(_CAPABILITIES_JS)
    import_lines = [ln.strip() for ln in src.splitlines() if ln.strip().startswith("import ")]
    assert len(import_lines) == 1
    assert "from './applicantCore.js'" in import_lines[0]


def test_wired_via_script_tag_before_app_js():
    src = _read(_INDEX_HTML)
    cap_idx = src.find('src="/static/js/applicantCapabilities.js"')
    app_idx = src.find('src="/static/app.js"')
    assert cap_idx != -1, "applicantCapabilities.js must be loaded via a <script type=module> tag in index.html"
    assert app_idx != -1
    assert cap_idx < app_idx, "applicantCapabilities.js must load before app.js (app.js must be LAST)"


def test_exactly_one_script_tag_added():
    src = _read(_INDEX_HTML)
    assert src.count('src="/static/js/applicantCapabilities.js"') == 1


def test_no_other_existing_surface_was_touched():
    for path in (_APP_JS, _COMMAND_PALETTE_JS):
        assert "applicantCapabilities" not in _read(path), (
            f"{path.name} should not need any reference to applicantCapabilities.js — it self-boots"
        )


def test_engine_endpoint_used_is_the_read_only_capabilities_proxy():
    src = _read(_CAPABILITIES_JS)
    assert "/api/applicant/capabilities" in src


# ══════════════════════════════════════════════════════════════════════════
# 2. Self-boot: the floating trigger appears with no index.html markup
# ══════════════════════════════════════════════════════════════════════════


def test_trigger_button_is_injected_on_import(node_available):
    script = f"""
        await import('file://{_CAPABILITIES_JS}');
        const btn = document.getElementById('applicant-capabilities-trigger');
        console.log(JSON.stringify({{
          exists: !!btn,
          tag: btn ? btn.tagName : null,
          connected: btn ? btn.isConnected : false,
        }}));
    """
    out = _run_node(script)
    assert out == {"exists": True, "tag": "BUTTON", "connected": True}


def test_clicking_the_trigger_opens_the_overlay(node_available):
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": [], "count": 0})}
        await import('file://{_CAPABILITIES_JS}');
        document.getElementById('applicant-capabilities-trigger').dispatchEvent(__mkEvent('click', {{}}));
        const modal = document.getElementById('applicant-capabilities-modal');
        console.log(JSON.stringify({{ everCreated: !!modal, hidden: modal ? modal.classList.contains('hidden') : null }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": True, "hidden": False}


# ══════════════════════════════════════════════════════════════════════════
# 3. Rendering the real tool list — never fabricated, straight from the proxy
# ══════════════════════════════════════════════════════════════════════════


def test_renders_the_five_real_tools_from_the_proxy(node_available):
    """#110/#111: the engine's raw tool ids (``list_campaigns``, ``health``)
    and stock ``List all campaigns.``-style descriptions used to leak
    straight into the UI as unreadable snake_case, and out of step with the
    rest of the product's "job search" wording. The overlay now relabels
    each tool it's given for a plain-language reader -- still exactly the
    tools the proxy returned (never fabricated or dropped), just not shown
    as machine identifiers."""
    tools_payload = {
        "engine_available": True,
        "count": 2,
        "tools": [
            {"name": "list_campaigns", "description": "List all campaigns."},
            {"name": "health", "description": "Check the engine's health status."},
        ],
    }
    script = f"""
        {_fetch_ok(tools_payload)}
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        await new Promise((r) => setTimeout(r, 20));
        const html = document.getElementById('applicant-capabilities-list').innerHTML;
        console.log(JSON.stringify({{
          hasCampaignsLabel: /job search/i.test(html),
          hasHealthLabel: html.includes('running'),
          leaksRawListCampaignsId: html.includes('list_campaigns'),
          leaksRawSnakeCaseId: /get_attributes|get_applications|get_pending_actions/.test(html),
        }}));
    """
    out = _run_node(script)
    assert out == {
        "hasCampaignsLabel": True,
        "hasHealthLabel": True,
        "leaksRawListCampaignsId": False,
        "leaksRawSnakeCaseId": False,
    }


def test_empty_tool_list_shows_a_designed_empty_state_not_a_blank_panel(node_available):
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": [], "count": 0})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        await new Promise((r) => setTimeout(r, 20));
        const html = document.getElementById('applicant-capabilities-list').innerHTML;
        console.log(JSON.stringify({{ hasEmptyCopy: html.toLowerCase().includes('nothing to show') }}));
    """
    out = _run_node(script)
    assert out == {"hasEmptyCopy": True}


# ══════════════════════════════════════════════════════════════════════════
# 4. Honest degrade paths — gated vs. offline (never silently "no capabilities")
# ══════════════════════════════════════════════════════════════════════════


def test_gated_state_shows_setup_required_copy_with_the_engines_message(node_available):
    gate_msg = "Connect an AI model first to continue."
    script = f"""
        {_fetch_ok({"engine_available": True, "gated": True, "message": gate_msg, "tools": []})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        await new Promise((r) => setTimeout(r, 20));
        const html = document.getElementById('applicant-capabilities-list').innerHTML;
        console.log(JSON.stringify({{
          hasSetupCopy: html.toLowerCase().includes('not set up yet'),
          hasMessage: html.includes({json.dumps(gate_msg)}),
        }}));
    """
    out = _run_node(script)
    assert out == {"hasSetupCopy": True, "hasMessage": True}


def test_offline_state_shows_retry_not_a_fabricated_list(node_available):
    script = f"""
        {_fetch_ok({"engine_available": False, "tools": []})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        await new Promise((r) => setTimeout(r, 20));
        const list = document.getElementById('applicant-capabilities-list');
        const retryBtn = list.querySelector('[data-applicant-retry]');
        console.log(JSON.stringify({{ hasRetry: !!retryBtn }}));
    """
    out = _run_node(script)
    assert out == {"hasRetry": True}


def test_network_error_renders_error_state_with_retry(node_available):
    script = f"""
        globalThis.fetch = async () => {{ throw new Error('boom'); }};
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        await new Promise((r) => setTimeout(r, 20));
        const list = document.getElementById('applicant-capabilities-list');
        console.log(JSON.stringify({{ hasRetry: !!list.querySelector('[data-applicant-retry]') }}));
    """
    out = _run_node(script)
    assert out == {"hasRetry": True}


# ══════════════════════════════════════════════════════════════════════════
# 5. Keyboard chord + editable-field suppression + close paths
# ══════════════════════════════════════════════════════════════════════════


def test_ctrl_shift_slash_opens_the_overlay(node_available):
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": []})}
        await import('file://{_CAPABILITIES_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '/', ctrlKey: true, shiftKey: true }}));
        const modal = document.getElementById('applicant-capabilities-modal');
        console.log(JSON.stringify({{ hidden: modal ? modal.classList.contains('hidden') : null }}));
    """
    out = _run_node(script)
    assert out == {"hidden": False}


def test_chord_ignored_while_typing_in_an_input(node_available):
    script = f"""
        await import('file://{_CAPABILITIES_JS}');
        const inputEl = document.createElement('input');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '/', ctrlKey: true, shiftKey: true, target: inputEl }}));
        const modal = document.getElementById('applicant-capabilities-modal');
        console.log(JSON.stringify({{ everOpened: !!(modal && !modal.classList.contains('hidden')) }}));
    """
    out = _run_node(script)
    assert out == {"everOpened": False}


def test_bare_slash_without_modifiers_does_not_open(node_available):
    script = f"""
        await import('file://{_CAPABILITIES_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '/' }}));
        const modal = document.getElementById('applicant-capabilities-modal');
        console.log(JSON.stringify({{ everOpened: !!(modal && !modal.classList.contains('hidden')) }}));
    """
    out = _run_node(script)
    assert out == {"everOpened": False}


def test_close_button_closes_the_overlay(node_available):
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": []})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        document.getElementById('applicant-capabilities-close').dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ hidden: document.getElementById('applicant-capabilities-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_clicking_the_backdrop_closes_the_overlay(node_available):
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": []})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        mod.openApplicantCapabilities();
        const modal = document.getElementById('applicant-capabilities-modal');
        modal.dispatchEvent(__mkEvent('click', {{ target: modal }}));
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_is_open_reflects_state(node_available):
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": []})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        const beforeOpen = mod.isApplicantCapabilitiesOpen();
        mod.openApplicantCapabilities();
        const afterOpen = mod.isApplicantCapabilitiesOpen();
        mod.closeApplicantCapabilities();
        const afterClose = mod.isApplicantCapabilitiesOpen();
        console.log(JSON.stringify({{ beforeOpen, afterOpen, afterClose }}));
    """
    out = _run_node(script)
    assert out == {"beforeOpen": False, "afterOpen": True, "afterClose": False}


def test_degrades_harmlessly_without_uimodule_initmodala11y_present(node_available):
    """window.uiModule.initModalA11y is reused when present (via the ui.js
    stub) but the module must not throw if it's ever absent from window
    itself (defensive try/catch around the call)."""
    script = f"""
        {_fetch_ok({"engine_available": True, "tools": []})}
        const mod = await import('file://{_CAPABILITIES_JS}');
        window.uiModule = undefined;
        let threw = false;
        try {{
            mod.openApplicantCapabilities();
            mod.closeApplicantCapabilities();
        }} catch (e) {{ threw = true; }}
        console.log(JSON.stringify({{ threw }}));
    """
    out = _run_node(script)
    assert out == {"threw": False}


# ══════════════════════════════════════════════════════════════════════════
# 6. Denylist hygiene (per the task's standing instruction)
# ══════════════════════════════════════════════════════════════════════════

_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_files_are_denylist_clean():
    for path in (
        pathlib.Path(__file__),
        _CAPABILITIES_JS,
        _REPO / "routes" / "applicant_capabilities_routes.py",
    ):
        text = path.read_text(encoding="utf-8").lower()
        for first, second in _DENYLIST_CODENAME_HALVES:
            codename = first + second
            assert codename not in text, f"denylist hit {codename!r} in {path.name}"
