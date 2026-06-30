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

const API = `${window.location.origin}/api/applicant/compare`;

let _modalEl = null;

function _esc(text) {
  const div = document.createElement('div');
  div.textContent = text == null ? '' : String(text);
  return div.innerHTML;
}

async function _fetchJSON(path, opts) {
  const res = await fetch(`${API}${path}`, {
    credentials: 'same-origin',
    ...(opts || {}),
  });
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const detail = (data && (data.detail || data.error)) || `HTTP ${res.status}`;
    throw new Error(typeof detail === 'string' ? detail : `HTTP ${res.status}`);
  }
  return data;
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
        <button class="close-btn" id="applicant-compare-close" title="Close">✖</button>
      </div>
      <div class="modal-body" style="flex:1;overflow-y:auto;">
        <p style="opacity:0.75;font-size:12px;margin:0 0 12px;">
          Put two or more applications or postings side-by-side to see exactly where they differ.
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:flex-end;margin-bottom:14px;">
          <label class="ow-field" style="min-width:160px;">
            <span>What to compare</span>
            <div class="ow-select">
              <select id="applicant-compare-kind">
                <option value="applications">Applications</option>
                <option value="postings">Postings</option>
              </select>
            </div>
          </label>
          <label class="ow-field" style="min-width:200px;flex:1;">
            <span>Campaign (optional scope)</span>
            <div class="ow-select">
              <select id="applicant-compare-campaign">
                <option value="">All campaigns</option>
              </select>
            </div>
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
  modal.addEventListener('keydown', (e) => { if (e.key === 'Escape') _close(); });
  modal.querySelector('#applicant-compare-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  modal.querySelector('#applicant-compare-run').addEventListener('click', _runCompare);
  _modalEl = modal;
  return modal;
}

function _close() {
  if (!_modalEl) return;
  _modalEl.classList.add('hidden');
  _modalEl.style.display = '';
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
    // Keep the "All campaigns" default; append the engine's campaigns.
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
  _setStatus('Comparing…', false);
  result.innerHTML = '';
  runBtn.disabled = true;
  try {
    const path = kind === 'postings' ? '/postings' : '/applications';
    const data = await _fetchJSON(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, campaign_id: campaignId }),
    });
    _setStatus('', false);
    _renderResult(result, data);
  } catch (e) {
    _setStatus(e && e.message ? e.message : 'Compare failed.', true);
  } finally {
    runBtn.disabled = false;
  }
}

function _renderResult(container, data) {
  container.innerHTML = '';
  if (!data) {
    container.innerHTML = '<div style="opacity:0.7;">No comparison returned.</div>';
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

  const table = document.createElement('table');
  table.className = 'applicant-compare-table';
  table.style.cssText = 'width:100%;border-collapse:collapse;font-size:12px;';

  const thead = document.createElement('thead');
  let headRow = '<tr><th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);">Dimension</th>';
  for (const id of entityIds) {
    headRow += `<th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);">${_esc(labels[id] || id)}</th>`;
  }
  headRow += '<th style="text-align:left;padding:6px 8px;border-bottom:1px solid var(--border);">Difference</th></tr>';
  thead.innerHTML = headRow;
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const dim of dimensions) {
    const values = (dim && dim.values) || {};
    let row = `<tr><td style="padding:6px 8px;border-bottom:1px solid var(--border);font-weight:600;">${_esc(dim.label || dim.key)}</td>`;
    for (const id of entityIds) {
      row += `<td style="padding:6px 8px;border-bottom:1px solid var(--border);">${_esc(values[id] != null ? values[id] : '—')}</td>`;
    }
    row += `<td style="padding:6px 8px;border-bottom:1px solid var(--border);opacity:0.8;">${_esc(dim.diff || '')}</td></tr>`;
    tbody.insertAdjacentHTML('beforeend', row);
  }
  table.appendChild(tbody);
  container.appendChild(table);
}

// ── Open / launchers / boot ──────────────────────────────────────────────────

export async function openApplicantCompare() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  _setStatus('', false);
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

const applicantCompareModule = { openApplicantCompare };

// Expose for deep-links / other modules without import coupling.
try { window.applicantCompareModule = applicantCompareModule; } catch { /* no-op */ }

export default applicantCompareModule;
