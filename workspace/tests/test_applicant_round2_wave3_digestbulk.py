"""Regression coverage for docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md §4J
"Cross-cutting quick wins" (quick-wins-cross-cutting.md lens), the two items in
this batch — confined to ``static/js/emailLibrary/applicantDigest.js`` (the
Email tab's "Daily updates" digest panel).

## Item 1 — "Bulk digest actions"

**Genuine gap, closed here.** Before this batch, ``applicantDigest.js`` (read
in full, current state — the file was already touched by an earlier round-2
wave for hidden-tab polling) let the user act on postings only ONE ROW AT A
TIME: each digest row rendered its own Approve/Pass/Research buttons
(``buildDigestRow`` -> ``_onApprove``/``_onPass``), with no selection
affordance and no way to approve/decline more than one role without repeating
the click-through-styledPrompt flow per row. There was no "select multiple"
UI anywhere in this file.

**No genuine bulk *approve/decline* engine endpoint exists to call once
instead.** Searched the engine + the workspace proxy layer before writing any
code:
  - ``src/applicant/app/routers/pending_actions.py``'s
    ``POST /{campaign_id}/resolve-bulk`` (and the workspace's own
    ``applicant_portal_routes.py`` ``/actions/resolve-bulk`` /
    ``applicant_engine.py``'s ``resolve_pending_actions_bulk``) IS a real bulk
    endpoint, but it operates on **pending-action ids** (Portal to-do items)
    and just *resolves/clears* the notification — it does not call
    ``digest.approve``/``digest.decline`` on the underlying application. Using
    it here would silently dismiss the digest notification without actually
    approving or declining the role.
  - Even the engine's OWN chat "approve all today's roles" directive
    (``ChatService._do_approve_all`` in
    ``src/applicant/application/services/chat_service.py``) does not call a
    bulk endpoint either — it lists the open ``digest_approval`` pending
    actions and loops ``self._digest.approve(posting_id)`` **once per
    posting**, explicitly commented as "the SAME gated decision path a single
    approve uses — chat never bypasses the per-application gate."
  - The workspace proxy (``workspace/routes/applicant_email_routes.py``) only
    exposes the per-application ``POST /applications/{id}/approve`` and
    ``POST /applications/{id}/decline`` this file already calls from
    ``_onApprove``/``_onPass`` — no bulk variant.

So the fix mirrors the engine's own precedent: a checkbox per row
(``.memory-select-cb`` — the SAME checkbox class + "selected" card-highlight
CSS already used by ``documentLibrary.js``'s bulk-select mode, not an invented
class), a "N selected" count + "All" toggle (``.memory-bulk-check-all``, same
class as ``documentLibrary.js``), and "Approve selected" / "Decline selected"
buttons (``.memory-toolbar-btn``, the row's own existing button class) that
loop the exact same ``/applications/{id}/approve`` / ``/applications/{id}/
decline`` calls ``_onApprove``/``_onPass`` already make, one request per
selected row — see ``_onBulkApprove``/``_onBulkDecline``. The bulk-decline
path reuses the single-row Pass flow's mandatory-feedback ``styledPrompt``
(one shared reason for the whole batch, since the engine requires non-blank
feedback per decline).

The new checkbox is a strict **opt-in** threaded through ``buildDigestRow``'s
existing ``ctx`` parameter (``ctx.selectable``/``ctx.isSelected``/
``ctx.onToggleSelect``) so the Portal's home-base embed
(``applicantPortal.js``'s ``buildDigestRow(row, { getCampaignId, onResolved
})`` call, NOT touched by this batch — out of scope per the task's file
boundary) keeps rendering the exact same row it always has, with no checkbox.

## Item 2 — "Freshness 'updated Ns ago'"

**Genuine gap, closed here.** Before this batch the panel had no freshness
indicator anywhere — no "Last updated" / "Updated just now" text in the head
or the empty-day state; a user reopening the popup after a while had no way
to tell whether the on-screen list was from just now or a stale prior load.

None of the workspace's existing relative-time helpers are exported from
their modules (checked ``applicantActivity.js``'s ``_relTime``,
``memory.js``'s ``relativeTime``, ``tasks.js``'s ``_relativeTime``,
``appkitStatusPanel.js``'s ``relativeTime`` — all module-private, no
``export``), and this batch's file boundary is ``applicantDigest.js`` only
(the task explicitly forbids touching ``applicantActivity.js`` or any other
file to add an export), so a local ``_relWhen`` helper was written using the
SAME phrasing convention as ``applicantActivity.js``'s ``_relTime`` ("just
now" / "Nm ago" / "Nh ago" / "Nd ago" / locale date beyond 30 days) rather
than inventing new wording.

A small ``#applicant-digest-freshness`` span next to the campaign picker now
reads "Updated <_relWhen(loadedAt)>", set on every successful digest load and
cleared when there is no campaign to show. To age "just now" forward into
"5m ago" etc. without polling the engine again, its text re-renders on each
tick of the presence heartbeat's EXISTING ~60s ``setInterval`` (see
``_signalPresence``) rather than adding a second timer — the
``test_applicant_round2_wave1_polling.py`` regression file pins this file to
exactly one ``setInterval`` (the presence heartbeat, guarding against an
unguarded content-poll loop reappearing), and that invariant still holds
after this change (see ``test_freshness_ticks_via_the_existing_presence_
heartbeat_not_a_new_interval`` below, which re-confirms it from this file
too).

## Test approach

Real JS execution: most tests below drive the ACTUAL, unmodified
``applicantDigest.js`` module through a hand-rolled DOM/window/document shim
(the parsing-innerHTML variant from
``test_applicant_round2_wave3_hashrouting.py`` / ``test_applicant_round2_
wave3_quickwins.py``, adapted verbatim), with its two collaborators
(``../ui.js``, ``./digestEmailPreview.js``) redirected via a ``node:module``
``resolve()`` loader hook to small recording stubs, and ``fetch`` mocked to
serve canned digest/campaign/approve/decline responses while recording every
call. A couple of pure-formatting checks extract ``_relWhen`` by source regex
and run it standalone (same technique as ``test_applicant_round2_wave1_
polling.py``'s ``pollVisible`` test), since it has no DOM dependency.

Every assertion below was verified failing by hand (temporarily reverting the
exact source change it protects — the checkbox render, the bulk-loop calls,
the freshness span, the single-setInterval piggyback — confirming a real
``AssertionError``, then restoring, ``git diff`` clean afterward) before this
file was landed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
_HAS_NODE = shutil.which("node") is not None

JS_DIR = _REPO / "static" / "js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"
DIGEST_URL = f"file://{DIGEST_JS}"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── minimal DOM/window/document shim, WITH a real innerHTML->DOM parser ────
#
# applicantDigest.js builds its panel from one big template-literal
# `.innerHTML = \`...\`` and then does `.querySelector('#...')` against the
# result, exactly like applicantVault.js / applicantActivity.js — adapted
# verbatim from test_applicant_round2_wave3_quickwins.py's shim.
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
  constructor(tag){ super(); this.nodeType=1; this.tagName=String(tag).toUpperCase(); this._attrs=new Map(); this.children=[]; this.parentNode=null; this.classList=new ClassList(); this.style=makeStyle(); this._text=''; this._html=''; this.dataset={}; this.value=''; this.disabled=false; this.checked=false; this._selected=false; }
  get id(){ return this._attrs.get('id')||''; }
  set id(v){ this._attrs.set('id', v); }
  get className(){ return this.classList.value; }
  set className(v){ this.classList=new ClassList(); (v||'').split(/\s+/).filter(Boolean).forEach(c=>this.classList.add(c)); }
  setAttribute(k,v){ this._attrs.set(k,String(v)); if(k==='class') this.className=String(v); }
  getAttribute(k){ return this._attrs.has(k)? this._attrs.get(k): null; }
  hasAttribute(k){ return this._attrs.has(k); }
  removeAttribute(k){ this._attrs.delete(k); }
  // Minimal <select>/<option> sync: matches real-DOM behavior enough for
  // _currentCampaign()'s `sel.value` read — an <option selected> updates its
  // parent <select>'s .value on whichever happens first, setting `.selected`
  // (already attached) or appendChild (attached after being marked selected,
  // the order applicantDigest.js's _populateCampaigns actually uses).
  get selected(){ return this._selected; }
  set selected(v){
    this._selected = !!v;
    if (v && this.parentNode && this.parentNode.tagName === 'SELECT') {
      this.parentNode.value = this.hasAttribute('value') ? this.getAttribute('value') : this.textContent;
    }
  }
  appendChild(c){
    if(c.parentNode) c.parentNode.removeChild(c);
    this.children.push(c);
    c.parentNode=this;
    if (this.tagName === 'SELECT' && c.tagName === 'OPTION' && c._selected) {
      this.value = c.hasAttribute('value') ? c.getAttribute('value') : c.textContent;
    }
    return c;
  }
  removeChild(c){ const i=this.children.indexOf(c); if(i>=0) this.children.splice(i,1); c.parentNode=null; return c; }
  remove(){ if(this.parentNode) this.parentNode.removeChild(this); }
  insertBefore(n,ref){ if(n.parentNode) n.parentNode.removeChild(n); if(ref==null) this.children.push(n); else { const i=this.children.indexOf(ref); this.children.splice(i<0?this.children.length:i,0,n); } n.parentNode=this; return n; }
  get isConnected(){ let n=this; while(n.parentNode) n=n.parentNode; return n===DOC.body || n===DOC.head; }
  querySelectorAll(sel){ return queryDescendants(this, sel); }
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
// Supports comma-separated groups AND simple space-separated descendant
// combinators (e.g. "#applicant-digest-body .applicant-digest-row"), which
// applicantDigest.js's real select-all handler actually uses — the borrowed
// base shim only matched single simple-selector-with-:not() tokens.
function queryDescendants(root, sel){
  const results = [];
  for (const group of sel.split(',').map(s=>s.trim()).filter(Boolean)) {
    const parts = group.split(/\s+/).filter(Boolean);
    for (const el of collectDescendants(root)) {
      if (!matchesSimple(el, parts[parts.length-1])) continue;
      let ok = true, anc = el.parentNode, idx = parts.length-2;
      while (idx >= 0) {
        while (anc && !matchesSimple(anc, parts[idx])) anc = anc.parentNode;
        if (!anc) { ok = false; break; }
        idx--; anc = anc.parentNode;
      }
      if (ok && !results.includes(el)) results.push(el);
    }
  }
  return results;
}
// Minimal HTML->DOM parser (adapted verbatim from
// test_applicant_round2_wave3_hashrouting.py / _quickwins.py's shim): nested
// tags, quoted attributes, self-closing/void tags. Good enough for the
// controlled, hand-written panel markup under test here.
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
  constructor(){ super(); this.body=new Element('body'); this.head=new Element('head'); this.activeElement=null; this.visibilityState='visible'; }
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
const win = new WindowObj();
win.document = DOC;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
win.location = { origin: 'http://localhost', href: 'http://localhost/email', hash: '' };
globalThis.window = win;
"""

