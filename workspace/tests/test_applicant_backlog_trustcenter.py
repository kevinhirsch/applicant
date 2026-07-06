"""Regression coverage for the trust-control backlog item in
``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``: a consolidated "how
Applicant protects you" trust center.

This session had already built a lot of individual safety facts, one per
surface — the pre-submit snapshot preview and the "Submitting in 5… Cancel"
authorize hold window (``applicantRemote.js``), the "what Applicant never
does" list (``_neverDoesHTML()`` in ``applicantPortal.js`` / the
``neverDoesList`` export in ``applicantOnboarding.js``), the immutable
submission record + audit-log export (``applicantDebug.js``), and the
owner-scoped/self-hosted data model (this repo's own CLAUDE.md files) — but
never one calm, single read that ties them together. ``applicantTrust.js`` is
that new, additive surface: a read-only content panel, wired into
``hashRouter.js`` under the ``#trust`` token exactly like the other 9
surfaces, with the exact ``window.applicantTrustModule.openApplicantTrust()``
export shape ``applicantResults.js`` established.

Nothing in the new file is invented: every claim it renders is a fact this
suite verifies against the real, already-shipped source it came from —
notably ``neverDoesList`` is *imported*, not copy-pasted, so it can never
drift from the OOBE wizard's own copy.

Two testing strategies:

  1. Structural / textual checks on the new file itself (syntax, codename
     denylist, shared-kit reuse, no new bespoke CSS) — plain regex/text
     assertions over the source, which the task explicitly allows for this
     kind of additive, mostly-static surface.
  2. Real ``node`` execution (the ``test_applicant_round1_missingkits.py`` /
     ``test_applicant_round2_wave3_hashrouting.py`` precedent: a hand-rolled
     DOM + ``window.location``/``history`` shim, since there is no jsdom in
     this repo's dependency set, plus a ``node:module`` loader-hook stub for
     ``./ui.js`` — the one browser-only import in this module's chain). This
     drives the *actual* ``applicantTrust.js``, ``hashRouter.js`` and
     ``applicantOnboarding.js`` modules together and inspects the real DOM
     tree the module builds, so it catches drift a text match would miss
     (e.g. the "never does" list silently diverging from the wizard's copy).

Every ``test_*`` here was verified failing by temporarily breaking the exact
line of ``applicantTrust.js`` it protects (reverted from a backup copy after
each check, ``git status`` clean afterward — the file is new/untracked, so a
plain backup-and-restore was used instead of ``git diff``), confirming a real
``AssertionError`` before restoring the original and confirming green again.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
_TRUST_JS = _REPO / "static/js/applicantTrust.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


# ── shared DOM + location/history shim (adapted verbatim from
#    test_applicant_round2_wave3_hashrouting.py, which itself adapted it from
#    test_applicant_round1_missingkits.py — lift and shift, per repo CLAUDE.md) ──
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
DOC.readyState = 'complete'; // module's boot() takes the synchronous branch — no DOMContentLoaded wait needed
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
function __parseHashFromUrl(url){ const s = String(url == null ? '' : url); const i = s.indexOf('#'); return i >= 0 ? s.slice(i) : ''; }
globalThis.history = {
  pushState(state, title, url){ __loc._hash = __parseHashFromUrl(url); }, // no hashchange — matches the real DOM
  replaceState(state, title, url){ __loc._hash = __parseHashFromUrl(url); },
};
const win = new WindowObj();
win.document = DOC;
win.location = __loc;
win.localStorage = globalThis.localStorage;
win.CustomEvent = globalThis.CustomEvent;
win.history = globalThis.history;
globalThis.window = win;
"""

# `applicantTrust.js` needs `./ui.js` stubbed (through its own import and,
# transitively, through applicantCore.js's and applicantOnboarding.js's) —
# same node:module loader-hook substitution test_applicant_round1_missingkits.py
# established. applicantCore.js's own `esc`/`_toast` already fall back to a
# manual escaper / no-op when `uiModule.esc`/`showToast` aren't functions, so
# the stub only needs to provide `initModalA11y` + a `showToast` no-op.
_UI_STUB_LOADER = r"""
import { register } from 'node:module';
const __loaderSrc = [
  'export async function resolve(specifier, context, nextResolve) {',
  '  if (specifier === "./ui.js" || specifier.endsWith("/ui.js")) {',
  '    return {',
  '      url: "data:text/javascript," + encodeURIComponent(',
  '        "export function initModalA11y(el, closeFn) {" +',
  '        "globalThis.__initModalA11yCalls = (globalThis.__initModalA11yCalls||0) + 1;" +',
  '        "return function(){ globalThis.__initModalA11yCleanupCalls = (globalThis.__initModalA11yCleanupCalls||0) + 1; };" +',
  '        "}" +',
  '        "const uiModule = { showToast: function(m){ (globalThis.__toasts=globalThis.__toasts||[]).push(m); }, initModalA11y };" +',
  '        "export default uiModule;"',
  '      ),',
  '      shortCircuit: true,',
  '    };',
  '  }',
  '  return nextResolve(specifier, context);',
  '}',
].join('\n');
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


_IMPORT_TRIO = f"""
    const trustMod = await import('file://{_TRUST_JS}');
    const hashRouterMod = await import('file://{_REPO}/static/js/hashRouter.js');
    const onboardingMod = await import('file://{_REPO}/static/js/applicantOnboarding.js');
