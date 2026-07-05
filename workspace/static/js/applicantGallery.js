// static/js/applicantGallery.js
//
// Gallery (#296) — the per-campaign screenshots + generated materials the
// Applicant engine captured, surfaced as a browsable collection/grid. ADDITIVE
// and self-contained: it opens its own modal, talks to the engine through the
// /api/applicant/gallery/* workspace proxy, and never touches the workspace's own
// native image gallery (that lives under #tool-gallery-btn / gallery.js).
//
// What it shows (read-only, plain-language, white-labeled):
//   • Screenshots — the per-page captures archived during pre-fill, each with its
//     page reference + (when present) the live page URL.
//   • Materials   — the generated drafts (resume / cover letter / screening
//     answer) with their kind, approval state, stored-file path and a content
//     snippet.
//
// Activation: the launcher (tool-applicant-gallery-btn / rail-applicant-gallery)
// is greyed + click-guarded by the feature-activation layer in app.js until the
// engine reports the `gallery` section configured. We still render a graceful
// offline/empty state if opened while the engine is unreachable.

import uiModule from './ui.js';
import { esc, _fetchJSON, errText, loadingHTML, emptyHTML, errorHTML, wireRetry } from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const GALLERY = '/api/applicant/gallery';

let _modalEl = null;
let _modalA11yCleanup = null;
let _campaignId = null;
let _renderSeq = 0;

// Shared with emailLibrary/applicantDigest.js's own last-campaign memory
// (exhaustive2 lens 01 micro-interactions #58) — Gallery deliberately reads
// AND writes the very same localStorage key rather than keeping its own
// campaign choice only for the page session, so picking a job search in
// either surface is remembered across a refresh in both.
const LAST_CAMPAIGN_KEY = 'applicant-digest-last-campaign';

// ── Modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-gallery-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Application Gallery — screenshots and generated materials');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:820px;display:flex;flex-direction:column;max-height:88vh;">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
          Application Gallery
        </h4>
        <button class="modal-close" id="applicant-gallery-close" title="Close" aria-label="Close">×</button>
      </div>
      <p style="padding:10px 14px 0;margin:0;opacity:0.75;font-size:12px;">
        A browsable record of what I capture while working your applications — the pages I saw,
        and the resumes, cover letters, and answers I drafted, organized by job search below.
      </p>
      <div style="padding:8px 14px 0;display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
        <label class="admin-toggle-sub" style="margin:0;display:flex;gap:6px;align-items:center;">
          Job search
          <select id="applicant-gallery-campaign" class="settings-select" style="min-width:180px;"></select>
        </label>
        <span id="applicant-gallery-engine" class="admin-toggle-sub" style="margin:0;opacity:0.6;"></span>
      </div>
      <div class="modal-body" id="applicant-gallery-body" style="flex:1;overflow-y:auto;padding:14px;" aria-live="polite" aria-busy="false">
        ${loadingHTML('Loading…')}
      </div>
    </div>`;
  document.body.appendChild(modal);
  // initModalA11y (focus trap + Escape arbiter + focus restore) is (re-)wired
  // from openApplicantGallery() on every open, not here — this element is
  // created once and reused across opens, so wiring it only at creation time
  // would leave every reopen after the first with no focus management at all
  // (a11y-deep audit item #1's "six modals lose focus mgmt after first
  // close" class of bug — Portal/Vault/Mind/Remote already re-init on every
  // open; Gallery was one of the six named).
  modal.querySelector('#applicant-gallery-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  modal.querySelector('#applicant-gallery-campaign').addEventListener('change', (e) => {
    _campaignId = e.target.value || null;
    try { localStorage.setItem(LAST_CAMPAIGN_KEY, _campaignId || ''); } catch { /* best-effort */ }
    _renderGallery();
  });
  // Delegated on the body (not the tiles) so it keeps working across every
  // _renderGallery() innerHTML swap of the body's children (micro-
  // interactions audit #64: material snippets hard-cut at 240 chars with no
  // ellipsis and no way to read the rest).
  modal.querySelector('#applicant-gallery-body').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-role="snippet-toggle"]');
    if (!btn) return;
    const tile = btn.closest('.applicant-gallery-tile');
    const snippet = tile && tile.querySelector('.applicant-gallery-snippet');
    if (!snippet) return;
    const expanded = snippet.getAttribute('data-expanded') === '1';
    if (expanded) {
      snippet.textContent = snippet.getAttribute('data-short') || '';
      snippet.style.maxHeight = '4.2em';
      snippet.setAttribute('data-expanded', '0');
      btn.textContent = 'Show more';
    } else {
      snippet.textContent = snippet.getAttribute('data-full') || '';
      snippet.style.maxHeight = 'none';
      snippet.setAttribute('data-expanded', '1');
      btn.textContent = 'Show less';
    }
  });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) {
    _modalEl.classList.add('hidden');
    _modalEl.style.display = 'none';
  }
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('gallery');
}

// Exported so other modules/tests can close Gallery without reaching into
// its private state, mirroring openApplicantGallery's public export.
export function closeApplicantGallery() {
  _close();
}

function _body() { return _modalEl.querySelector('#applicant-gallery-body'); }

function _empty(msg) {
  return `<div class="admin-card" style="opacity:0.85;">${esc(msg || 'Nothing here yet.')}</div>`;
}

// A "create a job search" button that routes forward out of a dead-end empty
// state. Prefers the onboarding/setup opener; falls back to the assistant so the
// user always has a real next step rather than a disabled picker.
function _createSearchCTA() {
  return `<button class="cal-btn cal-btn-primary" id="applicant-gallery-cta">Create a job search</button>`;
}

function _wireCreateSearchCTA() {
  const btn = _body() && _body().querySelector('#applicant-gallery-cta');
  if (!btn) return;
  btn.addEventListener('click', () => {
    try {
      if (typeof window.launchApplicantSetup === 'function') { window.launchApplicantSetup(); _close(); return; }
      if (window.applicantChatModule && window.applicantChatModule.openApplicantChat) {
        window.applicantChatModule.openApplicantChat(); _close(); return;
      }
    } catch { /* fall through to no-op */ }
  });
}

// Map a kit error (with .kind) to a plain-language line for the retry card.
function _errLine(err) {
  if (err && err.kind === 'gated') {
    return 'Finish setup (connect a model and your profile) to enable this view.';
  }
  if (err && (err.kind === 'offline' || err.kind === 'network')) {
    return "I can’t connect right now — this gallery will fill in once I’m back.";
  }
  return errText(err);
}

// ── Campaign chooser ────────────────────────────────────────────────────────

async function _loadCampaigns() {
  let data;
  try {
    data = await _fetchJSON(`${GALLERY}/campaigns`);
  } catch {
    data = { engine_available: false, campaigns: [] };
  }
  const sel = _modalEl.querySelector('#applicant-gallery-campaign');
  const campaigns = Array.isArray(data && data.campaigns) ? data.campaigns : [];
  sel.innerHTML = campaigns.length
    ? campaigns.map((c) => `<option value="${esc(c.id)}">${esc(c.name || c.id)}</option>`).join('')
    : '<option value="">No job searches yet</option>';
  if (!_campaignId && campaigns.length) {
    // Prefer the last campaign remembered by this shared key (micro-
    // interactions #58) over always defaulting back to the first one, so a
    // page refresh doesn't quietly switch a user back to a different search.
    let remembered = '';
    try { remembered = localStorage.getItem(LAST_CAMPAIGN_KEY) || ''; } catch { /* best-effort */ }
    _campaignId = (remembered && campaigns.some((c) => c.id === remembered))
      ? remembered
      : campaigns[0].id;
  }
  if (_campaignId) sel.value = _campaignId;
  return data && data.engine_available !== false;
}

// ── Collection rendering ────────────────────────────────────────────────────

function _shotCard(s) {
  const ref = esc(s.page_ref || 'screenshot');
  const url = s.page_url
    ? `<a class="grow" href="${esc(s.page_url)}" target="_blank" rel="noopener" title="${esc(s.page_url)}" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${esc(s.page_url)}</a>`
    : '<span class="admin-toggle-sub" style="opacity:0.6;">No page URL</span>';
  return `
    <div class="applicant-gallery-tile" style="display:flex;flex-direction:column;gap:6px;">
      <div style="display:flex;align-items:center;gap:8px;color:var(--text-muted,#888);">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
        <strong style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${ref}</strong>
      </div>
      <div style="display:flex;align-items:center;gap:6px;">${url}</div>
    </div>`;
}

const _MAT_LABEL = {
  resume: 'Resume',
  cover_letter: 'Cover letter',
  screening_answer: 'Screening answer',
};

function _matCard(m) {
  const label = esc(_MAT_LABEL[m.type] || m.type || 'Material');
  const badge = m.approved
    ? '<span class="admin-toggle-sub" style="color:var(--success,#3a3);">Approved</span>'
    : '<span class="admin-toggle-sub" style="opacity:0.6;">In review</span>';
  const path = m.storage_path
    ? `<div class="admin-toggle-sub" style="opacity:0.6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(m.storage_path)}">${esc(m.storage_path)}</div>`
    : '';
  // Micro-interactions audit #64: the 240-char cut used to hard-truncate
  // mid-word with no "…" and no way to read the rest. Now it truncates on a
  // word boundary, adds an ellipsis, and (when truncated) a real
  // keyboard-operable "Show more"/"Show less" toggle wired via the
  // delegated body listener in _ensureModalEl — the material is no longer
  // otherwise unviewable from the Gallery.
  let snippet = '';
  if (m.content) {
    const full = String(m.content);
    const truncated = full.length > 240;
    const cut = full.slice(0, 240);
    const short = truncated ? `${cut.slice(0, Math.max(1, cut.lastIndexOf(' ')) )}…` : full;
    snippet = `<div class="applicant-gallery-snippet" data-full="${esc(full)}" data-short="${esc(short)}" data-expanded="0" `
      + `style="font-size:12px;line-height:1.4;${truncated ? 'max-height:4.2em;overflow:hidden;' : ''}">${esc(short)}</div>`
      + (truncated
        ? '<button type="button" class="cal-btn" data-role="snippet-toggle" style="margin-top:4px;font-size:11px;padding:2px 8px;">Show more</button>'
        : '');
  }
  return `
    <div class="applicant-gallery-tile" style="display:flex;flex-direction:column;gap:6px;">
      <div style="display:flex;align-items:center;gap:8px;">
        <strong class="grow">${label}</strong>${badge}
      </div>
      ${path}
      ${snippet}
    </div>`;
}

function _grid(cards) {
  return `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;">${cards.join('')}</div>`;
}

