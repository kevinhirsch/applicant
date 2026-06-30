// static/js/applicantUpdate.js
// FR-UIKIT S11: Operator controls use .odec-* Decision kit for confirmable ops
//
// Update Applicant — a reachable sidebar surface for the one-click updater.
//
// This LIFTS the update logic that used to be buried in the Activity/Debug
// "Update" tab (applicantDebug.js: #applicant-update-go → POST OPS/update/trigger)
// into a first-class rail entry + modal, so updating is operable from the
// white-labeled front-door without opening a debug surface.
//
// ADDITIVE and self-contained: it self-boots (wires the #rail-update launcher on
// DOM ready, exposes window.applicantUpdateModule), opens its own .modal, and
// talks to the engine only through the workspace ops proxy at
// /api/applicant/ops/update (status, GET) and /api/applicant/ops/update/trigger
// (POST). It never reaches the engine directly and degrades gracefully when the
// engine is unreachable or the one-click updater isn't deployed.
//
// Styling reuses the workspace design system (.modal / .modal-content /
// .modal-header / .modal-body / .cal-btn / .cal-btn-primary / .close-btn /
// .admin-card / .admin-toggle-sub / .applicant-update-log).

import uiModule from './ui.js';
import { updateStateView, formatLogTail } from './applicantUpdateView.js';
import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';

const OPS = '/api/applicant/ops';
// While an update is running, re-poll status on this cadence so the live log
// tail and state badge stay fresh until it finishes.
const POLL_MS = 3000;

let _modalEl = null;
let _modalA11yCleanup = null;
let _pollIv = null;





// The pure view helpers (updateStateView / formatLogTail) live in the
// dependency-free leaf module ./applicantUpdateView.js (imported above) so they
// stay unit-testable without dragging in the browser-only module graph. They are
// re-exported from this module's default + named exports below.

// ── Modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-update-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Update applicant');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:560px;display:flex;flex-direction:column;max-height:86vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7"/><polyline points="8 12 12 16 16 12"/><line x1="12" y1="3" x2="12" y2="16"/></svg>
          Update
        </h4>
        <button class="close-btn" id="applicant-update-close" title="Close">✖</button>
      </div>
      <div class="modal-body" id="applicant-update-body" style="flex:1;overflow-y:auto;padding:4px 2px;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.addEventListener('keydown', (e) => { if (e.key === 'Escape') _close(); });
  modal.querySelector('#applicant-update-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
  _stopPolling();
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = 'none';
}

function _body() { return _modalEl && _modalEl.querySelector('#applicant-update-body'); }

function _stopPolling() {
  if (_pollIv) { clearInterval(_pollIv); _pollIv = null; }
}

// ── Render ───────────────────────────────────────────────────────────────────

function _render(status) {
  const host = _body();
  if (!host) return;
  const view = updateStateView(status);
  const log = formatLogTail(status && status.log_tail);
  const showButton = view.kind !== 'offline' && view.kind !== 'no-updater';
  const btnLabel = view.running
    ? 'Updating…'
    : (view.kind === 'failed' ? 'Try again' : 'Update now');

  host.innerHTML = `
    <div class="admin-card">
      <div style="font-weight:600;">${esc(view.headline)}</div>
      <div class="admin-toggle-sub" style="opacity:0.85;margin-top:6px;line-height:1.5;">${esc(view.message)}</div>
      ${showButton
        ? `<button class="cal-btn cal-btn-primary" id="applicant-update-go" style="margin-top:12px;"${view.canTrigger ? '' : ' disabled'}>${esc(btnLabel)}</button>`
        : ''}
      ${log
        ? `<div class="admin-toggle-sub" style="opacity:0.6;margin:12px 0 4px;">Update log</div>
           <pre class="applicant-update-log" id="applicant-update-log">${esc(log)}</pre>`
        : ''}
    </div>`;

  const btn = host.querySelector('#applicant-update-go');
  if (btn && view.canTrigger) {
    btn.addEventListener('click', _trigger);
  }
}

function _renderError() {
  _render({ engine_available: false });
}

// ── Status + trigger flow ─────────────────────────────────────────────────────

async function _refresh() {
  try {
    const status = await _fetchJSON(`${OPS}/update`);
    _render(status);
    return status;
  } catch {
    _renderError();
    return { engine_available: false };
  }
}

// Poll status while running; render each tick (live log tail) and stop on a
// terminal state (success/failed) or when the engine drops out.
function _startPolling() {
  _stopPolling();
  _pollIv = setInterval(async () => {
    let status;
    try {
      status = await _fetchJSON(`${OPS}/update`);
    } catch {
      _stopPolling();
      _renderError();
      return;
    }
    _render(status);
    const state = status && status.state;
    if (state !== 'running') {
      _stopPolling();
      if (state === 'success') _toast('Update complete — Applicant is up to date.');
      else if (state === 'failed') _toast(status.message || "Update didn't finish. You can try again.");
    }
  }, POLL_MS);
}

async function _trigger() {
  const host = _body();
  const btn = host && host.querySelector('#applicant-update-go');
  if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
  try {
    const res = await _post(`${OPS}/update/trigger`, {});
    if (res.engine_available === false) {
      _toast("The app's engine isn't reachable, so the update couldn't start.");
      await _refresh();
      return;
    }
    if (res.started === false) {
      _toast(res.message || 'Nothing to update right now.');
      await _refresh();
      return;
    }
    _toast(res.message || 'Update started.');
    // Re-pull status (now "running") and begin live-polling the log.
    await _refresh();
    _startPolling();
  } catch (e) {
    _toast((e && e.message) || 'Could not start the update right now.');
    await _refresh();
  }
}

// ── Open / launcher ──────────────────────────────────────────────────────────

export async function openApplicantUpdate() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  const host = _body();
  if (host) host.innerHTML = '<div class="hwfit-loading">Loading…</div>';
  const status = await _refresh();
  // If we opened mid-update, resume live-polling the log.
  if (status && status.state === 'running') _startPolling();
}

function _wireLauncher() {
  const btn = document.getElementById('rail-update');
  if (!btn || btn._applicantUpdateWired) return;
  btn._applicantUpdateWired = true;
  btn.addEventListener('click', () => openApplicantUpdate());
}

function _boot() {
  _wireLauncher();
  // The rail may be (re)rendered after boot; retry briefly so the launcher always
  // gets wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('rail-update')?._applicantUpdateWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantUpdateModule = { openApplicantUpdate, updateStateView, formatLogTail };
try { window.applicantUpdateModule = applicantUpdateModule; } catch { /* no-op */ }

// Re-export the pure helpers so importers can pull them from this module too.
export { updateStateView, formatLogTail };

export default applicantUpdateModule;
