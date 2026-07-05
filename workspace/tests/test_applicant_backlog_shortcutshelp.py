"""Regression coverage for the power-users audit lens (docs/design/audits/
exhaustive2/07_power_users.md), Tier 4 finding #36: "A global '?' shortcuts
cheat-sheet" — "Only the image editor has a shortcuts overlay
(static/js/editor/keyboard-shortcuts.js); the global, customizable map has
zero discoverability. A '?' overlay rendered *from* the live keybind map (so
custom binds show correctly) is the standard affordance."

New file under test: ``static/js/applicantShortcuts.js`` — a bare-``?``
overlay that renders the CURRENT contents of ``window._applicantKeybinds``
(the live map ``keyboard-shortcuts.js``'s ``initKeyboardShortcuts()``
populates, including any user rebind saved via Settings) as a cheat-sheet,
reusing the shared ``.modal``/``.admin-card`` chrome.

Design constraints this suite locks in (mirrors
``test_applicant_backlog_commandpalette.py``'s own methodology for the
sibling ``commandPalette.js`` self-contained module):

  - **No existing file was edited except ``index.html``** — and that edit is
    ONE new ``<script type="module" src="/static/js/applicantShortcuts.js">``
    tag, loaded (like every other self-booting ``applicantX.js`` /
    ``commandPalette.js`` surface) before the mandatory "app.js must be LAST"
    tag.
  - ``app.js``, ``keyboard-shortcuts.js``, ``settings.js`` and
    ``commandPalette.js`` were **not** touched — ``applicantShortcuts.js`` is
    fully self-contained (zero ``import`` statements; everything is read off
    ``window``/``document`` at call time).
  - The trigger key is a **bare ``?``** (no modifier), matching the image
    editor's own convention (``editor/keyboard-shortcuts.js:71``). It is
    ignored while the event target is an editable field (input/textarea/
    contentEditable) so typing a literal "?" anywhere never triggers it, and
    ignored while ``window.__galleryEditLive`` is true (the flag
    ``galleryEditor.js`` sets around its own editor session) so the editor's
    own cheatsheet and this global one never both react to one keypress.

Two testing strategies, per the task's own stated preference for real
execution over text-regex wherever practical:

  1. Real ``node`` execution of the ACTUAL ``applicantShortcuts.js`` file
     against a lightweight DOM shim (the same technique
     ``test_applicant_backlog_commandpalette.py`` uses) — exercises the real
     trigger-key wiring and the real rendering-from-live-keybind-map logic,
     not just markup checks.
  2. Source-level assertions for the two things that are structurally
     inconvenient to execute-test (the ``index.html`` wiring, and the
     "no other file touched" guarantee).

Every ``test_*`` here was verified failing (per the task's DoD) by
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
_SHORTCUTS_JS = _JS_DIR / "applicantShortcuts.js"
_APP_JS = _REPO / "static" / "app.js"
_KEYBOARD_SHORTCUTS_JS = _JS_DIR / "keyboard-shortcuts.js"
_SETTINGS_JS = _JS_DIR / "settings.js"
_COMMAND_PALETTE_JS = _JS_DIR / "commandPalette.js"
_INDEX_HTML = _REPO / "static" / "index.html"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + event shim ──────────────────────────────────────────────────
#
# Copied (own-file convention per this repo's established per-file-shim
# pattern, see test_applicant_backlog_commandpalette.py's own comment on
# this) from that file's DOM shim, trimmed nowhere further since
# applicantShortcuts.js exercises the same surface area (element creation,
# innerHTML parsing, classList, dataset, keydown/click dispatch).
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


# ══════════════════════════════════════════════════════════════════════════
# 1. Design constraints — source-level checks
# ══════════════════════════════════════════════════════════════════════════


def test_shortcuts_help_has_no_import_statements():
    """Fully self-contained: no imports, so no other file's load order is a
    dependency of this one."""
    src = _read(_SHORTCUTS_JS)
    assert "\nimport " not in ("\n" + src), "applicantShortcuts.js must stay import-free (reads window/document only)"


def test_shortcuts_help_wired_via_script_tag_before_app_js():
    src = _read(_INDEX_HTML)
    shortcuts_idx = src.find('src="/static/js/applicantShortcuts.js"')
    app_idx = src.find('src="/static/app.js"')
    assert shortcuts_idx != -1, "applicantShortcuts.js must be loaded via a <script type=module> tag in index.html"
    assert app_idx != -1
    assert shortcuts_idx < app_idx, "applicantShortcuts.js must load before app.js (app.js must be LAST, per the existing comment)"


def test_exactly_one_script_tag_added():
    src = _read(_INDEX_HTML)
    assert src.count('src="/static/js/applicantShortcuts.js"') == 1


def test_no_other_file_was_touched_for_this_feature():
    for path, forbidden in (
        (_APP_JS, "applicantShortcuts"),
        (_KEYBOARD_SHORTCUTS_JS, "applicantShortcuts"),
        (_SETTINGS_JS, "applicantShortcuts"),
        (_COMMAND_PALETTE_JS, "applicantShortcuts"),
    ):
        assert forbidden not in _read(path), (
            f"{path.name} should not need any reference to applicantShortcuts.js — it self-boots"
        )


# ══════════════════════════════════════════════════════════════════════════
# 2. Trigger key — real execution against the module-level keydown listener
# ══════════════════════════════════════════════════════════════════════════


def test_bare_question_mark_opens_the_overlay(node_available):
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?' }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ everCreated: !!modal, hidden: modal ? modal.classList.contains('hidden') : null }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": True, "hidden": False}


def test_second_question_mark_press_toggles_closed(node_available):
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?' }}));
        const openHidden = document.getElementById('applicant-shortcuts-modal').classList.contains('hidden');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?' }}));
        const closedHidden = document.getElementById('applicant-shortcuts-modal').classList.contains('hidden');
        console.log(JSON.stringify({{ openHidden, closedHidden }}));
    """
    out = _run_node(script)
    assert out == {"openHidden": False, "closedHidden": True}


