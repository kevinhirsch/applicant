"""Regression coverage for the ux-flows backlog item: "a command palette +
keyboard shortcuts for the surfaces users live in" (docs/design/audits/
PRODUCT_EXHAUSTIVE_AUDIT.md).

New file under test: ``static/js/commandPalette.js`` — a Ctrl+Shift+P
(Cmd+Shift+P) overlay that lets the user type a few letters and jump straight
to any of the 12 already-reachable Applicant surfaces (Portal, Activity,
Debug, Results, Tracker, Vault, Remote, Gallery, Mind, Compare, Chat, Update)
via the ``window.applicantXModule.openApplicantX()`` / bare
``window.openApplicantX()`` launchers those 12 ``applicantX.js`` files already
export.

Design constraints this suite locks in (per the task's own methodology):

  - **No existing file was edited except ``index.html``** — and that edit is
    ONE new ``<script type="module" src="/static/js/commandPalette.js">`` tag,
    the exact same load mechanism every other self-booting ``applicantX.js``
    surface already uses there (``applicantDebug.js`` / ``applicantGallery.js``
    / ``applicantRemote.js`` / ... / ``applicantTracker.js``, all listed right
    before it, right before the mandatory "app.js must be LAST" tag). Without
    a script tag (or an import from an already-loaded module), an ES module
    file is never fetched/executed by the browser at all — this is the
    unavoidable minimum wiring, not a restructuring of any existing surface.
  - ``app.js`` itself was **not** touched — commandPalette.js is fully
    self-contained (zero ``import`` statements; everything is read off
    ``window``/``document`` at call time), so nothing needed to change there.
  - The trigger key is **Ctrl+Shift+P / Cmd+Shift+P**, chosen because every
    combo already reserved by the workspace's OWN keybind system
    (``static/js/keyboard-shortcuts.js`` ``_defaultKeybinds`` /
    ``static/js/settings.js`` ``SHORTCUT_DEFAULTS`` — the registry an earlier
    round in this session fixed a default/display mismatch for) is taken:
    ``ctrl+k`` (search — the existing Ctrl+K conversation-search "command
    palette"), ``ctrl+alt+b/n/f/d``, ``ctrl+alt+c``, ``ctrl+,``, ``ctrl+/``,
    ``alt+shift+t``, ``escape``. Ctrl+Shift+P collides with none of them.

Two testing strategies, per the task's own stated preference for real
execution over text-regex wherever practical:

  1. Real ``node`` execution of the ACTUAL ``commandPalette.js`` file against a
     lightweight DOM shim (same technique
     ``test_applicant_round2_wave3_hashrouting_remaining.py`` uses for
     ``applicantResults.js`` / ``applicantUpdate.js``) — exercises the real
     trigger-key wiring, the real filter/keyboard-nav logic, and the real
     surface-launcher dispatch, not just markup checks. commandPalette.js has
     no ``./ui.js`` import (unlike the modules that precedent stubbed), so no
     loader-hook substitution is needed here — a straight DOM shim suffices.
  2. Source-level assertions for the two things that are structurally
     inconvenient to execute-test (the ``index.html`` wiring, and the
     "app.js untouched" guarantee).

Every ``test_*`` here was verified failing (per the task's DoD) by temporarily
breaking the exact behavior it protects (see the session's own verification
run), then restoring the original file (clean ``git diff`` afterward) before
landing this file.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_JS_DIR = _REPO / "static" / "js"
_PALETTE_JS = _JS_DIR / "commandPalette.js"
_APP_JS = _REPO / "static" / "app.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_HAS_NODE = shutil.which("node") is not None

_EXPECTED_SURFACE_IDS = [
    "portal", "activity", "debug", "results", "tracker", "vault",
    "remote", "gallery", "mind", "compare", "chat", "update",
]


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + event shim ──────────────────────────────────────────────────
#
# Adapted from test_applicant_round2_wave3_hashrouting_remaining.py's DOM shim
# (kept as its own copy rather than a shared import, matching this repo's
# established per-file-shim convention). commandPalette.js needs no
# location/history pieces (it never touches the URL — it isn't itself a
# hash-routable surface, it only launches ones that are), so those parts of
# the precedent shim are trimmed; a plain synthetic keydown/click/input event
# object (matching the shape commandPalette.js actually reads: .type, .key,
# .ctrlKey, .metaKey, .shiftKey, .altKey, .target, .preventDefault()) is all
# that's required.
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
  // dataset mirrors data-* attributes (real DOM behavior) — a plain object
  // wouldn't reflect attributes parsed off innerHTML strings, and
  // commandPalette.js's row click handler reads row.dataset.index.
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
  // Splits a compound simple selector (e.g. `.foo[data-id="mind"]`) into its
  // `#id` / `.class` / `[attr=val]` pieces so each can be AND-tested via
  // testBase — the original single-clause testBase only handled ONE such
  // piece, which is enough for the precedent files' plain `#id`/`.class`
  // selectors but not commandPalette.js's tests, which query compound
  // `.class[data-id="..."]` selectors.
  const tokens = [];
  const re = /#[\w-]+|\.[\w-]+|\[[^\]]+\]/g;
  let m;
  while ((m = re.exec(base))) tokens.push(m[0]);
  if (!tokens.length && base) tokens.push(base); // bare tag name fallback
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
globalThis.MutationObserver = class MutationObserver { constructor(cb){ this.cb=cb; } observe(){} disconnect(){} };
const win = new WindowObj();
win.document = DOC;
globalThis.window = win;

// Synthetic event helper — commandPalette.js only ever reads these fields off
// an event object, so a plain object (not a real KeyboardEvent/MouseEvent) is
// enough, same approach as globalThis.history.pushState stand-ins in the
// hashRouter precedent shim.
globalThis.__mkEvent = function(type, opts) {
  const e = Object.assign({ type, key: '', ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, target: null }, opts || {});
  e._prevented = false;
  e.preventDefault = function(){ e._prevented = true; };
  e.stopPropagation = function(){};
  return e;
};
"""