# Redirect applicantDigest.js's two collaborators (../ui.js,
# ./digestEmailPreview.js) to small recording stubs, leaving
# applicantDigest.js's OWN code untouched and really executing — same
# node:module technique as test_applicant_round1_missingkits.py /
# test_applicant_round2_wave3_quickwins.py.
_COLLAB_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === '../ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(\`
        export function showToast(msg) {
          globalThis.__toasts = globalThis.__toasts || [];
          globalThis.__toasts.push(msg);
        }
        export function styledPrompt(message, opts) {
          globalThis.__styledPromptCalls = globalThis.__styledPromptCalls || [];
          globalThis.__styledPromptCalls.push({ message, opts });
          const r = globalThis.__styledPromptResolve;
          return Promise.resolve(typeof r === 'function' ? r() : r);
        }
        export function styledConfirm(message, opts) {
          globalThis.__styledConfirmCalls = globalThis.__styledConfirmCalls || [];
          globalThis.__styledConfirmCalls.push({ message, opts });
          const r = globalThis.__styledConfirmResolve;
          return Promise.resolve(typeof r === 'function' ? r() : !!r);
        }
      \`),
      shortCircuit: true,
    };
  }
  if (specifier === './digestEmailPreview.js' || specifier.endsWith('/digestEmailPreview.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(\`
        export async function showDigestEmailPreview(campaignId) {
          globalThis.__previewCalls = globalThis.__previewCalls || [];
          globalThis.__previewCalls.push(campaignId);
        }
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


# Fetch stub shared by every full-mount script below: serves the
# features/campaigns/digest/approve/decline/presence endpoints this module
# calls, recording every call into globalThis.__fetchCalls so tests can assert
# on exactly what was requested. Per-test fixtures (globalThis.__campaigns /
# globalThis.__digestRows) are set AFTER this stub (it reads them lazily, at
# call time) and BEFORE mountApplicantDigest() is invoked.
_FETCH_STUB = r"""
globalThis.__fetchCalls = [];
globalThis.__toasts = [];
globalThis.fetch = async (url, opts) => {
  opts = opts || {};
  const method = opts.method || 'GET';
  let bodyParsed = null;
  if (opts.body) { try { bodyParsed = JSON.parse(opts.body); } catch (_e) { bodyParsed = opts.body; } }
  globalThis.__fetchCalls.push({ url, method, body: bodyParsed });
  const mk = (status, json) => ({ ok: status >= 200 && status < 300, status, json: async () => json });
  if (url.endsWith('/api/applicant/features')) {
    return mk(200, { sections: { email: { state: 'active' } } });
  }
  if (url.endsWith('/api/applicant/email/campaigns')) {
    const campaigns = globalThis.__campaigns || [{ id: 'camp-1', name: 'Search 1' }];
    return mk(200, { campaigns });
  }
  if (/\/api\/applicant\/email\/digest\/[^/]+$/.test(url)) {
    return mk(200, { rows: globalThis.__digestRows || [] });
  }
  if (/\/api\/applicant\/email\/applications\/[^/]+\/(approve|decline)$/.test(url)) {
    return mk(200, {});
  }
  if (url.endsWith('/api/applicant/email/presence')) {
    return mk(200, {});
  }
  return mk(200, {});
};
"""

# Builds a modal with the native #email-lib-grid host, attached to
# document.body — the exact shape _ensurePanel()/mountApplicantDigest() need.
_BUILD_MODAL = r"""
const modal = document.createElement('div');
const grid = document.createElement('div');
grid.id = 'email-lib-grid';
modal.appendChild(grid);
document.body.appendChild(modal);
"""


def _mount_script(fixtures: str, body: str) -> str:
    """Assemble a full node script: fetch stub -> import -> fixtures -> mount -> body."""
    return (
        _FETCH_STUB
        + "\nconst mod = await import('" + DIGEST_URL + "');\n"
        + fixtures
        + _BUILD_MODAL
        + "\nawait mod.mountApplicantDigest(modal);\n"
        + "const panel = document.getElementById('applicant-digest-panel');\n"
        + body
    )


# ── Item 1: bulk digest actions ─────────────────────────────────────────────


def test_build_digest_row_checkbox_is_opt_in_via_ctx_selectable(node_available):
    """buildDigestRow only renders the new selection checkbox when explicitly
    opted in via ctx.selectable=true. The Portal's home-base call site
    (applicantPortal.js's `buildDigestRow(row, { getCampaignId, onResolved
    })`, out of this batch's scope, not touched) keeps calling it exactly as
    before and must see NO checkbox — this is the backward-compat contract
    that lets the bulk feature live only in the Email panel."""
    script = (
        _FETCH_STUB
        + "\nconst mod = await import('" + DIGEST_URL + "');\n"
        + r"""
        const rowPortalStyle = mod.buildDigestRow(
          { id: 'p1', title: 'Engineer', company: 'Acme' },
          { getCampaignId: () => 'camp-1', onResolved: () => {} },
        );
        const rowSelectable = mod.buildDigestRow(
          { id: 'p2', title: 'Designer', company: 'Beta' },
          { selectable: true, isSelected: false, onToggleSelect: () => {} },
        );
        const rowSelectedTrue = mod.buildDigestRow(
          { id: 'p3', title: 'Manager', company: 'Gamma' },
          { selectable: true, isSelected: true, onToggleSelect: () => {} },
        );
        console.log(JSON.stringify({
          portalStyleHasCheckbox: !!rowPortalStyle.querySelector('.applicant-digest-select'),
          selectableHasCheckbox: !!rowSelectable.querySelector('.applicant-digest-select'),
          selectableCheckedInitially: rowSelectable.querySelector('.applicant-digest-select').checked,
          preSelectedIsChecked: rowSelectedTrue.querySelector('.applicant-digest-select').checked,
        }));
        """
    )
    out = _run_node(script)
    assert out["portalStyleHasCheckbox"] is False
    assert out["selectableHasCheckbox"] is True
    assert out["selectableCheckedInitially"] is False
    assert out["preSelectedIsChecked"] is True


def test_mount_renders_one_checkbox_per_row_and_bulk_bar_starts_hidden(node_available):
    fixtures = "globalThis.__digestRows = [" \
        "{ id: 'a1', title: 'Engineer', company: 'Acme' }, " \
        "{ id: 'a2', title: 'Designer', company: 'Beta' }];\n"
    body = r"""
        const rows = panel.querySelectorAll('.applicant-digest-row');
        const cbs = panel.querySelectorAll('.applicant-digest-select');
        const bar = document.getElementById('applicant-digest-bulk-bar');
        console.log(JSON.stringify({
          rowCount: rows.length,
          checkboxCount: cbs.length,
          barDisplay: bar.style.display,
          countText: document.getElementById('applicant-digest-selected-count').textContent,
        }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["rowCount"] == 2
    assert out["checkboxCount"] == 2
    assert out["barDisplay"] == "none"
    assert out["countText"] == "0 selected"


def test_checking_rows_updates_bulk_bar_visibility_and_count(node_available):
    fixtures = "globalThis.__digestRows = [" \
        "{ id: 'a1', title: 'Engineer', company: 'Acme' }, " \
        "{ id: 'a2', title: 'Designer', company: 'Beta' }];\n"
    body = r"""
        const cbs = panel.querySelectorAll('.applicant-digest-select');
        cbs[0].checked = true;
        cbs[0]._l['change'][0]({});
        const afterOne = {
          display: document.getElementById('applicant-digest-bulk-bar').style.display,
          count: document.getElementById('applicant-digest-selected-count').textContent,
        };
        cbs[1].checked = true;
        cbs[1]._l['change'][0]({});
        const afterTwo = {
          count: document.getElementById('applicant-digest-selected-count').textContent,
        };
        // Unchecking one must decrement, not just toggle a boolean.
        cbs[0].checked = false;
        cbs[0]._l['change'][0]({});
        const afterUncheckOne = {
          count: document.getElementById('applicant-digest-selected-count').textContent,
          display: document.getElementById('applicant-digest-bulk-bar').style.display,
        };
        console.log(JSON.stringify({ afterOne, afterTwo, afterUncheckOne }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["afterOne"] == {"display": "flex", "count": "1 selected"}
    assert out["afterTwo"]["count"] == "2 selected"
    assert out["afterUncheckOne"] == {"count": "1 selected", "display": "flex"}


def test_select_all_checkbox_selects_and_clears_every_row(node_available):
    fixtures = "globalThis.__digestRows = [" \
        "{ id: 'a1', title: 'Engineer', company: 'Acme' }, " \
        "{ id: 'a2', title: 'Designer', company: 'Beta' }];\n"
    body = r"""
        const selectAll = document.getElementById('applicant-digest-select-all');
        selectAll.checked = true;
        selectAll._l['change'][0]({});
        const cbs = panel.querySelectorAll('.applicant-digest-select');
        const afterSelectAll = {
          count: document.getElementById('applicant-digest-selected-count').textContent,
          allChecked: Array.from(cbs).every(cb => cb.checked === true),
        };
        selectAll.checked = false;
        selectAll._l['change'][0]({});
        const afterClearAll = {
          count: document.getElementById('applicant-digest-selected-count').textContent,
          noneChecked: Array.from(cbs).every(cb => cb.checked === false),
          display: document.getElementById('applicant-digest-bulk-bar').style.display,
        };
        console.log(JSON.stringify({ afterSelectAll, afterClearAll }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["afterSelectAll"] == {"count": "2 selected", "allChecked": True}
    assert out["afterClearAll"] == {"count": "0 selected", "noneChecked": True, "display": "none"}


def test_bulk_approve_selected_loops_the_same_per_row_approve_endpoint(node_available):
    """The core of item 1: 'Approve selected' must call the SAME per-
    application /applications/{id}/approve endpoint _onApprove already uses,
    once per selected row — not a new bulk-approve route."""
    fixtures = "globalThis.__digestRows = [" \
        "{ id: 'a1', title: 'Engineer', company: 'Acme' }, " \
        "{ id: 'a2', title: 'Designer', company: 'Beta' }];\n"
    body = r"""
        const cbs = panel.querySelectorAll('.applicant-digest-select');
        cbs.forEach(cb => { cb.checked = true; cb._l['change'][0]({}); });
        globalThis.__fetchCalls = []; // isolate: only capture the bulk-approve request wave
        const approveBtn = document.getElementById('applicant-digest-approve-selected');
        await approveBtn._l['click'][0]({});
        const approveCalls = globalThis.__fetchCalls.filter(c => c.method === 'POST' && c.url.includes('/approve'));
        console.log(JSON.stringify({
          approveUrls: approveCalls.map(c => c.url).sort(),
          countAfter: document.getElementById('applicant-digest-selected-count').textContent,
          barDisplayAfter: document.getElementById('applicant-digest-bulk-bar').style.display,
          toasts: globalThis.__toasts || [],
        }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["approveUrls"] == [
        "http://localhost/api/applicant/email/applications/a1/approve",
        "http://localhost/api/applicant/email/applications/a2/approve",
    ]
    assert out["countAfter"] == "0 selected"
    assert out["barDisplayAfter"] == "none"
    assert any("Approved 2 role" in t for t in out["toasts"])


def test_bulk_decline_selected_prompts_once_and_reuses_the_same_per_row_decline_endpoint(node_available):
    """The decline half: ONE shared styledPrompt for the whole batch (not one
    per row — mirroring the mandatory-feedback UX of the single-row Pass
    button), then the SAME /applications/{id}/decline call per selected row,
    each carrying the shared reason."""
    fixtures = (
        "globalThis.__digestRows = ["
        "{ id: 'a1', title: 'Engineer', company: 'Acme' }, "
        "{ id: 'a2', title: 'Designer', company: 'Beta' }];\n"
        "globalThis.__styledPromptResolve = 'wrong location';\n"
    )
    body = r"""
        const cbs = panel.querySelectorAll('.applicant-digest-select');
        cbs.forEach(cb => { cb.checked = true; cb._l['change'][0]({}); });
        globalThis.__fetchCalls = [];
        const declineBtn = document.getElementById('applicant-digest-decline-selected');
        await declineBtn._l['click'][0]({});
        const declineCalls = globalThis.__fetchCalls.filter(c => c.method === 'POST' && c.url.includes('/decline'));
        console.log(JSON.stringify({
          promptCalls: (globalThis.__styledPromptCalls || []).length,
          declineUrls: declineCalls.map(c => c.url).sort(),
          declineBodies: declineCalls.map(c => c.body),
          countAfter: document.getElementById('applicant-digest-selected-count').textContent,
        }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["promptCalls"] == 1
    assert out["declineUrls"] == [
        "http://localhost/api/applicant/email/applications/a1/decline",
        "http://localhost/api/applicant/email/applications/a2/decline",
    ]
    assert all(b["feedback_text"] == "wrong location" for b in out["declineBodies"])
    assert all(b["criteria_delta"] == {} for b in out["declineBodies"])
    assert out["countAfter"] == "0 selected"


def test_bulk_decline_cancelled_prompt_makes_no_calls_and_keeps_the_selection(node_available):
    fixtures = (
        "globalThis.__digestRows = [{ id: 'a1', title: 'Engineer', company: 'Acme' }];\n"
        "globalThis.__styledPromptResolve = null;\n"  # user cancels
    )
    body = r"""
        const cb = panel.querySelector('.applicant-digest-select');
        cb.checked = true;
        cb._l['change'][0]({});
        globalThis.__fetchCalls = [];
        const declineBtn = document.getElementById('applicant-digest-decline-selected');
        await declineBtn._l['click'][0]({});
        const declineCalls = globalThis.__fetchCalls.filter(c => c.url.includes('/decline'));
        console.log(JSON.stringify({
          declineCallCount: declineCalls.length,
          countAfter: document.getElementById('applicant-digest-selected-count').textContent,
        }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["declineCallCount"] == 0
    assert out["countAfter"] == "1 selected"


def test_reloading_the_digest_clears_any_stale_selection(node_available):
    """Selecting rows, then reloading (Refresh / campaign switch) must drop the
    old selection — otherwise a stale id from a row no longer on screen could
    linger in the bulk-approve/-decline request list."""
    fixtures = "globalThis.__digestRows = [{ id: 'a1', title: 'Engineer', company: 'Acme' }];\n"
    body = r"""
        const cb = panel.querySelector('.applicant-digest-select');
        cb.checked = true;
        cb._l['change'][0]({});
        const beforeReload = document.getElementById('applicant-digest-selected-count').textContent;
        const refreshBtn = document.getElementById('applicant-digest-refresh');
        await refreshBtn._l['click'][0]({});
        const afterReload = {
          count: document.getElementById('applicant-digest-selected-count').textContent,
          display: document.getElementById('applicant-digest-bulk-bar').style.display,
        };
        console.log(JSON.stringify({ beforeReload, afterReload }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["beforeReload"] == "1 selected"
    assert out["afterReload"] == {"count": "0 selected", "display": "none"}


def test_source_bulk_actions_reuse_the_per_row_endpoints_no_new_bulk_route():
    """Source-level guard for the design decision documented in the module
    docstring above: bulk approve/decline must hit the exact same
    per-application URLs as the single-row actions, never a distinct
    bulk-approve/bulk-decline route."""
    src = _read(DIGEST_JS)
    assert src.count("/applications/${encodeURIComponent(id)}/approve") >= 2, (
        "expected the per-application approve URL to be used by both the single-row and bulk paths"
    )
    assert src.count("/applications/${encodeURIComponent(id)}/decline") >= 2, (
        "expected the per-application decline URL to be used by both the single-row and bulk paths"
    )
    assert not re.search(r"/approve-bulk|/decline-bulk|/bulk-approve|/bulk-decline|/applications/bulk", src), (
        "must not introduce a new bulk-approve/bulk-decline engine route"
    )


# ── Item 2: freshness "updated Ns ago" ──────────────────────────────────────


def _extract_rel_when_source() -> str:
    src = _read(DIGEST_JS)
    m = re.search(r"function _relWhen\(value\)\s*\{.*?\n\}\n", src, re.S)
    assert m, "expected `function _relWhen(value) { ... }` in applicantDigest.js"
    return m.group(0)


def test_rel_when_formats_relative_time_consistently_with_the_rest_of_the_app(node_available):
    rel_when_src = _extract_rel_when_source()
    script = (
        rel_when_src
        + r"""
        const now = Date.now();
        console.log(JSON.stringify({
          justNow: _relWhen(now - 5000),
          fiveMinAgo: _relWhen(now - 5 * 60 * 1000),
          threeHoursAgo: _relWhen(now - 3 * 60 * 60 * 1000),
          twoDaysAgo: _relWhen(now - 2 * 24 * 60 * 60 * 1000),
          empty: _relWhen(null),
          emptyString: _relWhen(''),
        }));
        """
    )
    out = _run_node(script)
    assert out["justNow"] == "just now"
    assert out["fiveMinAgo"] == "5m ago"
    assert out["threeHoursAgo"] == "3h ago"
    assert out["twoDaysAgo"] == "2d ago"
    assert out["empty"] == ""
    assert out["emptyString"] == ""


def test_freshness_label_shows_updated_just_now_after_initial_load(node_available):
    fixtures = "globalThis.__digestRows = [{ id: 'a1', title: 'Engineer', company: 'Acme' }];\n"
    body = r"""
        const freshness = document.getElementById('applicant-digest-freshness');
        console.log(JSON.stringify({ text: freshness.textContent }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["text"] == "Updated just now"


def test_freshness_label_clears_when_there_is_no_job_search_to_show(node_available):
    fixtures = "globalThis.__campaigns = [];\n"  # no job search yet -> _loadDigest's early-return branch
    body = r"""
        const freshness = document.getElementById('applicant-digest-freshness');
        console.log(JSON.stringify({ text: freshness.textContent }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["text"] == ""


def test_freshness_label_updates_again_after_a_manual_refresh(node_available):
    """Freshness must reflect the LATEST successful load, not just the first
    one — clicking Refresh re-stamps loadedAt."""
    fixtures = "globalThis.__digestRows = [{ id: 'a1', title: 'Engineer', company: 'Acme' }];\n"
    body = r"""
        const before = document.getElementById('applicant-digest-panel').dataset.loadedAt;
        const refreshBtn = document.getElementById('applicant-digest-refresh');
        await refreshBtn._l['click'][0]({});
        const after = document.getElementById('applicant-digest-panel').dataset.loadedAt;
        console.log(JSON.stringify({
          text: document.getElementById('applicant-digest-freshness').textContent,
          loadedAtAdvanced: Number(after) >= Number(before),
        }));
    """
    out = _run_node(_mount_script(fixtures, body))
    assert out["text"] == "Updated just now"
    assert out["loadedAtAdvanced"] is True


def test_freshness_ticks_via_the_existing_presence_heartbeat_not_a_new_interval():
    """Design-decision guard: the freshness label must age forward by
    piggybacking on the presence heartbeat's EXISTING setInterval, not a
    second timer loop — this file must keep exactly one setInterval (also
    pinned independently by test_applicant_round2_wave1_polling.py's
    test_digest_js_has_no_engine_content_poll_loop)."""
    src = _read(DIGEST_JS)
    assert len(re.findall(r"setInterval\(", src)) == 1, (
        "applicantDigest.js must have exactly one setInterval (the presence heartbeat) — "
        "the freshness label must not add a second interval loop"
    )
    assert "_renderFreshness(_freshnessPanel)" in src, (
        "the presence heartbeat's tick must also refresh the freshness label"
    )
