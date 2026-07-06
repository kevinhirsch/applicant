// static/js/applicantTrust.js
//
// Trust Center — "How Applicant protects you". A single, calm, plain-language
// read that consolidates the safety facts this product already ships but that
// were previously scattered one-per-surface: the irreversible-action gate on
// applicantRemote.js's final-submit flow, the "what I promise" list from the
// OOBE wizard, the pre-submit snapshot + audit-log export from
// applicantDebug.js, and the owner-scoping/self-hosting story documented in
// this repo's own CLAUDE.md.
//
// This is a NEW, additive surface — not a rehash of any one of those. It is
// content-only: it makes no engine calls and creates no engine state, so it
// renders instantly and never has a loading/offline/gated state of its own.
// Every claim below is a verified, already-shipped product fact (checked
// against the source it lives in — see the inline references); nothing here
// describes a capability that doesn't exist yet.
//
// Facts consolidated (source of truth for each stays where it lives; this
// page only surfaces + links to it):
//   1. The irreversible-action gate — applicantRemote.js: the assistant can
//      never click a final submit without the owner's explicit action ("I'll
//      submit it myself" or "Authorize the assistant to finish"), the confirm
//      dialog echoes the exact role/company, and the "Submitting in N…
//      Cancel" hold window (`_holdBeforeAuthorize`, Top-25 #12) gives one more
//      undoable pause after confirming and before anything reaches the engine.
//   2. "What I promise" — reused VERBATIM via `neverDoesList`, exported by
//      applicantOnboarding.js. Reframed in the demo-tone pass from a list of
//      negative "never" disclaimers to positive control statements; the OOBE
//      welcome step and Portal empty state now show the shorter `trustLine`
//      one-liner instead, but this fuller Trust Center still reads the item
//      list — not duplicated text, the same import.
//   3. Honesty artifacts — the pre-submit snapshot ("Review exactly what will
//      be sent", applicantRemote.js) and the immutable per-application
//      submission record + full audit-log JSON export, both reachable from
//      Activity & controls (applicantDebug.js: `_renderSnapshot`,
//      `_downloadAuditLog`).
//   4. Data isolation — owner-scoped data (workspace/CLAUDE.md's
//      ownership/multi-user model: the `owner` column + `owner_filter`, with
//      dedicated `*_owner_scope` / `*_isolation` regression tests), a
//      self-hosted deployment (root CLAUDE.md: "self-hosted... AI workspace"),
//      and encrypted vault credentials that are never re-shown or sent back to
//      the browser (applicantVault.js).
//
// Styling reuses the workspace design system (`.ow-window` / `.modal` /
// `.modal-content` / `.modal-header` / `.modal-body` / `.admin-card` /
// `.cal-btn` / `.close-btn`) — no new visual language.

import uiModule from './ui.js';
import { esc } from './applicantCore.js';
import { neverDoesList } from './applicantOnboarding.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

let _modalEl = null;
let _modalA11yCleanup = null;

// ── Modal shell ──────────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-trust-modal';
  // FR-UIKIT-2: compose the vendored Window kit's `ow-window` alongside the
  // legacy `.modal` (mirrors applicantRemote.js) so the responsive kit window
  // applies while the existing `.modal hidden`/`.modal-content` rules,
  // handlers and focus trap keep working unchanged.
  modal.className = 'modal hidden ow-window';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'How Applicant protects you');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:640px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M12 2 4 5v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V5z"/><path d="M9 12l2 2 4-4"/></svg>
          How Applicant protects you
        </h4>
        <button class="close-btn" id="applicant-trust-close" title="Close">✖</button>
      </div>
      <div class="modal-body" id="applicant-trust-body" style="flex:1;overflow-y:auto;">
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  // Escape is handled by initModalA11y (topmost-modal arbiter, design-audit
  // item #17) — do not add a second local Escape listener here.
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-trust-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = 'none';
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('trust');
}

// Exported so other modules/tests can close the Trust Center without reaching
// into its private state, mirroring the rest of the applicant*.js surfaces.
export function closeApplicantTrust() {
  _close();
}

function _body() { return _modalEl && _modalEl.querySelector('#applicant-trust-body'); }

// ── Section renderers ────────────────────────────────────────────────────────

// Demo-tone pass: dropped the shouty ALL-CAPS treatment (text-transform) —
// the safety facts below are a selling point, not a disclaimer, and read
// calmer as normal sentence case.
function _sectionHead(title) {
  return `<div style="font-size:11px;letter-spacing:0.02em;font-weight:600;opacity:0.6;padding:2px 0 8px;">${esc(title)}</div>`;
}

