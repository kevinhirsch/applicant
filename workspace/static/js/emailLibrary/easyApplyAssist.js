// static/js/emailLibrary/easyApplyAssist.js
//
// P2-14 — Easy Apply: assisted mode.
//
// The user drives the actual application; the product only ASSISTS: a deep
// link to the real posting, the candidate's own already-prepared materials,
// and a plain checklist. Nothing here logs into the job board, fills a field,
// or submits anything — full live-account automation (walking the quick-apply
// modal on a real, owner-controlled account) is explicitly deferred until the
// owner supplies one for proof runs (road-to-market backlog, P2-14). First use
// shows a stop-boundary consent screen saying exactly that; acceptance is
// recorded server-side (GET/POST /api/applicant/easy-apply/consent) and is
// only ever asked once.
//
// Entry point is the digest row's existing "Easy Apply" chip (P1-11) — see
// `buildDigestRow` in ./applicantDigest.js, which renders the "Assisted apply"
// button that calls `showEasyApplyAssist` below. No new nav door.

import { showToast } from '../ui.js';

const API_BASE = window.location.origin;

// Staleness guard: each showEasyApplyAssist call (and each consent-screen
// accept click — a fresh user intent) claims a new token; every await checks
// it afterwards and bails when superseded, so posting A's slow consent/brief
// response can never clobber the modal the user just opened for posting B.
let _activeRequestId = 0;

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _close() {
  const existing = document.getElementById('applicant-easy-apply-overlay');
  if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
  document.removeEventListener('keydown', _onKey);
}

function _onKey(e) {
  if (e.key === 'Escape') { e.preventDefault(); _close(); }
}

async function _fetchJSON(url, opts = {}) {
  const r = await fetch(url, { credentials: 'same-origin', ...opts });
  let payload = null;
  try { payload = await r.json(); } catch (_) { payload = null; }
  if (!r.ok) {
    const detail = (payload && (payload.detail || payload.message)) || `Request failed (${r.status})`;
    const err = new Error(typeof detail === 'string' ? detail : 'Request failed');
    err.status = r.status;
    throw err;
  }
  return payload || {};
}