async function _renderGallery() {
  // Stale-render guard (micro-interactions audit #44: "Campaign-switch races
  // — only Chat has a stale-render guard"): capture this call's own sequence
  // number and bail before every DOM write once a later call has started, so
  // scrubbing the campaign picker quickly can never paint an earlier fetch's
  // response over a newer selection.
  const seq = (_renderSeq += 1);
  const host = _body();
  const stale = () => seq !== _renderSeq || !_modalEl;
  if (!_campaignId) {
    host.innerHTML = emptyHTML(
      'No job searches yet',
      'Create a job search to start capturing screenshots and materials here.',
      _createSearchCTA());
    _wireCreateSearchCTA();
    return;
  }
  host.setAttribute('aria-busy', 'true');
  host.innerHTML = loadingHTML('Loading…');
  let data;
  try {
    data = await _fetchJSON(`${GALLERY}/${encodeURIComponent(_campaignId)}`);
  } catch (err) {
    if (stale()) return;
    _body().setAttribute('aria-busy', 'false');
    _body().innerHTML = errorHTML(_errLine(err));
    wireRetry(_body(), _renderGallery);
    return;
  }
  if (stale()) return;
  const shots = (data && data.screenshots && Array.isArray(data.screenshots.items)) ? data.screenshots.items : [];
  const mats = (data && data.materials && Array.isArray(data.materials.items)) ? data.materials.items : [];

  if (!shots.length && !mats.length) {
    _body().setAttribute('aria-busy', 'false');
    _body().innerHTML = emptyHTML(
      'Nothing captured yet',
      'This job search has no screenshots or generated materials yet — they appear here as I work.',
      _createSearchCTA());
    _wireCreateSearchCTA();
    return;
  }

  const sections = [];
  sections.push(`<h5 style="margin:0 0 8px;">Screenshots <span class="admin-toggle-sub" style="opacity:0.6;">${shots.length}</span></h5>`);
  sections.push(shots.length ? _grid(shots.map(_shotCard)) : _empty(
    'No screenshots yet — these are captured automatically as I work through each page.'));
  sections.push(`<h5 style="margin:16px 0 8px;">Materials <span class="admin-toggle-sub" style="opacity:0.6;">${mats.length}</span></h5>`);
  sections.push(mats.length ? _grid(mats.map(_matCard)) : _empty(
    'No generated materials yet — resumes, cover letters, and screening answers will appear here as I draft them.'));
  _body().setAttribute('aria-busy', 'false');
  _body().innerHTML = sections.join('');
}

// ── Open + launcher ─────────────────────────────────────────────────────────

export async function openApplicantGallery(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('gallery');
  // Keyboard a11y: trap focus, Escape to close, restore on close — re-wired
  // on every open (not just the first), the fix for a11y-deep audit #1.
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  _body().innerHTML = loadingHTML('Loading…');
  try {
    const up = await _loadCampaigns();
    const badge = modal.querySelector('#applicant-gallery-engine');
    if (badge) badge.textContent = up ? '' : 'Not connected';
    await _renderGallery();
  } catch (err) {
    _body().innerHTML = errorHTML(_errLine(err));
    wireRetry(_body(), openApplicantGallery);
  }
}

function _wireLauncher() {
  ['tool-applicant-gallery-btn', 'rail-applicant-gallery'].forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn || btn._applicantGalleryWired) return;
    btn._applicantGalleryWired = true;
    btn.addEventListener('click', () => {
      // Respect the feature-activation lock — if app.js greyed the launcher, its
      // capture-phase guard already stopped this handler; reaching here = active.
      openApplicantGallery();
    });
  });
}

function _boot() {
  _wireLauncher();
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('tool-applicant-gallery-btn')?._applicantGalleryWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#gallery' deep-links straight into the Gallery
// page — a refresh/shared-link/back-forward on that hash opens/closes it.
// Registered at module-eval time (runs as soon as app.js's dynamic import
// resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('gallery', { open: openApplicantGallery, close: _close });

const applicantGalleryModule = { openApplicantGallery, closeApplicantGallery };
window.applicantGalleryModule = applicantGalleryModule;
export default applicantGalleryModule;