// (1) The irreversible-action gate.
function _gateSectionHTML() {
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('You have the final say on every submission')}
      <p style="font-size:12px;line-height:1.6;margin:0 0 8px;">
        I can search, draft, and fill out an application right up to the final
        submit step — the send is always yours to make. When an application
        is ready, you choose: click submit yourself in the live session, or
        explicitly authorize me to click it for you, just this once. There is
        no path in the product that lets me submit without that explicit
        action from you.
      </p>
      <p style="font-size:12px;line-height:1.6;margin:0 0 8px;">
        If you authorize me, I confirm the exact role and company back to you
        first, and remind you your materials are approved. Then there's one
        more pause: a visible "Submitting in 5…" hold with a Cancel button.
        Nothing reaches the employer until that hold finishes — you can cancel
        it at any moment with zero side effects.
      </p>
      <p style="font-size:11px;line-height:1.5;margin:0;opacity:0.7;">
        I also pause and ask whenever something is uncertain, rather than
        guessing — see "What I promise" below.
      </p>
    </div>`;
}

// (2) "What I promise" — reused verbatim from applicantOnboarding.js.
function _neverDoesSectionHTML() {
  const items = Array.isArray(neverDoesList) ? neverDoesList : [];
  if (!items.length) return '';
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('What I promise')}
      <ul style="margin:0;padding-left:18px;font-size:12px;line-height:1.7;">
        ${items.map((t) => `<li>${esc(t)}</li>`).join('')}
      </ul>
    </div>`;
}

// (3) Honesty artifacts — the pre-submit snapshot + the immutable submission
// record + the audit-log export, all of which already exist; this section
// just explains what they are and links to where they're reachable.
function _honestySectionHTML() {
  const hasDebug = !!(window.applicantActivityModule && typeof window.applicantActivityModule.openApplicantActivity === 'function');
  return `
    <div class="admin-card" style="margin:0 0 12px;padding:12px;">
      ${_sectionHead('Proof, not just promises')}
      <p style="font-size:12px;line-height:1.6;margin:0 0 8px;">
        Before you authorize a submission, "Review exactly what will be sent"
        opens the exact answers, document versions, and posting I'm about to
        submit — never a summary, never fabricated. If nothing's recorded yet,
        it says so plainly instead of guessing.
      </p>
      <p style="font-size:12px;line-height:1.6;margin:0 0 8px;">
        Once an application is submitted, that same record becomes an
        immutable submission record you can reopen any time — go to
        Activity &amp; controls, pick an application, and open
        Details → Submission record.
      </p>
      <p style="font-size:12px;line-height:1.6;margin:0 0 10px;">
        You can also export the complete action trail for a job search as
        JSON, any time, from Activity &amp; controls' overflow menu → Download
        activity log (available to the admin on a shared install).
      </p>
      <button type="button" class="cal-btn" id="applicant-trust-open-debug"
              title="Open Activity & controls">Open Activity &amp; controls</button>
      ${hasDebug ? '' : '<div style="font-size:11px;opacity:0.6;margin-top:6px;">Finish setup to reach Activity &amp; controls.</div>'}
    </div>`;
}

// (4) Data isolation — owner-scoping + self-hosting + vault encryption.
function _isolationSectionHTML() {
  return `
    <div class="admin-card" style="margin:0 0 4px;padding:12px;">
      ${_sectionHead('Your data stays yours')}
      <p style="font-size:12px;line-height:1.6;margin:0 0 8px;">
        Applicant is self-hosted — it runs on infrastructure you (or your
        household/team) control, not a third-party service. Your applications,
        documents, and history are scoped to your account; every data surface
        enforces that scoping on the server, not just in the interface.
      </p>
      <p style="font-size:12px;line-height:1.6;margin:0;">
        Sign-in credentials you save for job sites are encrypted and are
        never shown again or sent back to your browser once saved.
      </p>
    </div>`;
}

function _render(host) {
  if (!host) return;
  host.innerHTML = [
    _gateSectionHTML(),
    _neverDoesSectionHTML(),
    _honestySectionHTML(),
    _isolationSectionHTML(),
  ].filter(Boolean).join('');
  const debugBtn = host.querySelector('#applicant-trust-open-debug');
  if (debugBtn) {
    debugBtn.addEventListener('click', () => {
      try {
        if (window.applicantActivityModule && typeof window.applicantActivityModule.openApplicantActivity === 'function') {
          _close();
          window.applicantActivityModule.openApplicantActivity();
          return;
        }
      } catch { /* fall through */ }
      try { uiModule.showToast('Finish setup to reach Activity & controls'); } catch { /* no-op */ }
    });
  }
}

// ── Open/close ───────────────────────────────────────────────────────────────

export async function openApplicantTrust(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('trust');
  _render(_body());
}

// ── Launcher + boot ──────────────────────────────────────────────────────────

function _wireLaunchers() {
  const btn = document.getElementById('tool-trust-btn');
  if (btn && !btn._applicantTrustWired) {
    btn._applicantTrustWired = true;
    btn.addEventListener('click', () => openApplicantTrust());
  }
}

function _boot() {
  _wireLaunchers();
  // The nav may be (re)rendered after boot; retry briefly so the launcher
  // always gets wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLaunchers();
    if (document.getElementById('tool-trust-btn')?._applicantTrustWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#trust' deep-links straight into the Trust Center
// — a refresh/shared-link/back-forward on that hash opens/closes it.
// Registered at module-eval time (runs as soon as app.js's dynamic import
// resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('trust', { open: openApplicantTrust, close: _close });

const applicantTrustModule = { openApplicantTrust, closeApplicantTrust };

// Expose for deep-links / other modules without import coupling.
try { window.applicantTrustModule = applicantTrustModule; } catch { /* no-op */ }
try { window.openApplicantTrust = openApplicantTrust; } catch { /* no-op */ }

export default applicantTrustModule;