def _run_node(js_body: str) -> dict:
    script = _DOM_SHIM + "\n" + js_body + "\nprocess.exit(0);"
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


def _run_node_multi(js_body: str) -> list:
    script = _DOM_SHIM + "\n" + js_body + "\nprocess.exit(0);"
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO, capture_output=True, timeout=20, text=True,
    )
    assert res.returncode == 0, f"node failed:\nSTDOUT:{res.stdout}\nSTDERR:{res.stderr}"
    lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


# ══════════════════════════════════════════════════════════════════════════
# 1. Design constraints — source-level checks
# ══════════════════════════════════════════════════════════════════════════


def test_command_palette_has_no_import_statements():
    """Fully self-contained: no ./ui.js or other module import, so no other
    file's load order/module graph is a dependency of this one."""
    src = _read(_PALETTE_JS)
    assert "\nimport " not in ("\n" + src), "commandPalette.js must stay import-free (reads window/document only)"


def test_command_palette_wired_via_script_tag_before_app_js():
    src = _read(_INDEX_HTML)
    palette_idx = src.find('src="/static/js/commandPalette.js"')
    app_idx = src.find('src="/static/app.js"')
    assert palette_idx != -1, "commandPalette.js must be loaded via a <script type=module> tag in index.html"
    assert app_idx != -1
    assert palette_idx < app_idx, "commandPalette.js must load before app.js (app.js must be LAST, per the existing comment)"


def test_app_js_was_not_touched_for_this_feature():
    src = _read(_APP_JS)
    assert "commandPalette" not in src, "app.js should not need any reference to commandPalette.js — it self-boots"


# ══════════════════════════════════════════════════════════════════════════
# 2. The surface registry — real execution
# ══════════════════════════════════════════════════════════════════════════


