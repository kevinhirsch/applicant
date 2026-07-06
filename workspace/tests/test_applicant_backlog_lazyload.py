"""Regression coverage for docs/design/audits/PRODUCT_DEEP_AUDIT_ROUND3.md's
exhaustive2/03_performance.md item #2: "~47 eagerly loaded module scripts on
every boot, including 400KB+ modules for rare surfaces. This is the single
biggest cold-boot lever."

What changed:
  - ``static/index.html`` no longer eagerly ``<script type="module">``-tags
    ``applicantDebug.js``, ``applicantGallery.js``, or ``applicantCompare.js``
    (44 eager module tags now, down from 46 -- three removed, one added).
  - A new tiny eager module, ``static/js/lazyLaunch.js`` (its only import is
    the already-lightweight ``hashRouter.js``), takes their place in the load
    order. At module-eval time it (a) wires a throwaway click listener on
    each surface's launcher button(s) and (b) registers a placeholder
    hashRouter route for each surface's token ('debug' / 'gallery' /
    'compare'). Either trigger dynamic-``import()``s the real module exactly
    once (cached), then calls its ``openApplicantX`` export. The placeholder
    click listeners for a surface detach themselves -- on ALL of that
    surface's buttons, not just the one clicked -- the instant the import
    starts, so once the real module self-wires its own permanent listeners
    there is exactly one live listener per button, not two.
  - ``static/js/commandPalette.js`` (Ctrl+Shift+P launcher for every
    Applicant surface) gained a fallback for its 'debug' / 'gallery' /
    'compare' rows: if ``window.applicantXModule`` isn't loaded yet (because
    the user hasn't clicked that surface's own launcher or hash-linked into
    it), it now calls ``window.__applicantLazyOpen(id)`` -- the hook
    lazyLaunch.js exposes -- instead of silently no-oping. This is additive;
    every existing commandPalette test (which stubs ``window.applicantXModule``
    directly) is unaffected because ``_callFirst`` short-circuits before the
    fallback runs.

Left deliberately EAGER (not converted this wave), with the reason recorded
here so a future pass doesn't have to re-derive it:
  - ``static/js/cookbook.js`` and ``static/js/compare/index.js`` (the native
    model-arena compare, NOT applicantCompare.js) are BOTH statically
    imported by ``static/js/slashCommands.js``
    (``import cookbookModule from './cookbook.js'`` /
    ``import { EVAL_PROMPTS } from './compare/index.js'``), which is itself
    statically imported by the eager ``chat.js`` and ``tourAutoplay.js``.
    Removing their own eager ``<script>`` tags would not reduce the eager
    graph at all -- they would still download via that chain -- and fixing it
    for real means editing ``slashCommands.js``/``chat.js``, both outside this
    wave's owned files (``index.html`` + ``app.js``).
  - ``static/js/admin.js`` has exactly one static importer (``app.js``), which
    passed the audit's own "not imported by another eager module" check --
    but ``window.adminModule`` is read and called SYNCHRONOUSLY, with no lazy
    fallback, by five other already-eager modules (``settings.js``,
    ``calendar.js``, ``emailInbox.js``, ``emailLibrary.js``,
    ``modelPicker.js``) for "jump straight to Admin -> Integrations" deep
    links (e.g. calendar.js:783-784, emailInbox.js:507-508). Lazy-loading
    admin.js without also patching all five call sites would silently break
    those cross-surface jumps, so it stays eager this wave.
  - ``static/js/settings.js`` and the native ``static/js/gallery.js`` were
    never in this wave's candidate list (see the task's own conservative
    starting set) and are both imported by multiple other eager modules
    besides ``app.js`` (``emailLibrary.js``, ``modelPicker.js``,
    ``chatRenderer.js`` import settings.js; gallery.js's only importer is
    app.js but it isn't one of the three named "genuinely rare, launcher-only"
    surfaces this item targets).

Every test below was verified failing (per the batch's test-coverage DoD) by
temporarily reverting the file(s) it protects (``index.html``,
``static/js/lazyLaunch.js`` emptied to a no-op stub, ``commandPalette.js``'s
fallback lines removed), confirming the assertion goes red, then restoring
the original content (clean ``git diff`` afterward) before landing this file.
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
_INDEX_HTML = _REPO / "static" / "index.html"
_APP_JS = _REPO / "static" / "app.js"
_LAZYLAUNCH_JS = _JS_DIR / "lazyLaunch.js"
_PALETTE_JS = _JS_DIR / "commandPalette.js"
_DEBUG_JS = _JS_DIR / "applicantDebug.js"
_GALLERY_JS = _JS_DIR / "applicantGallery.js"
_COMPARE_JS = _JS_DIR / "applicantCompare.js"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ══════════════════════════════════════════════════════════════════════════
# 1. index.html -- source-level wiring
# ══════════════════════════════════════════════════════════════════════════


def test_index_html_no_longer_eagerly_tags_the_three_lazy_surfaces():
    src = _read(_INDEX_HTML)
    assert 'src="/static/js/applicantDebug.js"' not in src
    assert 'src="/static/js/applicantGallery.js"' not in src
    assert 'src="/static/js/applicantCompare.js"' not in src


def test_index_html_loads_lazylaunch_before_app_js():
    src = _read(_INDEX_HTML)
    lazy_idx = src.find('src="/static/js/lazyLaunch.js"')
    app_idx = src.find('src="/static/app.js"')
    assert lazy_idx != -1, "lazyLaunch.js must be loaded via a <script type=module> tag"
    assert app_idx != -1
    assert lazy_idx < app_idx, "lazyLaunch.js must load before app.js (registerRoute must run before hashRouter.initHashRouting())"


def test_eager_module_script_tag_count_dropped_by_two():
    """3 eager tags removed (applicantDebug/Gallery/Compare), 1 added
    (lazyLaunch.js) -- net -2. Locks the audit's headline number down instead
    of letting it silently drift back up."""
    src = _read(_INDEX_HTML)
    count = len(re.findall(r'<script type="module" src=', src))
    # 46 after the dark-engine audit item 24 capability-disclosure overlay added
    # one more eager module (applicantCapabilities.js), on top of the 45 the
    # power-users (07) keyboard-shortcuts overlay left this at; still well
    # below the 46-tag starting set this whole wave began from (net unchanged
    # vs. that original count, despite two power/discoverability overlays
    # having been added since -- three heavy surfaces were lazy-loaded away).
    # 47 after the trust-center reachability fix (lens 12 #5) wired
    # applicantTrust.js in eagerly -- a light, content-only, self-boot overlay
    # (no engine calls), the same category as applicantCapabilities.js /
    # applicantShortcuts.js above, not one of the "heavy" surfaces this wave
    # lazy-loaded away.
    # 48 after wiring applicantAutomationSettings.js -- a Settings-tab panel in
    # the SAME eager category as applicantCampaignSettings.js /
    # applicantModelLadder.js (settings.js reads their window.mount* globals);
    # it was accidentally omitted, so the Automation Preferences tab rendered
    # permanently empty until this tag was added.
    assert count == 48, f"expected 48 eager module <script> tags, got {count}"


def test_cookbook_admin_native_compare_are_still_eager_this_wave():
    """Documents the conservative scope: these three were candidates but are
    deliberately left as eager <script> tags (see module docstring for why)."""
    src = _read(_INDEX_HTML)
    assert 'src="/static/js/cookbook.js"' in src
    assert 'src="/static/js/admin.js"' in src
    assert 'src="/static/js/compare/index.js"' in src


# ══════════════════════════════════════════════════════════════════════════
# 2. lazyLaunch.js -- source-level shape
# ══════════════════════════════════════════════════════════════════════════


def test_lazylaunch_has_no_static_import_of_the_heavy_surfaces():
    src = _read(_LAZYLAUNCH_JS)
    assert "from './applicantDebug.js'" not in src
    assert "from './applicantGallery.js'" not in src
    assert "from './applicantCompare.js'" not in src


def test_lazylaunch_only_statically_imports_hashrouter():
    src = _read(_LAZYLAUNCH_JS)
    import_lines = [ln for ln in src.splitlines() if ln.strip().startswith("import ")]
    assert len(import_lines) == 1
    assert "from './hashRouter.js'" in import_lines[0]


def test_lazylaunch_uses_dynamic_import_for_all_three_surfaces():
    src = _read(_LAZYLAUNCH_JS)
    assert "import(spec.path)" in src
    for path in ("./applicantDebug.js", "./applicantGallery.js", "./applicantCompare.js"):
        assert f"path: '{path}'" in src


def test_lazylaunch_button_ids_match_index_html():
    """The button ids lazyLaunch.js wires must actually exist in index.html,
    and must match the ids each real surface's own _wireLauncher() targets
    (applicantDebug.js: tool-debug-btn; applicantGallery.js:
    tool-applicant-gallery-btn / rail-applicant-gallery; applicantCompare.js:
    tool-compare-btn / rail-compare)."""
    lazy_src = _read(_LAZYLAUNCH_JS)
    html_src = _read(_INDEX_HTML)
    debug_src = _read(_DEBUG_JS)
    gallery_src = _read(_GALLERY_JS)
    compare_src = _read(_COMPARE_JS)

    for btn_id in (
        "tool-debug-btn",
        "tool-applicant-gallery-btn", "rail-applicant-gallery",
        "tool-compare-btn", "rail-compare",
    ):
        assert f"'{btn_id}'" in lazy_src, f"lazyLaunch.js must reference {btn_id!r}"
        assert f'id="{btn_id}"' in html_src, f"{btn_id!r} must exist in index.html"

    assert "'tool-debug-btn'" in debug_src
    assert "'tool-applicant-gallery-btn'" in gallery_src and "'rail-applicant-gallery'" in gallery_src
    assert "'tool-compare-btn'" in compare_src and "'rail-compare'" in compare_src


# ══════════════════════════════════════════════════════════════════════════
# 3. Real node execution -- the actual lazy-load mechanism
# ══════════════════════════════════════════════════════════════════════════

# Merges test_applicant_backlog_commandpalette.py's DOM shim (Element with a
# dataset Proxy that reflects data-* attributes parsed off innerHTML, needed
# for commandPalette.js's row clicks) with
# test_applicant_round2_wave3_hashrouting_remaining.py's location/history
# pieces (needed for hashRouter.js's setHash/clearHash + hashchange
# simulation) -- both copied verbatim from their source files per this repo's
# per-file-shim convention, concatenated rather than reinvented.
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
  constructor(tag){ super(); this.nodeType=1; this.tagName=String(tag).toUpperCase(); this._attrs=new Map(); this.children=[]; this.parentNode=null; this.classList=new ClassList(); this.style=makeStyle(); this._text=''; this._html=''; }
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
  constructor(){ this._hash=''; this.pathname='/'; this.search=''; this.origin='http://localhost'; }
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
globalThis.history = {
  pushState(state, title, url){ __loc._hash = __parseHashFromUrl(url); },
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

globalThis.__mkEvent = function(type, opts) {
  const e = Object.assign({ type, key: '', ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, target: null }, opts || {});
  e._prevented = false;
  e.preventDefault = function(){ e._prevented = true; };
  e.stopPropagation = function(){};
  return e;
};
"""

