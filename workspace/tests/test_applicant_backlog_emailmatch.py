"""Regression coverage for phase 3 of the "variable reward" outcome loop
(``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md`` Top-25 #5 / systemic theme
#3): the "suggest-and-confirm" resolution to the automatic-inbox-matching risk
Phase 2 deliberately deferred.

Phase 1 (engine, merged) built ``POST /api/post-submission/applications/{id}/
scan-email`` — classify a pasted email's subject/body and record whatever
confidently matched. Phase 2 (front-door, merged) wired that up as a per-row,
owner-picked "Check an email" paste box (``test_applicant_round2_emailscan_
ui.py``) — safe, but a manual copy-paste chore. This phase removes that tax
WITHOUT reintroducing the mis-attribution risk: ``applicantTracker.js`` now
reads the owner's real inbox (the native workspace email feature's own
``GET /api/email/list`` — read only, never edited here) plus the tracker
board already on screen, and scores candidate (email, application) pairs
CLIENT-SIDE. A match only ever renders as a dismissable SUGGESTION card
("...looks like it might be about your application to X. Is it?"); nothing is
recorded until the owner clicks "Yes, check it", which runs through the exact
same ``${API}/applications/{id}/scan-email`` proxy call Phase 2 already wired
— the engine's own keyword detectors still gate whether anything is actually
recorded. "No / dismiss" (or a confirmed "Yes") is remembered in
``localStorage`` (``applicant_tracker_dismissed_email_matches``) so a
suggestion never re-nags once handled.

Two testing strategies:

  1. The scoring/matching heuristic (``_matchTokenize`` /
     ``_scoreEmailAgainstApplication`` / ``_bestApplicationForEmail`` /
     ``_cheapSubjectHint``) is pure and exported for tests — exercised
     directly via real ``node`` execution, no DOM needed.
  2. The full "Find responses" -> suggestion card -> confirm/dismiss flow,
     including the SAFETY-CRITICAL guarantee that a suggestion never triggers
     the scan-email call until "Yes, check it" is clicked, is exercised for
     REAL via ``node`` against a from-scratch DOM shim (adapted verbatim from
     ``test_applicant_round2_wave3_hashrouting.py`` / ``test_applicant_
     backlog_todaymode.py``) plus a URL-matched ``fetch`` mock that records
     every call, so assertions can pin exactly which endpoints get hit and
     when.

Every ``test_*`` below was verified failing (per this series' standing DoD) by
temporarily reverting the exact source it protects — stripping the button,
un-wiring the click handler, relaxing the tie-skip guard, removing the
dismissed-set gate, or (for the safety assertion) making "Yes" record without
waiting for the confirm click — confirming the assertion actually goes red,
then restoring the original file (clean ``git diff`` afterward) before
landing this file.
"""

from __future__ import annotations