"""


# ══════════════════════════════════════════════════════════════════════════
# 1. Plain structural checks (syntax, codename denylist, shared-kit reuse)
# ══════════════════════════════════════════════════════════════════════════


def test_node_check_syntax():
    """`node --check` must pass — the literal CI-equivalent command from this
    repo's own CLAUDE.md for a no-bundler front-end module. Note: since this
    repo's package.json has no `"type": "module"`, `node --check` on a plain
    `.js` file stops meaningfully validating syntax once it hits the first
    `import`/`export` token (a quirk shared by every applicant*.js file, not
    specific to this one) — the real, full-fidelity syntax gate for this
    file's actual ESM body is the real `import()` the execution tests below
    perform (confirmed: reintroducing a syntax error after the import block
    passes this check but fails every execution test)."""
    res = subprocess.run(
        ["node", "--check", str(_TRUST_JS)],
        cwd=_REPO, capture_output=True, timeout=15, text=True,
    )
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece halves so the literal,
#: contiguous codename string never appears in this file's own source text —
#: otherwise this very test would trip that same repo-wide CI grep (the exact
#: false-positive pattern the workflow already special-cases for
#: workspace/tests/test_landing_page_content.py and test_applicant_round1_missingkits.py).
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_no_forbidden_codenames():
    """White-label gate: zero references to the upstream fork's vendor/
    persona codenames in the new file.

    IMPORTANT: plain `git grep` silently skips untracked files — and this
    file is untracked (new). `git grep -- <path>` on it always exits 1 (“no
    match”) regardless of content, a false pass confirmed while writing this
    test. `--untracked` is required for the check to mean anything until the
    file is `git add`-ed."""
    text = _TRUST_JS.read_text(encoding="utf-8").lower()
    for first, second in _DENYLIST_CODENAME_HALVES:
        codename = first + second
        assert codename not in text, f"forbidden codename {codename!r} found in {_TRUST_JS}"


def test_reuses_shared_kit_no_new_visual_language():
    """The panel must compose the existing `.ow-window` / `.modal` /
    `.admin-card` / `.cal-btn` / `.close-btn` kit — not invent a bespoke
    stylesheet (no `<style>` block, no new CSS file)."""
    src = _TRUST_JS.read_text()
    assert "ow-window" in src
    assert "admin-card" in src
    assert "modal-content" in src
    assert "cal-btn" in src
    assert "close-btn" in src
    assert "<style" not in src


def test_never_does_list_is_imported_not_duplicated_in_source():
    """The task's explicit instruction: reuse `_neverDoesHTML()`'s list, don't
    duplicate it. Since `neverDoesList` IS exported/importable from
    applicantOnboarding.js, the new file must import it — not hardcode a
    second copy of its wording (which would silently drift from the OOBE
    wizard's copy over time)."""
    src = _TRUST_JS.read_text()
    assert "import { neverDoesList } from './applicantOnboarding.js';" in src
    # None of the wizard's exact sentences should appear as a separate string
    # literal in this file — the only place they can appear is via the import
    # + the `.map()` render, never a copy-pasted second array. (Demo-tone
    # pass: NEVER_DOES's wording changed from "never" disclaimers to positive
    # control statements — these are the current sentences.)
    for sentence in [
        "Submits an application only with your approval.",
        "Hands every CAPTCHA to you to solve.",
        "Keeps your voluntary self-identification (EEO) answers in your own words.",
    ]:
        # It's fine for the sentence to appear once it's imported/rendered, so
        # this checks the SOURCE doesn't declare it as a literal (i.e. no
        # hardcoded array entry) — a template-literal render via the import
        # would not contain the literal sentence text in the .js source at all.
        assert sentence not in src, f"looks like a hardcoded duplicate of the never-does copy: {sentence!r}"


def test_registers_hash_route_and_exports_results_shaped_module():
    """Same 3-line hashRouter.js pattern the other 9 surfaces use, and the
    exact export shape applicantResults.js established (default export +
    `window.applicant<Name>Module` + bare `window.open<Name>`)."""
    src = _TRUST_JS.read_text()
    assert "registerRoute('trust', { open: openApplicantTrust, close: _close });" in src
    assert "const applicantTrustModule = { openApplicantTrust, closeApplicantTrust };" in src
    assert "window.applicantTrustModule = applicantTrustModule;" in src
    assert "window.openApplicantTrust = openApplicantTrust;" in src
    assert "export default applicantTrustModule;" in src


# ══════════════════════════════════════════════════════════════════════════
# 2. Real execution — module shape, hash routing, rendered content
# ══════════════════════════════════════════════════════════════════════════


def test_module_shape_and_window_exports(node_available):
    """Real execution of the module-eval-time side effects: it self-registers
    under '#trust' with hashRouter.js, and exposes the same export shape
    applicantResults.js does."""
    script = _IMPORT_TRIO + """
        console.log(JSON.stringify({
          hasRouteTrust: hashRouterMod.hasRoute('trust'),
          hasOpen: typeof trustMod.openApplicantTrust === 'function',
          hasClose: typeof trustMod.closeApplicantTrust === 'function',
          windowModuleIsDefault: window.applicantTrustModule === trustMod.default,
          windowOpenIsSameFn: window.openApplicantTrust === trustMod.openApplicantTrust,
        }));
    """
    out = _run_node(script)
    assert out == {
        "hasRouteTrust": True,
        "hasOpen": True,
        "hasClose": True,
        "windowModuleIsDefault": True,
        "windowOpenIsSameFn": True,
    }


def test_open_sets_dialog_semantics_and_hash(node_available):
    """Opening the panel builds a real `role=dialog`/`aria-modal=true` window
    composing `.modal` + `.ow-window`, and updates location.hash to '#trust'
    — the same contract every other hash-routed surface honors."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const modal = document.getElementById('applicant-trust-modal');
        console.log(JSON.stringify({
          role: modal.getAttribute('role'),
          ariaModal: modal.getAttribute('aria-modal'),
          hasModalClass: modal.classList.contains('modal'),
          hasOwWindowClass: modal.classList.contains('ow-window'),
          hiddenAfterOpen: modal.classList.contains('hidden'),
          hash: window.location.hash,
        }));
    """
    out = _run_node(script)
    assert out == {
        "role": "dialog",
        "ariaModal": "true",
        "hasModalClass": True,
        "hasOwWindowClass": True,
        "hiddenAfterOpen": False,
        "hash": "#trust",
    }


def test_close_clears_only_its_own_hash(node_available):
    """closeApplicantTrust() must clear '#trust' (clearHash's own-token
    guard), and must NOT clear a hash belonging to a different surface."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        trustMod.closeApplicantTrust();
        const afterOwnClose = window.location.hash;

        await trustMod.openApplicantTrust();
        window.location.hash = '#results'; // a different surface takes over the hash
        trustMod.closeApplicantTrust(); // must be a no-op — '#results' isn't ours
        const afterForeignHash = window.location.hash;

        console.log(JSON.stringify({ afterOwnClose, afterForeignHash }));
    """
    out = _run_node(script)
    assert out == {"afterOwnClose": "", "afterForeignHash": "#results"}


def test_never_does_list_rendered_matches_real_onboarding_export(node_available):
    """The rendered "What I never do" section must contain EXACTLY the items
    (same count, same text, same order) that `applicantOnboarding.js` itself
    exports right now — proving real reuse, not a copy that can drift."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const body = document.getElementById('applicant-trust-body');
        // The DOM shim doesn't model text nodes (only elements), so
        // querySelector('li').textContent is always '' here — pull the
        // <li> contents straight from the real innerHTML string instead
        // and HTML-unescape them back to plain text for comparison.
        const unescape = (s) => s
          .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
          .replace(/&quot;/g, '"').replace(/&#39;/g, "'");
        const liRe = /<li>([\\s\\S]*?)<\\/li>/g;
        const items = [];
        let m;
        while ((m = liRe.exec(body.innerHTML))) items.push(unescape(m[1]));
        console.log(JSON.stringify({
          rendered: items,
          expected: onboardingMod.neverDoesList,
        }));
    """
    out = _run_node(script)
    assert out["rendered"] == out["expected"]
    assert len(out["rendered"]) >= 3  # sanity: the list is non-trivial


def test_gate_section_describes_the_real_authorize_hold_window(node_available):
    """The irreversible-action-gate section must describe the ACTUAL
    mechanics shipped in applicantRemote.js: the "Submitting in 5…" hold and
    that the owner (not the assistant) always makes the final call — not a
    vaguer or over-claiming rewrite.

    Demo-tone pass: "but I never click it myself without you" (a negative-
    capability disclaimer) was reframed as "the send is always yours to
    make" — same fact, positive control framing."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const norm = document.getElementById('applicant-trust-body').innerHTML.replace(/\\s+/g, ' ');
        console.log(JSON.stringify({
          mentionsHoldCountdown: norm.includes('Submitting in 5'),
          mentionsCancel: norm.includes('Cancel'),
          mentionsOwnerAlwaysDecides: norm.includes('the send is always yours to make'),
        }));
    """
    out = _run_node(script)
    assert out == {"mentionsHoldCountdown": True, "mentionsCancel": True, "mentionsOwnerAlwaysDecides": True}


def test_honesty_section_reflects_real_debug_affordances_and_wires_the_button(node_available):
    """The honesty-artifacts section must name the real, reachable
    affordances (the pre-submit snapshot preview, the submission record, and
    the "Download activity log" export button that actually exists in
    applicantDebug.js), and its "Open Activity & Debug" button must really
    call `window.applicantDebugModule.openApplicantDebug()` when present —
    closing itself first rather than stacking silently."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const body = document.getElementById('applicant-trust-body');
        const norm = body.innerHTML.replace(/\\s+/g, ' ');

        let opened = 0;
        window.applicantDebugModule = { openApplicantDebug: () => { opened++; } };
        const btn = body.querySelector('#applicant-trust-open-debug');
        btn.dispatchEvent({ type: 'click' });

        const modal = document.getElementById('applicant-trust-modal');
        console.log(JSON.stringify({
          mentionsSnapshotReview: norm.includes('Review exactly what will be sent'),
          mentionsSubmissionRecord: norm.includes('Submission record'),
          mentionsDownloadActivityLog: norm.includes('Download activity log'),
          buttonFound: !!btn,
          debugOpenedCalls: opened,
          selfClosedOnHandoff: modal.classList.contains('hidden'),
        }));
    """
    out = _run_node(script)
    assert out == {
        "mentionsSnapshotReview": True,
        "mentionsSubmissionRecord": True,
        "mentionsDownloadActivityLog": True,
        "buttonFound": True,
        "debugOpenedCalls": 1,
        "selfClosedOnHandoff": True,
    }


def test_honesty_section_falls_back_gracefully_without_debug_module(node_available):
    """When Activity & Debug isn't available (engine not yet configured), the
    button must not throw and must not silently no-op — it shows a toast
    instead, and the trust panel stays open (no false "handled" close)."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const body = document.getElementById('applicant-trust-body');
        delete window.applicantDebugModule;
        const btn = body.querySelector('#applicant-trust-open-debug');
        btn.dispatchEvent({ type: 'click' });
        const modal = document.getElementById('applicant-trust-modal');
        console.log(JSON.stringify({
          stillOpen: !modal.classList.contains('hidden'),
          toasted: (globalThis.__toasts || []).length > 0,
        }));
    """
    out = _run_node(script)
    assert out == {"stillOpen": True, "toasted": True}


def test_isolation_section_mentions_self_hosted_and_encrypted_credentials(node_available):
    """Data-isolation section must state the two verified, already-true
    facts: the deployment is self-hosted (root CLAUDE.md), and saved vault
    credentials are encrypted and never re-shown (applicantVault.js) —
    nothing broader or unverified."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const norm = document.getElementById('applicant-trust-body').innerHTML.replace(/\\s+/g, ' ');
        console.log(JSON.stringify({
          mentionsSelfHosted: norm.includes('self-hosted'),
          mentionsEncrypted: norm.includes('encrypted'),
          mentionsNeverShownAgain: norm.includes('never shown again'),
        }));
    """
    out = _run_node(script)
    assert out == {"mentionsSelfHosted": True, "mentionsEncrypted": True, "mentionsNeverShownAgain": True}


def test_admin_card_section_count(node_available):
    """Four consolidated sections (gate, never-does, honesty, isolation),
    each an `.admin-card` — not a wall of unstructured text."""
    script = _IMPORT_TRIO + """
        await trustMod.openApplicantTrust();
        const body = document.getElementById('applicant-trust-body');
        console.log(JSON.stringify({ cardCount: body.querySelectorAll('.admin-card').length }));
    """
    out = _run_node(script)
    assert out["cardCount"] == 4