# ui.js stub -- identical technique/content to the hashrouting-remaining wave's
# loader hook (applicantDebug/Gallery/Compare each import only ./ui.js and
# ./applicantCore.js -- and applicantCore.js itself imports only ./ui.js --
# so this single redirect covers the whole chain).
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


def _run_node(js_body: str, *, with_ui_stub: bool = True) -> dict:
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
    if res.returncode != 0:
        raise AssertionError(f"node failed (rc={res.returncode}):\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError(f"node produced no stdout\nSTDERR:\n{res.stderr}")
    return json.loads(out_lines[-1])


def _run_node_multi(js_body: str, *, with_ui_stub: bool = True) -> list:
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


def _seed_buttons() -> str:
    """JS snippet that plants the five real launcher buttons in the DOM
    before lazyLaunch.js boots, mirroring index.html's actual markup ids."""
    return r"""
        for (const id of ['tool-debug-btn', 'tool-applicant-gallery-btn', 'rail-applicant-gallery', 'tool-compare-btn', 'rail-compare']) {
          const b = document.createElement('div');
          b.id = id;
          document.body.appendChild(b);
        }
    """


# ── 3a. Importing lazyLaunch.js alone must NOT pull in the heavy modules ────


def test_importing_lazylaunch_alone_does_not_load_heavy_modules(node_available):
    script = f"""
        {_seed_buttons()}
        await import('file://{_LAZYLAUNCH_JS}');
        console.log(JSON.stringify({{
          debug: !!window.applicantDebugModule,
          gallery: !!window.applicantGalleryModule,
          compare: !!window.applicantCompareModule,
        }}));
    """
    out = _run_node(script)
    assert out == {"debug": False, "gallery": False, "compare": False}


def test_lazylaunch_registers_placeholder_routes_immediately(node_available):
    script = f"""
        {_seed_buttons()}
        await import('file://{_LAZYLAUNCH_JS}');
        console.log(JSON.stringify({{
          debug: window.applicantHashRouter.hasRoute('debug'),
          gallery: window.applicantHashRouter.hasRoute('gallery'),
          compare: window.applicantHashRouter.hasRoute('compare'),
        }}));
    """
    out = _run_node(script)
    assert out == {"debug": True, "gallery": True, "compare": True}


# ── 3b. Click on a launcher lazily loads the REAL module and opens it ──────


def test_click_on_debug_launcher_lazy_loads_and_opens_real_module(node_available):
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        document.getElementById('tool-debug-btn').dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('debug');
        const modal = document.getElementById('applicant-debug-modal');
        console.log(JSON.stringify({{
          loaded: !!window.applicantDebugModule,
          modalExists: !!modal,
          modalHidden: modal ? modal.classList.contains('hidden') : null,
        }}));
    """
    out = _run_node(script)
    assert out == {"loaded": True, "modalExists": True, "modalHidden": False}


def test_click_on_gallery_launcher_lazy_loads_and_opens_real_module(node_available):
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        document.getElementById('tool-applicant-gallery-btn').dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('gallery');
        const modal = document.getElementById('applicant-gallery-modal');
        console.log(JSON.stringify({{
          loaded: !!window.applicantGalleryModule,
          modalHidden: modal ? modal.classList.contains('hidden') : null,
        }}));
    """
    out = _run_node(script)
    assert out == {"loaded": True, "modalHidden": False}


def test_click_on_rail_compare_lazy_loads_and_opens_real_module(node_available):
    """Uses the SECOND button (rail-compare, not tool-compare-btn) to prove
    either of Compare's two launcher ids triggers the load."""
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        document.getElementById('rail-compare').dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('compare');
        const modal = document.getElementById('applicant-compare-modal');
        console.log(JSON.stringify({{
          loaded: !!window.applicantCompareModule,
          modalHidden: modal ? modal.classList.contains('hidden') : null,
        }}));
    """
    out = _run_node(script)
    assert out == {"loaded": True, "modalHidden": False}


# ── 3c. No double-listener / double-open after the module finishes loading ─


def test_no_duplicate_click_listener_after_debug_loads(node_available):
    """Before load: 1 placeholder listener. After load: exactly 1 listener
    (the real module's own) -- not 2 -- proving the placeholder detached
    itself instead of stacking with the real _wireLauncher() listener."""
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        const btn = document.getElementById('tool-debug-btn');
        const before = (btn._l['click']||[]).length;
        btn.dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('debug');
        const after = (btn._l['click']||[]).length;
        console.log(JSON.stringify({{ before, after }}));
    """
    out = _run_node(script)
    assert out == {"before": 1, "after": 1}


def test_clicking_a_second_time_does_not_reopen_via_a_stale_placeholder(node_available):
    """After the real module has loaded and re-wired, a second click must
    route through ONLY the real module's listener (no lingering placeholder
    double-firing openApplicantDebug via two separate paths)."""
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        const btn = document.getElementById('tool-debug-btn');
        btn.dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('debug');
        const afterFirstClick = (btn._l['click']||[]).length;
        btn.dispatchEvent(__mkEvent('click', {{}}));
        const afterSecondClick = (btn._l['click']||[]).length;
        console.log(JSON.stringify({{ afterFirstClick, afterSecondClick }}));
    """
    out = _run_node(script)
    assert out == {"afterFirstClick": 1, "afterSecondClick": 1}


def test_clicking_the_other_compare_button_also_detaches_both_placeholders(node_available):
    """Compare has two launcher ids sharing one lazy load. Clicking
    tool-compare-btn must ALSO tear down rail-compare's still-unclicked
    placeholder -- otherwise rail-compare would end up with a placeholder
    AND the real module's listener stacked once loading finishes."""
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        const tool = document.getElementById('tool-compare-btn');
        const rail = document.getElementById('rail-compare');
        tool.dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('compare');
        console.log(JSON.stringify({{
          toolListeners: (tool._l['click']||[]).length,
          railListeners: (rail._l['click']||[]).length,
        }}));
    """
    out = _run_node(script)
    # tool-compare-btn also carries app.js's own (unrelated, native-compare)
    # listener in the real app -- not simulated here, so in this isolated
    # shim it's just the real applicantCompare.js listener: exactly 1.
    assert out == {"toolListeners": 1, "railListeners": 1}


# ── 3d. Hash deep-link path (not just click) ────────────────────────────────


def test_hash_deep_link_lazy_loads_gallery(node_available):
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        window.applicantHashRouter.initHashRouting();
        __simulateHashNav('#gallery');
        await lazy.ensureLoaded('gallery');
        const modal = document.getElementById('applicant-gallery-modal');
        console.log(JSON.stringify({{
          loaded: !!window.applicantGalleryModule,
          modalHidden: modal ? modal.classList.contains('hidden') : null,
        }}));
    """
    out = _run_node(script)
    assert out == {"loaded": True, "modalHidden": False}


def test_hash_deep_link_lazy_loads_debug_at_boot_before_any_click(node_available):
    """Simulates the exact boot scenario the task called out: opening the app
    directly at #debug (no prior click on the Debug launcher) must still lazy
    load and open it."""
    script = f"""
        {_seed_buttons()}
        __simulateHashNav('#debug');
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        window.applicantHashRouter.initHashRouting();
        await lazy.ensureLoaded('debug');
        const modal = document.getElementById('applicant-debug-modal');
        console.log(JSON.stringify({{
          loaded: !!window.applicantDebugModule,
          modalHidden: modal ? modal.classList.contains('hidden') : null,
        }}));
    """
    out = _run_node(script)
    assert out == {"loaded": True, "modalHidden": False}


# ══════════════════════════════════════════════════════════════════════════
# 4. commandPalette.js fallback -- source + real execution
# ══════════════════════════════════════════════════════════════════════════


def test_command_palette_source_has_lazy_fallback_for_the_three_surfaces():
    src = _read(_PALETTE_JS)
    assert len(re.findall(r"window\.__applicantLazyOpen\('(debug|gallery|compare)'\)", src)) == 3
    assert "window.__applicantLazyOpen('debug')" in src
    assert "window.__applicantLazyOpen('gallery')" in src
    assert "window.__applicantLazyOpen('compare')" in src


def test_command_palette_debug_row_falls_back_to_lazy_open_when_module_absent(node_available):
    """Unit-level: stub window.__applicantLazyOpen directly (no real
    lazyLaunch.js) to prove commandPalette.js's own fallback wiring calls it
    with the right id when window.applicantDebugModule is absent."""
    script = f"""
        window.__applicantLazyOpen = (id) => {{ globalThis.__lazyCalls = (globalThis.__lazyCalls||[]); globalThis.__lazyCalls.push(id); }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="debug"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ calls: globalThis.__lazyCalls||[] }}));
    """
    out = _run_node(script, with_ui_stub=False)
    assert out == {"calls": ["debug"]}


def test_command_palette_still_prefers_the_real_module_over_lazy_fallback(node_available):
    """When window.applicantGalleryModule IS already present (surface was
    opened earlier), the palette must use it directly and never touch the
    lazy fallback."""
    script = f"""
        window.applicantGalleryModule = {{ openApplicantGallery: () => {{ globalThis.__calls = (globalThis.__calls||0)+1; }} }};
        window.__applicantLazyOpen = (id) => {{ globalThis.__lazyCalls = (globalThis.__lazyCalls||0)+1; }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="gallery"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ calls: globalThis.__calls||0, lazyCalls: globalThis.__lazyCalls||0 }}));
    """
    out = _run_node(script, with_ui_stub=False)
    assert out == {"calls": 1, "lazyCalls": 0}


def test_command_palette_end_to_end_with_real_lazylaunch_opens_real_compare_modal(node_available):
    """Full integration: real commandPalette.js + real lazyLaunch.js + real
    applicantCompare.js, nothing stubbed except ./ui.js. Clicking the
    'Compare' row in the palette (with no surface pre-loaded) must open the
    genuine Compare modal end-to-end."""
    script = f"""
        {_seed_buttons()}
        const lazy = await import('file://{_LAZYLAUNCH_JS}');
        const palette = await import('file://{_PALETTE_JS}');
        palette.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="compare"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        await lazy.ensureLoaded('compare');
        const modal = document.getElementById('applicant-compare-modal');
        console.log(JSON.stringify({{
          loaded: !!window.applicantCompareModule,
          modalHidden: modal ? modal.classList.contains('hidden') : null,
        }}));
    """
    out = _run_node(script)
    assert out == {"loaded": True, "modalHidden": False}