function _overlay(bodyHTML, { title = 'Easy Apply', wide = false } = {}) {
  _close();
  const overlay = document.createElement('div');
  overlay.id = 'applicant-easy-apply-overlay';
  overlay.className = 'modal';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');
  overlay.setAttribute('aria-label', title);
  // Explicit overlay positioning (mirrors digestEmailPreview.js) so it shows
  // regardless of the app's modal show/hide class state.
  overlay.style.cssText =
    'display:flex;align-items:center;justify-content:center;position:fixed;'
    + 'inset:0;z-index:100000;background:rgba(0,0,0,0.55);';
  overlay.innerHTML = `
    <div class="modal-content" style="max-width:${wide ? 560 : 460}px;width:92%;display:flex;flex-direction:column;max-height:84vh;">
      <div class="modal-header" style="display:flex;align-items:center;">
        <h4 style="margin:0;">${_esc(title)}</h4>
        <button type="button" class="memory-toolbar-btn" id="applicant-easy-apply-close" style="margin-left:auto;">Close</button>
      </div>
      <div class="modal-body" style="display:flex;flex-direction:column;gap:10px;overflow:auto;padding:4px 2px;">
        ${bodyHTML}
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const closeBtn = overlay.querySelector('#applicant-easy-apply-close');
  closeBtn.addEventListener('click', _close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) _close(); });
  document.addEventListener('keydown', _onKey);
  closeBtn.focus();
  return overlay;
}

// Reuses the existing Documents library launcher rather than building a
// second materials picker (CLAUDE.md principle #1 — lift and shift).
function _openDocuments() {
  _close();
  const opener = document.getElementById('tool-library-btn') || document.getElementById('rail-archive');
  if (opener) opener.click();
  else showToast('Open Documents from the sidebar to grab your resume and cover letter.');
}

// The stop-boundary consent screen (safety surface, not decoration): plain
// language, what the product WILL and will NEVER do, shown before the very
// first assisted-mode use. Acceptance is recorded server-side on "continue".
function _showConsentScreen(onAccept) {
  const body = `
    <p class="memory-desc" style="font-size:12.5px;line-height:1.5;">
      Easy Apply <strong>assists</strong> — it never applies for you. When you use it,
      Applicant will:
    </p>
    <ul style="font-size:12.5px;line-height:1.6;margin:0 0 6px 18px;padding:0;">
      <li>Open the real posting for you to review.</li>
      <li>Hand you your already-prepared resume and cover letter.</li>
      <li>Walk you through a short checklist.</li>
    </ul>
    <p class="memory-desc" style="font-size:12.5px;line-height:1.5;">
      It will <strong>never</strong> log into the job board on your behalf, fill in a field,
      or submit an application for you — and it never answers EEO or work-authorization
      questions; those are always yours to answer. Fully automated Easy Apply isn't available
      yet in this build.
    </p>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:4px;">
      <button type="button" class="memory-toolbar-btn" id="applicant-easy-apply-decline">Not now</button>
      <button type="button" class="memory-toolbar-btn" id="applicant-easy-apply-accept">I understand — continue</button>
    </div>`;
  const overlay = _overlay(body, { title: 'Before you use Easy Apply' });
  overlay.querySelector('#applicant-easy-apply-decline').addEventListener('click', _close);
  const acceptBtn = overlay.querySelector('#applicant-easy-apply-accept');
  acceptBtn.addEventListener('click', async () => {
    acceptBtn.disabled = true;
    try {
      await _fetchJSON(`${API_BASE}/api/applicant/easy-apply/consent`, { method: 'POST' });
      await onAccept();
    } catch (e) {
      showToast(e.message || "Couldn't save that — try again in a moment.");
      acceptBtn.disabled = false;
    }
  });
}

// The assisted-mode brief itself: deep link + checklist + a hand-off to the
// candidate's own prepared materials. Render-only — every action here opens
// something ELSEWHERE (a new tab, the Documents library); nothing submits.
function _showBrief(brief) {
  const title = brief.title || 'this role';
  const company = brief.company ? ` at ${brief.company}` : '';
  const checklist = Array.isArray(brief.checklist) ? brief.checklist : [];
  const items = checklist.map((step) => `<li style="margin-bottom:4px;">${_esc(step)}</li>`).join('');
  const link = brief.deep_link;
  // Never render a clickable link for a non-web URL (defense in depth, mirrors
  // buildDigestRow's own `_isWebUrl` guard on the "Open" action).
  const isWebUrl = typeof link === 'string' && /^https?:\/\//i.test(link);
  const openLink = isWebUrl
    ? `<a class="memory-toolbar-btn" href="${_esc(link)}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;">Open the posting</a>`
    : '';
  const body = `
    <p class="memory-desc" style="font-size:12.5px;">
      ${_esc(title)}${_esc(company)} — you're driving; here's everything to hand.
    </p>
    <ol style="font-size:12.5px;line-height:1.6;margin:0 0 4px 18px;padding:0;">${items}</ol>
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:2px;">
      ${openLink}
      <button type="button" class="memory-toolbar-btn" id="applicant-easy-apply-open-docs">Open my Documents</button>
    </div>`;
  const overlay = _overlay(body, { title: 'Easy Apply — assisted' });
  const docsBtn = overlay.querySelector('#applicant-easy-apply-open-docs');
  if (docsBtn) docsBtn.addEventListener('click', _openDocuments);
}

async function _loadAndShowBrief(campaignId, postingId, requestId) {
  try {
    const brief = await _fetchJSON(
      `${API_BASE}/api/applicant/easy-apply/${encodeURIComponent(campaignId)}/${encodeURIComponent(postingId)}`,
    );
    if (requestId !== _activeRequestId) return; // superseded — a newer flow owns the modal now
    _showBrief(brief);
  } catch (e) {
    if (requestId !== _activeRequestId) return;
    showToast(e.message || "Couldn't load that role's assisted-apply brief right now.");
  }
}

// Entry point (called from buildDigestRow's "Assisted apply" button): show the
// consent screen once, then the assisted-mode brief for this posting. Safe to
// call any number of times — the consent screen is skipped once the engine has
// recorded acceptance (a real, server-side record, never a client-side flag).
export async function showEasyApplyAssist(campaignId, row) {
  const postingId = row && row.posting_id;
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  if (!postingId) { showToast("This role doesn't have assisted-apply details yet."); return; }
  const requestId = ++_activeRequestId;
  let consent;
  try {
    consent = await _fetchJSON(`${API_BASE}/api/applicant/easy-apply/consent`);
  } catch (e) {
    if (requestId !== _activeRequestId) return; // superseded mid-flight
    showToast(e.message || "Couldn't check assisted-apply settings right now.");
    return;
  }
  if (requestId !== _activeRequestId) return; // superseded mid-flight
  if (consent && consent.given) {
    await _loadAndShowBrief(campaignId, postingId, requestId);
  } else {
    // The accept click is a fresh user intent, so it claims its own token —
    // it must never be suppressed by a flow that started before it.
    _showConsentScreen(() => _loadAndShowBrief(campaignId, postingId, ++_activeRequestId));
  }
}

export default { showEasyApplyAssist };
