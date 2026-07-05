/**
 * applicantCompare.js — the Compare surface (#184/#486), engine-backed (#297).
 *
 * Opens a modal where the user picks an entity kind (applications or postings)
 * and an optional campaign scope, supplies two or more entity ids, and gets back
 * the engine's cross-entity diff table (one row per dimension, the differing
 * cells flagged) rendered as a side-by-side grid.
 *
 * Reachability chain:
 *   nav (#tool-compare-btn / #rail-compare)
 *     → openApplicantCompare()
 *     → /api/applicant/compare/{applications,postings}  (workspace proxy)
 *     → engine /api/compare/{applications,postings}      (CompareService)
 *
 * Lift-and-shift: the modal shell, self-boot + launcher-wiring, and the soft
 * degradation pattern are the ones applicantActivity.js already uses; the atomic
 * controls are the vendored AppKit Elements kit (.ow-btn / .ow-select / .ow-field,
 * S17/#486) composed on real rendered markup. UI styling otherwise reuses the
 * workspace design system (.modal / .cal-btn).
 *
 * This is the Applicant Compare surface — NOT the vendored model arena
 * (static/js/compare/index.js, /api/compare). Different prefix, different nav.
 */

import uiModule from './ui.js';
import { _fetchJSON as _kitFetchJSON, errText, loadingHTML, emptyHTML, errorHTML, wireRetry } from './applicantCore.js';
import { registerRoute, setHash, clearHash } from './hashRouter.js';

const API = `${window.location.origin}/api/applicant/compare`;

let _modalEl = null;
let _modalA11yCleanup = null;
// The in-flight compare request's abort controller + a flag so the catch handler
// can tell a user-triggered Cancel apart from a real network/engine error.
let _compareController = null;
let _compareCancelled = false;

function _esc(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

// Prefix the compare API onto the kit fetch so callers keep passing bare paths;
// the kit gives us .kind-tagged errors + errText() for the retry/error states.
function _fetchJSON(path, opts) {
  return _kitFetchJSON(`${API}${path}`, opts);
}

// Map a kit error (with .kind) to a plain-language line for the retry card.
function _errLine(err) {
  if (err && err.kind === 'gated') {
    return 'Finish setup (connect a model and your profile) to enable comparisons.';
  }
  if (err && (err.kind === 'offline' || err.kind === 'network')) {
    return 'The Applicant engine is not reachable right now. Try again once it is connected.';
  }
  return errText(err);
}

// Copy a value to the clipboard, reusing the workspace copy helper when present.
function _copy(text) {
  try {
    if (uiModule && typeof uiModule.copyToClipboard === 'function') { uiModule.copyToClipboard(text); return; }
  } catch { /* fall through */ }
  try { navigator.clipboard.writeText(text); } catch { /* no-op */ }
}

// ── Modal shell ─────────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-compare-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Compare');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:720px;display:flex;flex-direction:column;max-height:88vh;background:var(--bg);">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/></svg>
          Compare
        </h4>
        <button class="close-btn" id="applicant-compare-close" title="Close" aria-label="Close">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
        </button>
      </div>
      <div class="modal-body" style="flex:1;overflow-y:auto;">
        <p style="opacity:0.75;font-size:12px;margin:0 0 12px;">
          Put two or more applications or postings side-by-side to see exactly where they differ.
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:14px;">
          <label class="ow-field" style="min-width:160px;">
            <span>What to compare</span>
            <select id="applicant-compare-kind" class="ow-select"
              title="Applications: your own submissions, with status and materials. Postings: just the job listings, before you've applied.">
              <option value="applications">Applications</option>
              <option value="postings">Postings</option>
            </select>
          </label>
          <label class="ow-field" style="min-width:200px;flex:1;">
            <span>Campaign (optional scope)</span>
            <select id="applicant-compare-campaign" class="ow-select">
              <option value="">All campaigns</option>
            </select>
          </label>
        </div>
        <label class="ow-field" style="display:block;margin-bottom:14px;">
          <span>Ids to compare</span>
          <textarea id="applicant-compare-ids" rows="3" placeholder="One id per line, or comma-separated — at least two"
            style="width:100%;box-sizing:border-box;resize:vertical;"></textarea>
          <span class="ow-field-hint">The engine needs two or more ids from the same campaign.</span>
        </label>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:14px;">
          <button class="ow-btn ow-btn-prominent" id="applicant-compare-run">Compare</button>
          <span id="applicant-compare-status" style="font-size:12px;opacity:0.8;"></span>
        </div>
        <div id="applicant-compare-result"></div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  // Tab-trap + Escape-to-close + focus-restore, and (design-audit item #17)
  // topmost-only Escape arbitration against any other open modal/dialog —
  // reuse ui.js's initModalA11y rather than a bespoke local Escape listener.
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-compare-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  modal.querySelector('#applicant-compare-run').addEventListener('click', _runCompare);
  _modalEl = modal;
  return modal;
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = '';
  // Hash routing (audit #7): only clears when the hash is actually ours.
  clearHash('compare');
}

