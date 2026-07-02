"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md §4J
"Cross-cutting quick wins" (quick-wins-cross-cutting.md lens), the two items in
this batch — confined to this batch's two owned modules: applicantVault.js and
applicantOnboarding.js.

## Item 1 — "Confirm-before-discard on Vault/Onboarding"

**Onboarding: already fully handled going into this batch, no change made.**
`applicantOnboarding.js`'s blocking wizard overlay:
  - has NO close (X) button in its header (`_buildOverlay()` — "no dismiss-into-
    app" by design),
  - explicitly swallows backdrop clicks (`o.addEventListener('click', (ev) => {
    if (ev.target === o) ev.stopPropagation(); })`),
  - already confirms before an Escape-driven discard of unsaved input
    (`_maybeDismiss()` checks `_formDirty`, added in an earlier round-1
    bug-ledger pass), and
  - already opts the ENTIRE overlay out of ui.js's mobile swipe-to-dismiss via
    the static `data-no-swipe-dismiss` attribute on `.modal-content` (also an
    earlier-round fix).
The only remaining exits are the explicit Back/Skip/Continue nav buttons, which
are intentional navigation, not accidental discards. There is no genuine gap
left here — verified by reading the current file in full, not re-fixed.

**Vault: three genuine gaps found and closed here.** `applicantVault.js`'s
credential modal had NO unsaved-input protection at all on any of its three
dismiss paths — the X button, a backdrop click, and Escape (via
`initModalA11y`) all called `closeApplicantVault()` directly, silently
discarding whatever the user had typed into the Google / default-account /
per-site credential fields but not yet saved. A mobile swipe-dismiss (ui.js's
global touchstart handler, engaged for any `.modal` lacking
`data-no-swipe-dismiss`) had the exact same silent-discard problem, and Vault's
modal never opted out.

Fixed (this batch, applicantVault.js only) by adding:
  - `_vaultDirty` (mirrors onboarding's `_formDirty`): set on any `input`/
    `change` event inside the modal, cleared on open and after each
    successful save.
  - `_confirm()` — the SAME async `styledConfirm`-with-`window.confirm`-
    fallback shape already used by `applicantPortal.js`'s `_confirm()` and
    `applicantRemote.js`'s `_confirm()`.
  - `_maybeCloseVault()` — closes immediately when clean; when dirty, awaits
    `_confirm()` (`{confirmText:'Discard', cancelText:'Keep editing',
    danger:true}`) before actually closing. Wired to the X button, the
    backdrop click, AND `initModalA11y`'s Escape callback (previously all
    three called `closeApplicantVault` directly).
  - `_setVaultDirty()` also toggles `data-no-swipe-dismiss` on
    `.modal-content` dynamically (present while dirty, absent while clean) —
    reusing the exact same opt-out hook the onboarding overlay uses
    statically, so a mobile swipe can't bypass the new confirm gate either
    (that gesture hides the modal directly in ui.js, never calling
    `closeApplicantVault`).

## Item 2 — "Persist active campaign" (Vault only; in scope)

`applicantVault.js`'s `_resolveDefaultCampaign()` (used whenever the vault is
opened without an explicit `campaignId`, e.g. Settings' "Saved sign-ins" entry)
always picked `arr[0]` — the first campaign returned by the engine — with no
memory of which campaign the user had last used the vault for. Multi-campaign
users would see the picker silently reset every time.

Fixed by persisting the last-used campaign id to
`localStorage['applicant_vault_last_campaign_id']` (matching the `applicant_`
key-naming precedent already used for small UI-state markers in
`applicantPortal.js`'s `NOTIF_SEEN_KEY` / `RECAP_SEEN_KEY`) every time the
vault opens with a KNOWN campaign (whether passed explicitly or resolved), and
preferring that remembered id — falling back to `arr[0]` when nothing is
remembered or the remembered campaign no longer exists (e.g. deleted) — the
next time the vault opens without an explicit id.

(`applicantDebug.js`'s Activity campaign `<select>` has the same
reset-to-first-campaign behavior but is out of scope for this batch — not
touched here.)

## Test approach

Real JS execution: this file drives the ACTUAL `applicantVault.js` module
through a hand-rolled DOM/window/document shim (the same technique as
`test_applicant_round1_missingkits.py`), with its two collaborators
(`./ui.js`, `./applicantCore.js`) redirected via a `node:module` `resolve()`
loader hook to small recording stubs — so the code under test is 100% the
real, unmodified applicantVault.js, and only its external dependencies (which
have their own coverage elsewhere) are faked.

Every assertion below was verified failing by hand (temporarily reverting the
exact source line it protects, confirming a real `AssertionError`, then
restoring — `git diff` clean afterward) before this file was landed.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── minimal DOM/window/document shim, WITH a real innerHTML->DOM parser ─────
#
# applicantVault.js builds its whole modal from one big template-literal
# `.innerHTML = \`...\`` and then does `.querySelector('#...')` against the
# result — like applicantActivity.js in test_applicant_round2_wave3_hashrouting.py,
# which is where this parsing `innerHTML` setter (`_parseHTMLInto`) comes
# from (adapted verbatim from that file's shim; the plain
# non-parsing-innerHTML shim in test_applicant_round1_missingkits.py is NOT
# enough here since those kits build DOM node-by-node via
# createElement/appendChild and never assign a markup string).
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
  constructor(tag){ super(); this.nodeType=1; this.tagName=String(tag).toUpperCase(); this._attrs=new Map(); this.children=[]; this.parentNode=null; this.classList=new ClassList(); this.style=makeStyle(); this._text=''; this._html=''; this.dataset={}; this.value=''; this.disabled=false; }
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
  scrollIntoView(){ /* no-op */ }
  get textContent(){ return this._text; }
  set textContent(v){ this._text=v==null?'':String(v); this.children=[]; this._html=''; }
  get innerHTML(){ return this._html; }
  set innerHTML(v){ this.children=[]; this._html=v==null?'':String(v); _parseHTMLInto(this, this._html); }
  insertAdjacentHTML(pos, html){ this._html+=html; _parseHTMLInto(this, html); }
}
function collectDescendants(el, acc){ acc=acc||[]; for(const c of el.children){ acc.push(c); collectDescendants(c, acc); } return acc; }
// Minimal HTML->DOM parser (adapted verbatim from
// test_applicant_round2_wave3_hashrouting.py's shim): nested tags, quoted
// attributes, self-closing/void tags. Good enough for the controlled,
// hand-written modal markup under test here — not a general HTML parser.
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
globalThis.localStorage = { _s:{}, getItem(k){ return Object.prototype.hasOwnProperty.call(this._s,k)?this._s[k]:null; }, setItem(k,v){ this._s[k]=String(v); }, removeItem(k){ delete this._s[k]; } };
const win = new WindowObj();
win.document = DOC;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
win.confirm = () => false;  // real fallback path is exercised separately if ever hit
globalThis.window = win;
"""

# Redirect applicantVault.js's two collaborators (./ui.js, ./applicantCore.js)
# to small recording stubs, leaving applicantVault.js's OWN code untouched and
# really executing — same node:module technique as
# test_applicant_round1_missingkits.py / test_applicant_round1_remainder_modalstack.py.
_COLLAB_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === './ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(\`
        export function initModalA11y(el, closeFn) {
          globalThis.__a11yCalls = (globalThis.__a11yCalls||0) + 1;
          globalThis.__a11yCloseFn = closeFn;
          return function(){ globalThis.__a11yCleanupCalls = (globalThis.__a11yCleanupCalls||0) + 1; };
        }
        export function styledConfirm(message, opts) {
          globalThis.__styledConfirmCalls = globalThis.__styledConfirmCalls || [];
          globalThis.__styledConfirmCalls.push({ message, opts });
          const r = globalThis.__styledConfirmResolve;
          return Promise.resolve(typeof r === 'function' ? r() : !!r);
        }
        const uiModule = { initModalA11y, styledConfirm };
        export default uiModule;
      \`),
      shortCircuit: true,
    };
  }
  if (specifier === './applicantCore.js' || specifier.endsWith('/applicantCore.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(\`
        export function esc(s) { return s == null ? '' : String(s); }
        export function _toast(msg) { globalThis.__toasts = globalThis.__toasts || []; globalThis.__toasts.push(msg); }
        export async function _fetchJSON(url, opts) {
          globalThis.__fetchCalls = globalThis.__fetchCalls || [];
          globalThis.__fetchCalls.push(url);
          const h = globalThis.__fetchJSONHandler;
          return typeof h === 'function' ? h(url, opts) : {};
        }
        export async function _post(url, body, opts) {
          globalThis.__postCalls = globalThis.__postCalls || [];
          globalThis.__postCalls.push({ url, body });
          const h = globalThis.__postHandler;
          return typeof h === 'function' ? h(url, body, opts) : {};
        }
        export function errText(err) { return (err && err.message) || 'error'; }
        export function loadingHTML(label) { return '<p>' + (label || '') + '</p>'; }
        export function errorHTML(msg) { return '<p>' + msg + '</p>'; }
        export function wireRetry(el, fn) { /* no-op */ }
      \`),
      shortCircuit: true,
    };
  }
  return nextResolve(specifier, context);
}
`;
register('data:text/javascript,' + encodeURIComponent(__loaderSrc), import.meta.url);
"""


def _run_node(js_body: str) -> dict:
    parts = [_COLLAB_STUB_LOADER, _DOM_SHIM, js_body, "process.exit(0);"]
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


_VAULT_URL = f"file://{_REPO}/static/js/applicantVault.js"

# Fetch handler shared by most scripts: harmless empty responses for the vault
# account-status / tenants-list calls so open() completes cleanly.
_BASE_FETCH_HANDLER = r"""
globalThis.__fetchJSONHandler = (url) => {
  if (url.includes('/vault/account')) return { google: false, predefined_account: false };
  if (url.includes('/tenants')) return { tenants: [] };
  return {};
};
"""


# ── Item 1: confirm-before-discard ──────────────────────────────────────────

def test_vault_clean_close_needs_no_confirm(node_available):
    """A fresh, untouched modal closes immediately on the X button — nothing
    typed, nothing to confirm."""
    script = f"""
        {_BASE_FETCH_HANDLER}
        await import('{_VAULT_URL}');
        await window.openApplicantVault('camp-1');
        const modal = document.getElementById('applicant-vault-modal');
        const closeBtn = document.getElementById('applicant-vault-close');
        globalThis.__styledConfirmCalls = [];
        await closeBtn._l['click'][0]({{}});
        console.log(JSON.stringify({{
          hiddenAfterClose: modal.classList.contains('hidden'),
          confirmCalls: globalThis.__styledConfirmCalls.length,
        }}));
    """
    out = _run_node(script)
    assert out["hiddenAfterClose"] is True
    assert out["confirmCalls"] == 0


def test_vault_dirty_close_via_x_confirms_and_respects_cancel(node_available):
    """Typing into a credential field (simulated by dispatching 'input' on the
    modal, matching the delegated listener `_wire()` installs) then clicking
    the X must go through styledConfirm; declining keeps the modal open."""
    script = f"""
        {_BASE_FETCH_HANDLER}
        await import('{_VAULT_URL}');
        await window.openApplicantVault('camp-1');
        const modal = document.getElementById('applicant-vault-modal');
        const closeBtn = document.getElementById('applicant-vault-close');
        modal.dispatchEvent({{ type: 'input' }});
        globalThis.__styledConfirmResolve = false;  // user picks "Keep editing"
        globalThis.__styledConfirmCalls = [];
        await closeBtn._l['click'][0]({{}});
        console.log(JSON.stringify({{
          hiddenAfterCancel: modal.classList.contains('hidden'),
          confirmCalls: globalThis.__styledConfirmCalls.length,
          confirmOpts: globalThis.__styledConfirmCalls[0] && globalThis.__styledConfirmCalls[0].opts,
        }}));
    """
    out = _run_node(script)
    assert out["hiddenAfterCancel"] is False
    assert out["confirmCalls"] == 1
    assert out["confirmOpts"]["confirmText"] == "Discard"
    assert out["confirmOpts"]["cancelText"] == "Keep editing"


def test_vault_dirty_close_via_x_accepting_discard_closes(node_available):
    """Accepting the discard confirm actually closes the modal."""
    script = f"""
        {_BASE_FETCH_HANDLER}
        await import('{_VAULT_URL}');
        await window.openApplicantVault('camp-1');
        const modal = document.getElementById('applicant-vault-modal');
        const closeBtn = document.getElementById('applicant-vault-close');
        modal.dispatchEvent({{ type: 'input' }});
        globalThis.__styledConfirmResolve = true;  // user picks "Discard"
        await closeBtn._l['click'][0]({{}});
        console.log(JSON.stringify({{ hiddenAfterAccept: modal.classList.contains('hidden') }}));
    """
    out = _run_node(script)
    assert out["hiddenAfterAccept"] is True


def test_vault_backdrop_click_and_escape_also_go_through_confirm(node_available):
    """The backdrop click handler and the Escape callback passed to
    initModalA11y must be the SAME confirm-aware close path as the X button —
    not the raw closeApplicantVault()."""
    script = f"""
        {_BASE_FETCH_HANDLER}
        await import('{_VAULT_URL}');
        await window.openApplicantVault('camp-1');
        const modal = document.getElementById('applicant-vault-modal');
        modal.dispatchEvent({{ type: 'input' }});
        // The backdrop-click listener is a plain (non-async) arrow function
        // that fires-and-forgets _maybeCloseVault() rather than returning its
        // promise — `flush()` lets that inner async chain (styledConfirm ->
        // closeApplicantVault) actually settle before we inspect state, same
        // as a real browser event loop would between the click and the next
        // paint/assertion.
        const flush = () => new Promise((r) => setTimeout(r, 0));

        // Backdrop click: target === modal itself.
        globalThis.__styledConfirmResolve = false;
        globalThis.__styledConfirmCalls = [];
        const modalClickHandlers = modal._l['click'];
        for (const h of modalClickHandlers) h({{ target: modal }});
        await flush();
        const backdropConfirmCalls = globalThis.__styledConfirmCalls.length;
        const hiddenAfterBackdropCancel = modal.classList.contains('hidden');

        // A click INSIDE the modal (target !== modal) must not trigger anything.
        globalThis.__styledConfirmCalls = [];
        for (const h of modalClickHandlers) h({{ target: document.getElementById('applicant-vault-tenant') }});
        await flush();
        const innerClickConfirmCalls = globalThis.__styledConfirmCalls.length;

        // Escape: initModalA11y was called with our confirm-aware close fn.
        globalThis.__styledConfirmResolve = true;
        globalThis.__styledConfirmCalls = [];
        await globalThis.__a11yCloseFn();
        const escapeConfirmCalls = globalThis.__styledConfirmCalls.length;
        const hiddenAfterEscapeAccept = modal.classList.contains('hidden');

        console.log(JSON.stringify({{
          backdropConfirmCalls, hiddenAfterBackdropCancel,
          innerClickConfirmCalls,
          escapeConfirmCalls, hiddenAfterEscapeAccept,
        }}));
    """
    out = _run_node(script)
    assert out["backdropConfirmCalls"] == 1
    assert out["hiddenAfterBackdropCancel"] is False
    assert out["innerClickConfirmCalls"] == 0
    assert out["escapeConfirmCalls"] == 1
    assert out["hiddenAfterEscapeAccept"] is True


def test_vault_dirty_state_opts_out_of_swipe_dismiss_dynamically(node_available):
    """`data-no-swipe-dismiss` (the same opt-out hook applicantOnboarding.js's
    overlay sets statically — see ui.js's touchstart handler) must be present
    on `.modal-content` while there is unsaved input, and absent on a fresh
    open / after a successful save, so a mobile swipe can't bypass the new
    confirm gate (that gesture hides the modal directly, bypassing
    closeApplicantVault entirely)."""
    script = f"""
        {_BASE_FETCH_HANDLER}
        globalThis.__postHandler = (url) => {{
          if (url.includes('/vault/credentials')) return {{ ok: true }};
          return {{}};
        }};
        await import('{_VAULT_URL}');
        await window.openApplicantVault('camp-1');
        const modal = document.getElementById('applicant-vault-modal');
        const content = modal.querySelector('.modal-content');
        const cleanOnOpen = content.hasAttribute('data-no-swipe-dismiss');

        modal.dispatchEvent({{ type: 'input' }});
        const setAfterDirty = content.hasAttribute('data-no-swipe-dismiss');

        // Fill in and save the per-site form -> dirty should clear again.
        document.getElementById('applicant-vault-tenant').value = 'acme.workday.com';
        document.getElementById('applicant-vault-username').value = 'me@example.com';
        document.getElementById('applicant-vault-secret').value = 'hunter2';
        await document.getElementById('applicant-vault-save')._l['click'][0]({{}});
        const clearedAfterSave = content.hasAttribute('data-no-swipe-dismiss');

        console.log(JSON.stringify({{ cleanOnOpen, setAfterDirty, clearedAfterSave }}));
    """
    out = _run_node(script)
    assert out["cleanOnOpen"] is False
    assert out["setAfterDirty"] is True
    assert out["clearedAfterSave"] is False


# ── Item 2: persist active campaign ─────────────────────────────────────────

def test_vault_open_with_explicit_campaign_remembers_it(node_available):
    script = f"""
        {_BASE_FETCH_HANDLER}
        await import('{_VAULT_URL}');
        await window.openApplicantVault('camp-explicit-1');
        console.log(JSON.stringify({{
          stored: globalThis.localStorage.getItem('applicant_vault_last_campaign_id'),
        }}));
    """
    out = _run_node(script)
    assert out["stored"] == "camp-explicit-1"


def test_vault_open_without_campaign_prefers_remembered_over_first(node_available):
    """When opened with NO explicit campaignId, the vault must default to the
    last-remembered campaign (from a prior visit), not always the first one
    the engine's campaign list happens to return."""
    script = f"""
        globalThis.__fetchJSONHandler = (url) => {{
          if (url.includes('/setup/campaigns')) return [{{id:'camp-1'}}, {{id:'camp-2'}}, {{id:'camp-3'}}];
          if (url.includes('/vault/account')) return {{}};
          if (url.includes('/tenants')) return {{ tenants: [] }};
          return {{}};
        }};
        globalThis.localStorage.setItem('applicant_vault_last_campaign_id', 'camp-2');
        await import('{_VAULT_URL}');
        await window.openApplicantVault();
        const tenantsCall = (globalThis.__fetchCalls || []).find(u => u.includes('/tenants'));
        console.log(JSON.stringify({{ tenantsCall }}));
    """
    out = _run_node(script)
    assert "camp-2" in out["tenantsCall"]
    assert "camp-1" not in out["tenantsCall"]


def test_vault_open_without_campaign_falls_back_when_remembered_is_gone(node_available):
    """If the remembered campaign no longer exists (e.g. deleted), fall back
    to the first campaign in the list rather than leaving the vault
    campaign-less."""
    script = f"""
        globalThis.__fetchJSONHandler = (url) => {{
          if (url.includes('/setup/campaigns')) return [{{id:'camp-1'}}, {{id:'camp-2'}}];
          if (url.includes('/vault/account')) return {{}};
          if (url.includes('/tenants')) return {{ tenants: [] }};
          return {{}};
        }};
        globalThis.localStorage.setItem('applicant_vault_last_campaign_id', 'camp-deleted');
        await import('{_VAULT_URL}');
        await window.openApplicantVault();
        const tenantsCall = (globalThis.__fetchCalls || []).find(u => u.includes('/tenants'));
        console.log(JSON.stringify({{ tenantsCall }}));
    """
    out = _run_node(script)
    assert "camp-1" in out["tenantsCall"]


# ── syntax sanity ────────────────────────────────────────────────────────

@pytest.mark.parametrize("relpath", ["static/js/applicantVault.js", "static/js/applicantOnboarding.js"])
def test_file_has_valid_js_syntax(node_available, relpath):
    res = subprocess.run(
        ["node", "--check", str(_REPO / relpath)],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0, res.stderr


# ── Onboarding: confirm the ALREADY-FIXED protections are still in place ───
# (regression guard only — these were fixed in earlier rounds; not re-fixed
# here, just asserted so this batch's audit conclusion stays true over time)

def test_onboarding_overlay_has_no_close_button_and_blocks_backdrop_dismiss():
    src = (_REPO / "static/js/applicantOnboarding.js").read_text()
    # No X / close affordance in the overlay header markup.
    assert "modal-close" not in src
    # Backdrop clicks are explicitly swallowed, not routed to a close/dismiss.
    assert "if (ev.target === o) ev.stopPropagation();" in src


def test_onboarding_escape_confirms_before_discarding_dirty_form():
    src = (_REPO / "static/js/applicantOnboarding.js").read_text()
    assert "if (!_formDirty) { _dismiss(); return; }" in src
    assert "styledConfirm" in src


def test_onboarding_overlay_opts_out_of_swipe_dismiss():
    src = (_REPO / "static/js/applicantOnboarding.js").read_text()
    assert 'data-no-swipe-dismiss' in src


# ── white-label denylist sanity for this new file ───────────────────────────
#: Split into two-piece tuples so the literal, contiguous codename string never
#: appears in this file's own source text (mirrors
#: test_applicant_round1_missingkits.py's precedent).
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


@pytest.mark.parametrize("relpath", [
    "static/js/applicantVault.js",
    "static/js/applicantOnboarding.js",
    "tests/test_applicant_round2_wave3_quickwins.py",
])
def test_no_whitelabel_denylist_hits(relpath):
    text = (_REPO / relpath).read_text()
    lowered = text.lower()
    for first, second in _DENYLIST_CODENAME_HALVES:
        codename = first + second
        assert codename not in lowered, f"white-label denylist hit {codename!r} in {relpath}"