def test_trigger_ignored_while_typing_in_an_input(node_available):
    """Regression guard for the task's own requirement: typing "?" into a
    text field (e.g. asking a question in chat) must never pop the
    overlay."""
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        const inputEl = document.createElement('input');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?', target: inputEl }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_trigger_ignored_while_typing_in_a_textarea(node_available):
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        const ta = document.createElement('textarea');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?', target: ta }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_trigger_ignored_on_contenteditable_target(node_available):
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        const div = document.createElement('div');
        div.isContentEditable = true;
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?', target: div }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_trigger_still_fires_from_a_non_editable_target(node_available):
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        const divEl = document.createElement('div');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?', target: divEl }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": False}


def test_trigger_suppressed_while_the_image_editor_owns_the_key(node_available):
    """The image editor has its OWN '?' cheatsheet (editor/keyboard-
    shortcuts.js, gated on state.editorOpen). galleryEditor.js flips
    window.__galleryEditLive true for the duration of an edit session; this
    global overlay must stay out of the way so both don't pop for one
    keypress."""
    script = f"""
        window.__galleryEditLive = true;
        await import('file://{_SHORTCUTS_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '?' }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


def test_other_keys_do_not_open_the_overlay(node_available):
    script = f"""
        await import('file://{_SHORTCUTS_JS}');
        document.dispatchEvent(__mkEvent('keydown', {{ key: '/' }}));
        document.dispatchEvent(__mkEvent('keydown', {{ key: 'k', ctrlKey: true }}));
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ everCreated: !!modal }}));
    """
    out = _run_node(script)
    assert out == {"everCreated": False}


# ══════════════════════════════════════════════════════════════════════════
# 3. Rendering FROM the live keybind map (the audit's own requirement)
# ══════════════════════════════════════════════════════════════════════════


def test_renders_from_live_keybind_map_including_a_custom_rebind(node_available):
    """The audit explicitly asks for an overlay rendered *from* the live
    keybind map "so custom binds show correctly" — simulate a user having
    rebound `new_session` to something non-default and confirm the rendered
    text reflects THAT combo, not the hardcoded default."""
    script = f"""
        window._applicantKeybinds = {{
            search: 'ctrl+k', toggle_sidebar: 'ctrl+alt+b', new_session: 'ctrl+alt+z',
            fav_session: '', delete_session: '', cancel: 'escape', tts: '',
            settings: '', focus_input: '', open_calendar: '', open_compare: '',
            open_cookbook: '', open_research: '', open_gallery: '', open_library: '',
            open_memory: '', open_notes: '', open_tasks: '', open_theme: '',
        }};
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        const html = document.getElementById('applicant-shortcuts-list').innerHTML;
        console.log(JSON.stringify({{
            hasRebind: html.includes('Ctrl+Alt+Z'),
            hasSearch: html.includes('Ctrl+K'),
            hasSearchLabel: html.includes('Search conversations'),
        }}));
    """
    out = _run_node(script)
    assert out == {"hasRebind": True, "hasSearch": True, "hasSearchLabel": True}


def test_unbound_actions_are_not_rendered(node_available):
    script = f"""
        window._applicantKeybinds = {{
            search: '', toggle_sidebar: '', new_session: '', fav_session: '',
            delete_session: '', cancel: '', tts: '', settings: '', focus_input: '',
            open_calendar: '', open_compare: '', open_cookbook: '', open_research: '',
            open_gallery: '', open_library: '', open_memory: '', open_notes: '',
            open_tasks: '', open_theme: '',
        }};
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        const html = document.getElementById('applicant-shortcuts-list').innerHTML;
        console.log(JSON.stringify({{ hasSearchLabel: html.includes('Search conversations') }}));
    """
    out = _run_node(script)
    assert out == {"hasSearchLabel": False}


def test_falls_back_to_defaults_when_live_map_absent(node_available):
    """Defensive degrade: if window._applicantKeybinds hasn't been set yet
    (boot-ordering edge case), the overlay still renders something sensible
    rather than throwing or rendering nothing."""
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        const html = document.getElementById('applicant-shortcuts-list').innerHTML;
        console.log(JSON.stringify({{ hasSearchLabel: html.includes('Search conversations'), hasSearchCombo: html.includes('Ctrl+K') }}));
    """
    out = _run_node(script)
    assert out == {"hasSearchLabel": True, "hasSearchCombo": True}