// Exported so other modules/tests can close Compare without reaching into
// its private state, mirroring openApplicantCompare's public export.
export function closeApplicantCompare() {
  _close();
}

function _setStatus(msg, isError) {
  const el = _modalEl && _modalEl.querySelector('#applicant-compare-status');
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = isError ? 'var(--color-error, #e06c75)' : '';
}

// ── Campaign picker ──────────────────────────────────────────────────────────

async function _loadCampaigns() {
  const sel = _modalEl && _modalEl.querySelector('#applicant-compare-campaign');
  if (!sel) return;
  try {
    const data = await _fetchJSON('/campaigns');
    const campaigns = (data && data.campaigns) || [];
    // Keep the "All campaigns" default; clear any previously-appended options
    // first so reopening the modal doesn't duplicate every campaign name.
    sel.querySelectorAll('option[value]:not([value=""])').forEach((opt) => opt.remove());
    for (const c of campaigns) {
      const id = c && (c.id != null ? c.id : c.campaign_id);
      if (id == null) continue;
      const opt = document.createElement('option');
      opt.value = String(id);
      opt.textContent = (c && (c.name || c.title)) || String(id);
      sel.appendChild(opt);
    }
  } catch (_) {
    // Soft-degrade: the picker just stays "All campaigns" when the engine is
    // unreachable. The compare action itself surfaces the real error.
  }
}

// ── Run + render ─────────────────────────────────────────────────────────────

function _parseIds(raw) {
  return String(raw || '')
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

// Loading state + an inline Cancel — the compare request is a plain POST, so a
// user-triggered abort is safe/interruptible (unlike e.g. the Update trigger).
function _loadingWithCancel(label) {
  return `<div style="display:flex;align-items:center;gap:10px;">${loadingHTML(label)}`
    + `<button type="button" class="cal-btn" id="applicant-compare-cancel">Cancel</button></div>`;
}

async function _runCompare() {
  const kind = _modalEl.querySelector('#applicant-compare-kind').value;
  const campaignId = _modalEl.querySelector('#applicant-compare-campaign').value || null;
  const ids = _parseIds(_modalEl.querySelector('#applicant-compare-ids').value);
  const result = _modalEl.querySelector('#applicant-compare-result');
  const runBtn = _modalEl.querySelector('#applicant-compare-run');

  if (ids.length < 2) {
    _setStatus('Enter at least two ids to compare.', true);
    return;
  }
  _setStatus('', false);
  _compareCancelled = false;
  if (_compareController) { try { _compareController.abort(); } catch { /* already settled */ } }
  const controller = new AbortController();
  _compareController = controller;
  result.innerHTML = _loadingWithCancel('Comparing…');
  const cancelBtn = result.querySelector('#applicant-compare-cancel');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      _compareCancelled = true;
      try { controller.abort(); } catch { /* no-op */ }
    });
  }
  runBtn.disabled = true;
  try {
    const path = kind === 'postings' ? '/postings' : '/applications';
    const data = await _fetchJSON(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, campaign_id: campaignId }),
      signal: controller.signal,
    });
    _setStatus('', false);
    _renderResult(result, data, kind, campaignId);
  } catch (e) {
    _setStatus('', false);
    if (_compareCancelled) {
      result.innerHTML = '<div style="opacity:0.7;padding:8px 0;">Comparison cancelled.</div>';
    } else {
      // Inline error + Retry so the user recovers without re-typing their ids.
      result.innerHTML = errorHTML(_errLine(e));
      wireRetry(result, _runCompare);
    }
  } finally {
    runBtn.disabled = false;
    if (_compareController === controller) _compareController = null;
  }
}

// True when the values for a dimension actually differ across entities (or the
// engine already flagged it via `dim.diff`) — used to flag the row, in-content,
// with neutral ink weight/bg rather than the previous opacity-only "—" signal.
function _dimDiffers(dim, entityIds, values) {
  if (dim && dim.diff) return true;
  const seen = new Set();
  for (const id of entityIds) {
    seen.add(values[id] != null ? String(values[id]) : '');
  }
  return seen.size > 1;
}