def test_lists_all_twelve_surfaces_in_expected_order(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        console.log(JSON.stringify({{ ids: mod.listSurfaces() }}));
    """
    out = _run_node(script)
    assert out == {"ids": _EXPECTED_SURFACE_IDS}


# ══════════════════════════════════════════════════════════════════════════
# 3. Trigger key — real execution against the module-level keydown listener
# ══════════════════════════════════════════════════════════════════════════


def test_ctrl_shift_p_opens_the_palette(node_available):
    script = f"""
        await import('file://{_PALETTE_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: true }}));
        const modal = document.getElementById('applicant-command-palette-modal');
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": False}


def test_cmd_shift_p_opens_the_palette_on_mac(node_available):
    script = f"""
        await import('file://{_PALETTE_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'P', metaKey: true, shiftKey: true }}));
        const modal = document.getElementById('applicant-command-palette-modal');
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": False}


def test_ctrl_shift_alt_p_does_not_open(node_available):
    """The alt modifier must NOT be part of the chord — confirms the exact
    combo, not an accidental superset match."""
    script = f"""
        await import('file://{_PALETTE_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: true, altKey: true }}));
        const modal = document.getElementById('applicant-command-palette-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_ctrl_p_without_shift_does_not_open(node_available):
    script = f"""
        await import('file://{_PALETTE_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: false }}));
        const modal = document.getElementById('applicant-command-palette-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_trigger_ignored_while_typing_in_an_input(node_available):
    script = f"""
        await import('file://{_PALETTE_JS}');
        const inputEl = document.createElement('input');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: true, target: inputEl }}));
        const modal = document.getElementById('applicant-command-palette-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_trigger_still_fires_from_a_non_editable_target(node_available):
    script = f"""
        await import('file://{_PALETTE_JS}');
        const divEl = document.createElement('div');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: true, target: divEl }}));
        const modal = document.getElementById('applicant-command-palette-modal');
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": False}


def test_trigger_toggles_closed_on_second_press(node_available):
    script = f"""
        await import('file://{_PALETTE_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: true }}));
        const openHidden = document.getElementById('applicant-command-palette-modal').classList.contains('hidden');
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'p', ctrlKey: true, shiftKey: true }}));
        const closedHidden = document.getElementById('applicant-command-palette-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ openHidden, closedHidden }}));
    """
    out = _run_node(script)
    assert out == {"openHidden": False, "closedHidden": True}


# ══════════════════════════════════════════════════════════════════════════
# 4. Open / list rendering
# ══════════════════════════════════════════════════════════════════════════


def test_open_renders_all_twelve_rows(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const rows = document.getElementById('applicant-command-palette-list').querySelectorAll('.applicant-command-palette-row');
        console.log(JSON.stringify({{ count: rows.length }}));
    """
    out = _run_node(script)
    assert out == {"count": 12}


def test_open_focuses_and_clears_the_input(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        const input = document.createElement('input'); // decoy, not used
        mod.openCommandPalette();
        const realInput = document.getElementById('applicant-command-palette-input');
        realInput.value = 'stale';
        mod.closeCommandPalette();
        mod.openCommandPalette();
        console.log(JSON.stringify({{ value: realInput.value, focused: document.activeElement === realInput }}));
    """
    out = _run_node(script)
    assert out == {"value": "", "focused": True}


# ══════════════════════════════════════════════════════════════════════════
# 5. Filtering
# ══════════════════════════════════════════════════════════════════════════


def test_filter_narrows_to_matching_keyword(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.value = 'password';
        input.dispatchEvent(__mkEvent('input', {{}}));
        const rows = [...document.getElementById('applicant-command-palette-list').querySelectorAll('.applicant-command-palette-row')];
        console.log(JSON.stringify({{ ids: rows.map(r => r.dataset.id) }}));
    """
    out = _run_node(script)
    assert out == {"ids": ["vault"]}


def test_filter_matches_on_label_too(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.value = 'tRaCk';
        input.dispatchEvent(__mkEvent('input', {{}}));
        const rows = [...document.getElementById('applicant-command-palette-list').querySelectorAll('.applicant-command-palette-row')];
        console.log(JSON.stringify({{ ids: rows.map(r => r.dataset.id) }}));
    """
    out = _run_node(script)
    assert out == {"ids": ["tracker"]}


def test_filter_empty_query_shows_all_twelve(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.value = 'gallery';
        input.dispatchEvent(__mkEvent('input', {{}}));
        input.value = '';
        input.dispatchEvent(__mkEvent('input', {{}}));
        const rows = document.getElementById('applicant-command-palette-list').querySelectorAll('.applicant-command-palette-row');
        console.log(JSON.stringify({{ count: rows.length }}));
    """
    out = _run_node(script)
    assert out == {"count": 12}


def test_filter_no_match_shows_empty_state(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.value = 'zzzznomatch';
        input.dispatchEvent(__mkEvent('input', {{}}));
        const list = document.getElementById('applicant-command-palette-list');
        const rows = list.querySelectorAll('.applicant-command-palette-row');
        console.log(JSON.stringify({{ count: rows.length, hasEmptyMsg: list.innerHTML.includes('No matching surface') }}));
    """
    out = _run_node(script)
    assert out == {"count": 0, "hasEmptyMsg": True}


# ══════════════════════════════════════════════════════════════════════════
# 6. Keyboard navigation + activation (real launcher dispatch)
# ══════════════════════════════════════════════════════════════════════════


def test_enter_activates_first_row_by_default(node_available):
    script = f"""
        window.applicantPortalModule = {{ openApplicantPortal: () => {{ globalThis.__calls = (globalThis.__calls||0)+1; }} }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.dispatchEvent(__mkEvent('keydown', {{ key: 'Enter' }}));
        console.log(JSON.stringify({{ calls: globalThis.__calls||0, hidden: document.getElementById('applicant-command-palette-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"calls": 1, "hidden": True}


def test_arrow_down_then_enter_activates_second_row(node_available):
    script = f"""
        window.applicantPortalModule = {{ openApplicantPortal: () => {{ globalThis.__portalCalls = (globalThis.__portalCalls||0)+1; }} }};
        window.applicantActivityModule = {{ openApplicantActivity: () => {{ globalThis.__activityCalls = (globalThis.__activityCalls||0)+1; }} }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.dispatchEvent(__mkEvent('keydown', {{ key: 'ArrowDown' }}));
        input.dispatchEvent(__mkEvent('keydown', {{ key: 'Enter' }}));
        console.log(JSON.stringify({{ portalCalls: globalThis.__portalCalls||0, activityCalls: globalThis.__activityCalls||0 }}));
    """
    out = _run_node(script)
    assert out == {"portalCalls": 0, "activityCalls": 1}


def test_arrow_up_clamps_at_zero(node_available):
    """ArrowUp with nothing above the first row must not go negative (no
    launcher is skipped/off-by-one on Enter)."""
    script = f"""
        window.applicantPortalModule = {{ openApplicantPortal: () => {{ globalThis.__calls = (globalThis.__calls||0)+1; }} }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.dispatchEvent(__mkEvent('keydown', {{ key: 'ArrowUp' }}));
        input.dispatchEvent(__mkEvent('keydown', {{ key: 'Enter' }}));
        console.log(JSON.stringify({{ calls: globalThis.__calls||0 }}));
    """
    out = _run_node(script)
    assert out == {"calls": 1}


def test_clicking_a_row_activates_that_surface(node_available):
    script = f"""
        window.applicantMindModule = {{ openApplicantMind: () => {{ globalThis.__calls = (globalThis.__calls||0)+1; }} }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="mind"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ calls: globalThis.__calls||0, hidden: document.getElementById('applicant-command-palette-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"calls": 1, "hidden": True}


def test_falls_back_to_bare_window_global_when_module_object_absent(node_available):
    """Results/Tracker/Vault/Remote each additionally export a bare
    window.openApplicantX() alias (grepped from their own export blocks); the
    palette must still work through THAT alone when the *Module object isn't
    present (defensive — mirrors how those 4 files' own code treats the two
    forms as equivalent)."""
    script = f"""
        window.openApplicantTracker = () => {{ globalThis.__calls = (globalThis.__calls||0)+1; }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="tracker"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ calls: globalThis.__calls||0 }}));
    """
    out = _run_node(script)
    assert out == {"calls": 1}


def test_prefers_module_object_over_bare_global_when_both_exist(node_available):
    script = f"""
        window.applicantResultsModule = {{ openApplicantResults: () => {{ globalThis.__moduleCalls = (globalThis.__moduleCalls||0)+1; }} }};
        window.openApplicantResults = () => {{ globalThis.__bareCalls = (globalThis.__bareCalls||0)+1; }};
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="results"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ moduleCalls: globalThis.__moduleCalls||0, bareCalls: globalThis.__bareCalls||0 }}));
    """
    out = _run_node(script)
    assert out == {"moduleCalls": 1, "bareCalls": 0}


def test_activating_a_surface_with_no_launcher_present_does_not_throw(node_available):
    """None of window.applicantXModule / window.openApplicantX exist for some
    surface (e.g. the front-door hasn't finished loading that script yet) —
    clicking it must not crash the palette."""
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const row = document.querySelector('.applicant-command-palette-row[data-id="compare"]');
        row.dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ hidden: document.getElementById('applicant-command-palette-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


# ══════════════════════════════════════════════════════════════════════════
# 7. Close paths
# ══════════════════════════════════════════════════════════════════════════


def test_escape_closes_the_palette(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const input = document.getElementById('applicant-command-palette-input');
        input.dispatchEvent(__mkEvent('keydown', {{ key: 'Escape' }}));
        console.log(JSON.stringify({{ hidden: document.getElementById('applicant-command-palette-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_close_button_closes_the_palette(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        document.getElementById('applicant-command-palette-close').dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ hidden: document.getElementById('applicant-command-palette-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_clicking_the_backdrop_closes_the_palette(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        mod.openCommandPalette();
        const modal = document.getElementById('applicant-command-palette-modal');
        modal.dispatchEvent(__mkEvent('click', {{ target: modal }}));
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_is_open_reflects_state(node_available):
    script = f"""
        const mod = await import('file://{_PALETTE_JS}');
        const beforeOpen = mod.isCommandPaletteOpen();
        mod.openCommandPalette();
        const afterOpen = mod.isCommandPaletteOpen();
        mod.closeCommandPalette();
        const afterClose = mod.isCommandPaletteOpen();
        console.log(JSON.stringify({{ beforeOpen, afterOpen, afterClose }}));
    """
    out = _run_node(script)
    assert out == {"beforeOpen": False, "afterOpen": True, "afterClose": False}


# ══════════════════════════════════════════════════════════════════════════
# 8. Denylist hygiene (per the task's standing instruction)
# ══════════════════════════════════════════════════════════════════════════

_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_files_are_denylist_clean():
    for path in (pathlib.Path(__file__), _PALETTE_JS):
        text = path.read_text(encoding="utf-8").lower()
        for first, second in _DENYLIST_CODENAME_HALVES:
            codename = first + second
            assert codename not in text, f"denylist hit {codename!r} in {path.name}"