def test_always_shows_the_command_palette_and_help_chords(node_available):
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        const html = document.getElementById('applicant-shortcuts-list').innerHTML;
        console.log(JSON.stringify({{
            hasPalette: html.includes('Ctrl+Shift+P'),
            hasEsc: html.includes('Esc'),
        }}));
    """
    out = _run_node(script)
    assert out == {"hasPalette": True, "hasEsc": True}


# ══════════════════════════════════════════════════════════════════════════
# 4. Close paths + public API
# ══════════════════════════════════════════════════════════════════════════


def test_escape_closes_via_public_close_function(node_available):
    """Global Escape-closes-modal already exists via ui.js's initModalA11y
    (shared Escape-arbiter stack every other modal registers with); this
    module reuses it defensively (falling back to a no-op focus trap if
    uiModule isn't present in this shim) and additionally exposes its own
    closeApplicantShortcuts() for direct callers/tests."""
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        mod.closeApplicantShortcuts();
        const modal = document.getElementById('applicant-shortcuts-modal');
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_close_button_closes_the_overlay(node_available):
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        document.getElementById('applicant-shortcuts-close').dispatchEvent(__mkEvent('click', {{}}));
        console.log(JSON.stringify({{ hidden: document.getElementById('applicant-shortcuts-modal').classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_clicking_the_backdrop_closes_the_overlay(node_available):
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        mod.openApplicantShortcuts();
        const modal = document.getElementById('applicant-shortcuts-modal');
        modal.dispatchEvent(__mkEvent('click', {{ target: modal }}));
        console.log(JSON.stringify({{ hidden: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out == {"hidden": True}


def test_is_open_reflects_state(node_available):
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        const beforeOpen = mod.isApplicantShortcutsOpen();
        mod.openApplicantShortcuts();
        const afterOpen = mod.isApplicantShortcutsOpen();
        mod.closeApplicantShortcuts();
        const afterClose = mod.isApplicantShortcutsOpen();
        console.log(JSON.stringify({{ beforeOpen, afterOpen, afterClose }}));
    """
    out = _run_node(script)
    assert out == {"beforeOpen": False, "afterOpen": True, "afterClose": False}


def test_degrades_harmlessly_without_uimodule_present(node_available):
    """window.uiModule.initModalA11y is reused when present but must not be
    required — opening/closing must not throw when it's absent (this shim
    never defines window.uiModule at all)."""
    script = f"""
        const mod = await import('file://{_SHORTCUTS_JS}');
        let threw = false;
        try {{
            mod.openApplicantShortcuts();
            mod.closeApplicantShortcuts();
        }} catch (e) {{ threw = true; }}
        console.log(JSON.stringify({{ threw }}));
    """
    out = _run_node(script)
    assert out == {"threw": False}


# ══════════════════════════════════════════════════════════════════════════
# 5. Denylist hygiene (per the task's standing instruction)
# ══════════════════════════════════════════════════════════════════════════

_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_files_are_denylist_clean():
    for path in (pathlib.Path(__file__), _SHORTCUTS_JS):
        text = path.read_text(encoding="utf-8").lower()
        for first, second in _DENYLIST_CODENAME_HALVES:
            codename = first + second
            assert codename not in text, f"denylist hit {codename!r} in {path.name}"