function _renderResult(container, data, kind, campaignId) {
  container.innerHTML = '';
  if (!data) {
    container.innerHTML = emptyHTML(
      'No comparison came back',
      'The engine did not return a result for that comparison. Try again, or adjust the ids and re-run.',
      '');
    return;
  }
  const entityIds = Array.isArray(data.entity_ids) ? data.entity_ids : [];
  const labels = data.entity_labels || {};
  const dimensions = Array.isArray(data.dimensions) ? data.dimensions : [];

  if (data.summary) {
    const sum = document.createElement('p');
    sum.style.cssText = 'font-size:12px;opacity:0.85;margin:0 0 10px;';
    sum.textContent = data.summary;
    container.appendChild(sum);
  }

  if (entityIds.length < 2 || dimensions.length === 0) {
    // Engine's degraded-but-valid case (e.g. "Need at least 2 …"): the summary
    // above already explains it; nothing more to table.
    return;
  }

  // The diff sits inside a bounded content-material panel instead of directly on
  // the modal glass — a hairline-divided table, not per-cell inline borders.
  const panel = document.createElement('div');
  panel.className = 'applicant-compare-result-panel';

  const table = document.createElement('table');
  table.className = 'applicant-compare-table';

  const thead = document.createElement('thead');
  // Applications can be opened in the Debug/Activity detail view; postings have
  // no reachable detail surface within this module, so their labels stay plain.
  const canLink = kind === 'applications';
  let headRow = '<tr><th>Dimension</th>';
  for (const id of entityIds) {
    // Click-to-copy the raw id so it can be re-pasted into another compare /
    // surface without hand-typing. The label stays visible; the id is the payload.
    headRow += `<th>
      <button type="button" class="applicant-compare-copy-id" data-id="${_esc(id)}" title="Copy id — ${_esc(id)}">${_esc(labels[id] || id)}</button>
      ${canLink ? `<button type="button" class="applicant-compare-open-detail" data-id="${_esc(id)}" title="Open this application in Activity">Open in Activity →</button>` : ''}
    </th>`;
  }
  headRow += '<th title="A short note from the engine on what actually differs for this row">Difference</th></tr>';
  thead.innerHTML = headRow;
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const dim of dimensions) {
    const values = (dim && dim.values) || {};
    const differs = _dimDiffers(dim, entityIds, values);
    let row = `<tr class="${differs ? 'applicant-compare-row-diff' : ''}"><td>${_esc(dim.label || dim.key)}</td>`;
    for (const id of entityIds) {
      row += `<td>${_esc(values[id] != null ? values[id] : '—')}</td>`;
    }
    row += `<td class="applicant-compare-diff-cell">${_esc(dim.diff || '')}</td></tr>`;
    tbody.insertAdjacentHTML('beforeend', row);
  }
  table.appendChild(tbody);
  panel.appendChild(table);
  container.appendChild(panel);
  container.querySelectorAll('.applicant-compare-copy-id').forEach((b) => {
    b.addEventListener('click', () => _copy(b.dataset.id || ''));
  });
  container.querySelectorAll('.applicant-compare-open-detail').forEach((b) => {
    b.addEventListener('click', () => {
      const id = b.dataset.id;
      try {
        if (window.applicantDebugModule && typeof window.applicantDebugModule.openApplicantDebugDetail === 'function') {
          _close();
          window.applicantDebugModule.openApplicantDebugDetail(campaignId, id);
        } else {
          _copy(id || '');
        }
      } catch { /* no-op — the copy-id button beside it still works */ }
    });
  });
}

// ── Open / launchers / boot ──────────────────────────────────────────────────

export async function openApplicantCompare(opts) {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  if (!(opts && opts.skipHashUpdate)) setHash('compare');
  _setStatus('', false);
  // Seed the (otherwise blank) result area with a plain-language empty state so
  // the surface reads as ready, not broken, before the first comparison.
  const result = modal.querySelector('#applicant-compare-result');
  if (result && !result.innerHTML.trim()) {
    result.innerHTML = emptyHTML(
      'Nothing to compare yet',
      'Pick applications or postings above, paste two or more ids, then Compare to see where they differ.',
      '');
  }
  await _loadCampaigns();
}

function _wireLaunchers() {
  for (const id of ['tool-compare-btn', 'rail-compare']) {
    const el = document.getElementById(id);
    if (el && !el._applicantCompareWired) {
      el._applicantCompareWired = true;
      el.addEventListener('click', () => openApplicantCompare());
    }
  }
}

function _boot() {
  _wireLaunchers();
  // The rail/tool entries may be (re)rendered after boot (feature-activation
  // toggles their visibility), so retry briefly without a hard load-order dep.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLaunchers();
    const toolWired = document.getElementById('tool-compare-btn')?._applicantCompareWired;
    const railWired = document.getElementById('rail-compare')?._applicantCompareWired;
    if ((toolWired && railWired) || tries > 20) clearInterval(iv);
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#compare' deep-links straight into the Compare
// page — a refresh/shared-link/back-forward on that hash opens/closes it.
// Registered at module-eval time (runs as soon as app.js's dynamic import
// resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('compare', { open: openApplicantCompare, close: _close });

const applicantCompareModule = { openApplicantCompare, closeApplicantCompare };

// Expose for deep-links / other modules without import coupling.
try { window.applicantCompareModule = applicantCompareModule; } catch { /* no-op */ }

export default applicantCompareModule;