import json
import pathlib
import re
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_TRACKER_JS = _REPO / "static" / "js" / "applicantTracker.js"
_HAS_NODE = shutil.which("node") is not None


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + fetch-mock shim (adapted from test_applicant_backlog_ ─────
# todaymode.py's own _DOM_SHIM; extended with a no-op CSS.escape stub since
# this module's `_removeSuggestionCard` uses it and this simplistic shim's
# querySelector already does raw string attribute matching without needing
# real CSS escaping semantics).

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
  constructor(tag){ super(); this.nodeType=1; this.tagName=String(tag).toUpperCase(); this._attrs=new Map(); this.children=[]; this.parentNode=null; this.classList=new ClassList(); this.style=makeStyle(); this._text=''; this._html=''; this.dataset={}; this.disabled=false; }
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
    const [whole, closeTag, openTag, attrsStr] = m;
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
      if (!_VOID_TAGS.has(openTag.toLowerCase())) stack.push(el);
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
globalThis.CustomEvent = class CustomEvent { constructor(type, o){ this.type=type; this.detail=o&&o.detail; } };
globalThis.MutationObserver = class MutationObserver { constructor(cb){ this.cb=cb; } observe(){} disconnect(){} };
globalThis.CSS = { escape(s){ return String(s); } };
globalThis.localStorage = { _s:{}, getItem(k){ return Object.prototype.hasOwnProperty.call(this._s,k)?this._s[k]:null; }, setItem(k,v){ this._s[k]=String(v); }, removeItem(k){ delete this._s[k]; } };
globalThis.AbortController = class AbortController { constructor(){ this.signal = { aborted:false }; } abort(){ this.signal.aborted = true; } };

const win = new WindowObj();
win.document = DOC;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
globalThis.window = win;

// ── queued/URL-matched fetch mock — records every call so assertions can
// pin exactly which endpoints get hit and when (the safety-critical bit).
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

# applicantTracker.js's import graph is applicantCore.js (-> ui.js) and
# ui.js directly — stubbing './ui.js' (the same technique test_applicant_
# round2_wave3_hashrouting.py / test_applicant_backlog_todaymode.py already
# established) is enough for the rest to resolve and execute for real.
_UI_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = `
export async function resolve(specifier, context, nextResolve) {
  if (specifier === './ui.js' || specifier.endsWith('/ui.js')) {
    return {
      url: 'data:text/javascript,' + encodeURIComponent(
        'export function initModalA11y(el, closeFn) { return function(){}; }' +
        'const uiModule = { showToast: function(){ globalThis.__toastCalls = (globalThis.__toastCalls||[]); globalThis.__toastCalls.push(arguments[0]); }, initModalA11y };' +
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


# A two-application board: one with a distinctive, non-generic token
# ("nimbus") in its campaign name, one entirely generic (every word of
# "Support Specialist" is in the stopword list, so it can never match
# anything) — used to prove the heuristic only fires on a real signal.
_BOARD_RESPONSE = """{
  "engine_available": true, "has_data": true,
  "applications": [
    { "application_id": "app-nimbus", "campaign_id": "c1", "campaign_name": "Nimbus job search",
      "status": "AWAITING_RESPONSE", "job_title": "Backend Engineer", "role_name": "Backend Engineer", "signals": [] },
    { "application_id": "app-generic", "campaign_id": "c1", "campaign_name": "My job search",
      "status": "AWAITING_RESPONSE", "job_title": "Support Specialist", "role_name": "Support Specialist", "signals": [] }
  ]
}"""


def _responder(extra_cases: str = "") -> str:
    return f"""
globalThis.__fetchResponder = (url, method, body) => {{
  if (url === '/api/applicant/tracker' && method === 'GET') {{
    return {{ status: 200, body: {_BOARD_RESPONSE} }};
  }}
  {extra_cases}
  return {{ status: 404, body: {{}} }};
}};
"""


# ══════════════════════════════════════════════════════════════════════════
# 1. Pure scoring/matching heuristic — real execution, no DOM
# ══════════════════════════════════════════════════════════════════════════


def test_tokenize_strips_generic_stopwords_and_short_tokens(node_available):
    script = f"""
        const {{ _matchTokenize }} = await import('file://{_TRACKER_JS}');
        console.log(JSON.stringify({{
          stripped: _matchTokenize('Senior Software Engineer at the Team'),
          keepsDistinctive: _matchTokenize('Nimbus Cloud Platform'),
          dropsShort: _matchTokenize('Go a b c io'),
        }}));
    """
    out = _run_node(script)
    # Every word in "Senior Software Engineer at the Team" is either a
    # stopword or too short -- nothing distinctive survives.
    assert out["stripped"] == []
    assert "nimbus" in out["keepsDistinctive"]
    assert "cloud" in out["keepsDistinctive"]
    assert out["dropsShort"] == []


def test_score_requires_a_real_token_not_just_any_email(node_available):
    script = f"""
        const {{ _scoreEmailAgainstApplication }} = await import('file://{_TRACKER_JS}');
        const app = {{ job_title: 'Backend Engineer', role_name: 'Backend Engineer', campaign_name: 'Nimbus job search' }};
        const genericApp = {{ job_title: 'Support Specialist', role_name: 'Support Specialist', campaign_name: 'My job search' }};
        const matchingEmail = {{ subject: 'Interview invitation from Nimbus', from_name: 'Nimbus Talent', from_address: 'careers@nimbuscloud.io' }};
        const unrelatedEmail = {{ subject: 'Weekly newsletter', from_name: 'Random News', from_address: 'hello@randomsite.com' }};
        console.log(JSON.stringify({{
          matching: _scoreEmailAgainstApplication(matchingEmail, app),
          unrelated: _scoreEmailAgainstApplication(unrelatedEmail, app),
          genericAppNeverMatches: _scoreEmailAgainstApplication(matchingEmail, genericApp),
        }}));
    """
    out = _run_node(script)
    assert out["matching"]["score"] >= 2  # sender-name/domain hit ("nimbus")
    assert out["matching"]["senderHit"] == "nimbus"
    assert out["unrelated"]["score"] == 0
    # A fully-generic application (every field's words are stopwords) can
    # never produce a token to match against -- not even a coincidental hit.
    assert out["genericAppNeverMatches"]["score"] == 0


def test_best_match_skips_ambiguous_ties(node_available):
    script = f"""
        const {{ _bestApplicationForEmail }} = await import('file://{_TRACKER_JS}');
        const appA = {{ application_id: 'a', job_title: 'Nimbus Backend Engineer', role_name: '', campaign_name: '' }};
        const appB = {{ application_id: 'b', job_title: 'Nimbus Frontend Engineer', role_name: '', campaign_name: '' }};
        const email = {{ subject: 'update', from_name: 'Nimbus Talent', from_address: 'careers@nimbuscloud.io' }};
        const best = _bestApplicationForEmail(email, [appA, appB]);
        console.log(JSON.stringify({{ best }}));
    """
    out = _run_node(script)
    # Both apps score identically on the shared "nimbus" token -- an
    # ambiguous tie must never be guessed at.
    assert out["best"] is None


def test_cheap_subject_hint_is_cosmetic_only(node_available):
    script = f"""
        const {{ _cheapSubjectHint }} = await import('file://{_TRACKER_JS}');
        console.log(JSON.stringify({{
          interview: _cheapSubjectHint('Interview invitation'),
          offer: _cheapSubjectHint('Congratulations on your offer'),
          rejected: _cheapSubjectHint('Unfortunately we will not be moving forward'),
          none: _cheapSubjectHint('Your weekly digest'),
        }}));
    """
    out = _run_node(script)
    assert out == {"interview": "interview_invited", "offer": "offer", "rejected": "rejected", "none": None}


# ══════════════════════════════════════════════════════════════════════════
# 2. Full flow — real DOM execution, the safety-critical guarantee
# ══════════════════════════════════════════════════════════════════════════


def test_find_responses_renders_a_suggestion_and_never_calls_scan_email(node_available):
    """THE safety-critical assertion: computing + rendering a suggestion must
    NEVER, by itself, call the scan-email endpoint (or even fetch the email's
    full body) -- both only happen after an explicit "Yes, check it" click."""
    responder = _responder("""
  if (url === '/api/email/list?folder=INBOX&limit=50' && method === 'GET') {
    return { status: 200, body: { total: 2, emails: [
      { uid: 101, subject: 'Interview invitation from Nimbus', from_name: 'Nimbus Talent', from_address: 'careers@nimbuscloud.io', date: '2026-07-01T10:00:00Z', is_read: false },
      { uid: 102, subject: 'Weekly newsletter', from_name: 'Random News', from_address: 'hello@randomsite.com', date: '2026-07-01T09:00:00Z', is_read: true },
    ] } };
  }
""")
    script = f"""
        {responder}
        const mod = await import('file://{_TRACKER_JS}');
        await mod.openApplicantTracker();
        const findBtn = document.getElementById('applicant-tracker-find-emails');
        await findBtn._l.click[0]();
        const list = document.getElementById('applicant-tracker-suggestions-list');
        const cards = list.querySelectorAll('[data-suggestion-key]');
        const scanCalls = globalThis.__fetchCalls.filter(c => c.url.includes('/scan-email'));
        const readCalls = globalThis.__fetchCalls.filter(c => c.url.includes('/api/email/read/'));
        console.log(JSON.stringify({{
          cardCount: cards.length,
          suggestionKey: cards.length ? cards[0].getAttribute('data-suggestion-key') : null,
          scanEmailCallCount: scanCalls.length,
          emailReadCallCount: readCalls.length,
          panelVisible: document.getElementById('applicant-tracker-suggestions').style.display,
        }}));
    """
    out = _run_node(script)
    # Only the Nimbus email/app-nimbus pair clears the bar; the unrelated
    # newsletter and the fully-generic application never do.
    assert out["cardCount"] == 1
    assert out["suggestionKey"] == "101::app-nimbus"
    # THE guarantee: rendering the suggestion touched neither the email body
    # endpoint nor the scan-email endpoint -- nothing was recorded, nothing
    # was even read, from computing/showing the suggestion alone.
    assert out["scanEmailCallCount"] == 0
    assert out["emailReadCallCount"] == 0
    assert out["panelVisible"] == "block"


def test_yes_click_fetches_the_body_then_calls_scan_email_exactly_once(node_available):
    responder = _responder("""
  if (url === '/api/email/list?folder=INBOX&limit=50' && method === 'GET') {
    return { status: 200, body: { total: 1, emails: [
      { uid: 101, subject: 'Interview invitation from Nimbus', from_name: 'Nimbus Talent', from_address: 'careers@nimbuscloud.io', date: '2026-07-01T10:00:00Z', is_read: false },
    ] } };
  }
  if (url === '/api/email/read/101?folder=INBOX' && method === 'GET') {
    return { status: 200, body: { uid: 101, subject: 'Interview invitation from Nimbus', body: 'We would like to schedule an interview with you for the Nimbus role.' } };
  }
  if (url === '/api/applicant/tracker/applications/app-nimbus/scan-email' && method === 'POST') {
    return { status: 200, body: { application_id: 'app-nimbus', detected: true, recorded: true, outcome_type: 'interview_invited' } };
  }
""")
    script = f"""
        {responder}
        const mod = await import('file://{_TRACKER_JS}');
        await mod.openApplicantTracker();
        const findBtn = document.getElementById('applicant-tracker-find-emails');
        await findBtn._l.click[0]();
        const confirmBtn = document.querySelector('[data-suggestion-confirm]');
        await confirmBtn._l.click[0]();
        const scanCalls = globalThis.__fetchCalls.filter(c => c.url.includes('/scan-email'));
        const readCalls = globalThis.__fetchCalls.filter(c => c.url.includes('/api/email/read/'));
        // scan-email must run AFTER the body fetch, carrying the fetched body.
        console.log(JSON.stringify({{
          scanEmailCallCount: scanCalls.length,
          emailReadCallCount: readCalls.length,
          scanBody: scanCalls[0] ? scanCalls[0].body : null,
          scanUrl: scanCalls[0] ? scanCalls[0].url : null,
          toasted: (globalThis.__toastCalls || []).some(t => String(t).includes('recorded')),
          cardRemoved: document.querySelectorAll('[data-suggestion-key]').length,
        }}));
    """
    out = _run_node(script)
    assert out["emailReadCallCount"] == 1
    assert out["scanEmailCallCount"] == 1
    assert out["scanUrl"] == "/api/applicant/tracker/applications/app-nimbus/scan-email"
    assert out["scanBody"]["subject"] == "Interview invitation from Nimbus"
    assert "interview" in out["scanBody"]["body"].lower()
    assert out["toasted"] is True
    assert out["cardRemoved"] == 0  # confirmed suggestion is removed from the panel


def test_dismiss_click_never_calls_scan_email_and_persists_in_local_storage(node_available):
    responder = _responder("""
  if (url === '/api/email/list?folder=INBOX&limit=50' && method === 'GET') {
    return { status: 200, body: { total: 1, emails: [
      { uid: 101, subject: 'Interview invitation from Nimbus', from_name: 'Nimbus Talent', from_address: 'careers@nimbuscloud.io', date: '2026-07-01T10:00:00Z', is_read: false },
    ] } };
  }
""")
    script = f"""
        {responder}
        const mod = await import('file://{_TRACKER_JS}');
        await mod.openApplicantTracker();
        const findBtn = document.getElementById('applicant-tracker-find-emails');
        await findBtn._l.click[0]();
        const dismissBtn = document.querySelector('[data-suggestion-dismiss]');
        dismissBtn._l.click[0]();
        const afterDismissCards = document.querySelectorAll('[data-suggestion-key]').length;
        // A second "Find responses" run must not re-surface the dismissed pair.
        await findBtn._l.click[0]();
        const afterRefindCards = document.querySelectorAll('[data-suggestion-key]').length;
        const stored = JSON.parse(globalThis.localStorage.getItem('applicant_tracker_dismissed_email_matches') || '[]');
        console.log(JSON.stringify({{
          afterDismissCards, afterRefindCards, stored,
          scanEmailCallCount: globalThis.__fetchCalls.filter(c => c.url.includes('/scan-email')).length,
          emailReadCallCount: globalThis.__fetchCalls.filter(c => c.url.includes('/api/email/read/')).length,
        }}));
    """
    out = _run_node(script)
    assert out["afterDismissCards"] == 0
    assert out["afterRefindCards"] == 0  # stays dismissed across a fresh search
    assert "101::app-nimbus" in out["stored"]
    # Dismissing must never touch the email body or scan-email endpoints.
    assert out["scanEmailCallCount"] == 0
    assert out["emailReadCallCount"] == 0


def test_no_candidates_and_email_feature_unreachable_both_show_the_same_graceful_empty_state(node_available):
    responder_no_matches = _responder("""
  if (url === '/api/email/list?folder=INBOX&limit=50' && method === 'GET') {
    return { status: 200, body: { total: 1, emails: [
      { uid: 201, subject: 'Weekly newsletter', from_name: 'Random News', from_address: 'hello@randomsite.com', date: '2026-07-01T09:00:00Z', is_read: true },
    ] } };
  }
""")
    script_no_matches = f"""
        {responder_no_matches}
        const mod = await import('file://{_TRACKER_JS}');
        await mod.openApplicantTracker();
        const findBtn = document.getElementById('applicant-tracker-find-emails');
        await findBtn._l.click[0]();
        const list = document.getElementById('applicant-tracker-suggestions-list');
        console.log(JSON.stringify({{ text: list.innerHTML, btnDisabled: findBtn.disabled }}));
    """
    out_no_matches = _run_node(script_no_matches)
    assert "No likely responses found in your inbox right now" in out_no_matches["text"]
    assert out_no_matches["btnDisabled"] is False  # button is re-enabled, not stuck

    # Email feature unreachable (e.g. not configured) -- 404 from the list
    # endpoint -- must degrade to the exact same graceful message, no error
    # surfaced anywhere and no exception thrown.
    responder_unreachable = _responder("""
  if (url === '/api/email/list?folder=INBOX&limit=50' && method === 'GET') {
    return { status: 404, body: { detail: 'not configured' } };
  }
""")
    script_unreachable = f"""
        {responder_unreachable}
        const mod = await import('file://{_TRACKER_JS}');
        await mod.openApplicantTracker();
        const findBtn = document.getElementById('applicant-tracker-find-emails');
        await findBtn._l.click[0]();
        const list = document.getElementById('applicant-tracker-suggestions-list');
        console.log(JSON.stringify({{ text: list.innerHTML }}));
    """
    out_unreachable = _run_node(script_unreachable)
    assert "No likely responses found in your inbox right now" in out_unreachable["text"]


# ══════════════════════════════════════════════════════════════════════════
# 3. Source-level pins (wiring / reuse / no-regression on Phase 2)
# ══════════════════════════════════════════════════════════════════════════


def test_find_responses_button_exists_and_is_wired_in_the_modal_header():
    src = _read(_TRACKER_JS)
    assert 'id="applicant-tracker-find-emails"' in src
    assert "_onFindResponses(findBtn)" in src


def test_confirm_reuses_the_exact_same_scan_email_endpoint_phase2_wired():
    """The suggestion's "Yes, check it" must POST to the identical URL
    template the row-level "Check an email" flow (Phase 2, `_scanEmail`)
    already uses -- never a new/parallel endpoint."""
    src = _read(_TRACKER_JS)
    scan_email_fn = re.search(r"async function _scanEmail\(btn\) \{.*?\n\}\n", src, re.S)
    confirm_fn = re.search(r"async function _onSuggestionConfirm\(btn\) \{.*?\n\}\n", src, re.S)
    assert scan_email_fn and confirm_fn
    assert "${API}/applications/" in scan_email_fn.group(0) and "/scan-email" in scan_email_fn.group(0)
    assert "${API}/applications/" in confirm_fn.group(0) and "/scan-email" in confirm_fn.group(0)


def test_suggestion_confirm_never_records_without_reading_the_scan_result():
    """Source-level pin alongside the real-execution test above: the confirm
    handler must gate its "recorded" toast/reload on the engine's own
    `detected && recorded` flags -- never assume success from the POST alone."""
    src = _read(_TRACKER_JS)
    fn = re.search(r"async function _onSuggestionConfirm\(btn\) \{.*?\n\}\n", src, re.S)
    assert fn
    assert "scanData && scanData.detected && scanData.recorded" in fn.group(0)


def test_dismissed_matches_use_the_applicant_prefix_localstorage_convention():
    src = _read(_TRACKER_JS)
    assert "'applicant_tracker_dismissed_email_matches'" in src


def test_existing_row_level_check_an_email_affordance_is_untouched():
    """No regression to Phase 2: the per-row disclosure, its scoped id
    threading, and its handler wiring must all still be present verbatim."""
    src = _read(_TRACKER_JS)
    assert "function _scanEmailHTML(id, label)" in src
    assert "data-tracker-scan=\"${id}\"" in src
    assert "data-scan-submit" in src and "_scanEmail(" in src


def test_node_check_applicant_tracker_js(node_available):
    res = subprocess.run(
        ["node", "--check", str(_TRACKER_JS)],
        capture_output=True,
        timeout=15,
        text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"
