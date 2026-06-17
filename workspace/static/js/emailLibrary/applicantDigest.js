// static/js/emailLibrary/applicantDigest.js
//
// Applicant "Daily updates" panel inside the Email library popup.
//
// This is ADDITIVE to the workspace's native IMAP/SMTP mail. The native inbox
// grid (#email-lib-grid) is left exactly as-is; this module injects a separate
// collapsible panel ABOVE it that surfaces the Applicant job-search assistant's
// daily digest — the same "here are today's roles worth a look" summary that is
// also emailed — and lets the user act on each role right here:
//
//   • Open the role posting in a new tab,
//   • Approve a role (greenlight an application),
//   • Pass on a role with a short reason (the reason teaches the next run), and
//   • Send a quick note of feedback about the suggestions in general.
//
// Everything is backed by the workspace-side proxy at /api/applicant/email/*,
// which forwards to the engine's digest + feedback endpoints. The panel only
// appears once the assistant is set up (the feature layer reports the "email"
// section as "active"); until then it stays hidden so there is no dead UI.

import { showToast, styledPrompt, styledConfirm } from '../ui.js';

const API_BASE = window.location.origin;

// Remember the last campaign the user looked at so reopening the popup lands on
// the same digest. Shared global so any other surface can pre-select one too.
const LAST_CAMPAIGN_KEY = 'applicant-digest-last-campaign';

let _featurePromise = null;

// --- small DOM helpers -----------------------------------------------------

function _el(tag, opts = {}) {
  const node = document.createElement(tag);
  if (opts.cls) node.className = opts.cls;
  if (opts.text != null) node.textContent = opts.text;
  if (opts.html != null) node.innerHTML = opts.html;
  if (opts.title) node.title = opts.title;
  if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
  if (opts.style) node.style.cssText = opts.style;
  return node;
}

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// True only for http(s) URLs — guards the posting "Open" link against
// javascript:/data:/other schemes even though the value is trusted infra.
function _isWebUrl(u) {
  try {
    const proto = new URL(u, window.location.origin).protocol;
    return proto === 'http:' || proto === 'https:';
  } catch (_e) {
    return false;
  }
}

// Inline icons (match the line-icon style used across the email UI).
const _ICON_BELL =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>';
const _ICON_CHECK =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><polyline points="20 6 9 17 4 12"/></svg>';
const _ICON_PASS =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
const _ICON_LINK =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';

// --- feature gate ----------------------------------------------------------

// Ask the derived Applicant feature state whether the email/digest surface is
// live. Cached for the page session; never throws (a down engine -> not active).
async function _emailSectionActive() {
  if (!_featurePromise) {
    _featurePromise = (async () => {
      try {
        const r = await fetch(`${API_BASE}/api/applicant/features`, { credentials: 'same-origin' });
        if (!r.ok) return false;
        const data = await r.json();
        const sec = data && data.sections && data.sections.email;
        return !!(sec && sec.state === 'active');
      } catch (_) {
        return false;
      }
    })();
  }
  return _featurePromise;
}

// --- engine-backed calls (via the workspace proxy) -------------------------

async function _api(path, { method = 'GET', body = null } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body != null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`${API_BASE}/api/applicant/email${path}`, opts);
  let payload = null;
  try { payload = await r.json(); } catch (_) { payload = null; }
  if (!r.ok) {
    const detail = (payload && (payload.detail || payload.message)) || `Request failed (${r.status})`;
    const err = new Error(typeof detail === 'string' ? detail : 'Request failed');
    err.status = r.status;
    throw err;
  }
  return payload;
}

// Best id to act on for a digest row. Once an application exists the engine
// hangs an application_id off the row; before that the row is just a posting.
function _rowActionId(row) {
  return row.application_id || row.posting_id || row.id || '';
}

// --- rendering -------------------------------------------------------------

function _panelEl(modal) {
  return modal.querySelector('#applicant-digest-panel');
}

// Inject the panel shell once, just above the native email grid.
function _ensurePanel(modal) {
  let panel = _panelEl(modal);
  if (panel) return panel;
  const grid = modal.querySelector('#email-lib-grid');
  if (!grid || !grid.parentNode) return null;

  panel = _el('div', {
    cls: 'admin-card applicant-digest-panel',
    attrs: { id: 'applicant-digest-panel' },
    style: 'flex:0 0 auto;margin-bottom:8px;padding:10px 12px;',
  });
  panel.innerHTML = `
    <div class="applicant-digest-head" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <span class="section-title" style="font-weight:600;display:flex;align-items:center;">
        ${_ICON_BELL}Daily updates
      </span>
      <select class="memory-sort-select applicant-digest-campaign" id="applicant-digest-campaign"
              title="Choose which job search to show updates for"
              style="flex:0 1 auto;min-width:0;max-width:200px;"></select>
      <button type="button" class="memory-toolbar-btn" id="applicant-digest-refresh" title="Check for new updates"
              style="margin-left:auto;">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M1 4v6h6"/><path d="M23 20v-6h-6"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
        Refresh
      </button>
      <button type="button" class="memory-toolbar-btn" id="applicant-digest-feedback" title="Send the assistant a quick note about its suggestions">
        Send feedback
      </button>
    </div>
    <p class="memory-desc" style="margin:6px 0 4px;opacity:0.7;font-size:11px;">
      Roles your job-search assistant flagged today. The same summary is emailed to you; act on anything right here.
    </p>
    <div class="applicant-digest-body" id="applicant-digest-body"></div>
  `;
  grid.parentNode.insertBefore(panel, grid);
  return panel;
}

function _renderMessage(panel, msg, { muted = true } = {}) {
  const body = panel.querySelector('#applicant-digest-body');
  if (!body) return;
  body.innerHTML = '';
  body.appendChild(_el('div', {
    cls: 'email-loading',
    text: msg,
    style: `padding:14px 4px;font-size:12px;${muted ? 'opacity:0.7;' : ''}`,
  }));
}

function _renderDigest(panel, payload) {
  const body = panel.querySelector('#applicant-digest-body');
  if (!body) return;
  body.innerHTML = '';

  const rows = (payload && Array.isArray(payload.rows)) ? payload.rows : [];
  if (!rows.length) {
    const note = (payload && payload.note) ? String(payload.note)
      : 'No new roles cleared the bar today. The assistant keeps looking and will let you know.';
    body.appendChild(_el('div', {
      cls: 'email-loading',
      html: _esc(note),
      style: 'padding:12px 4px;font-size:12px;opacity:0.75;',
    }));
    return;
  }

  for (const row of rows) {
    body.appendChild(_buildRow(panel, row));
  }
}

function _buildRow(panel, row) {
  const card = _el('div', {
    cls: 'doclib-card applicant-digest-row',
    style: 'padding:9px 10px;margin-bottom:6px;cursor:default;',
  });
  card.dataset.actionId = _rowActionId(row);

  const title = row.title || row.summary || 'Untitled role';
  const company = row.company ? ` · ${row.company}` : '';
  const score = (row.viability_score != null) ? row.viability_score : null;

  const head = _el('div', { style: 'display:flex;align-items:baseline;gap:8px;' });
  head.appendChild(_el('span', {
    text: title + company,
    style: 'font-weight:600;font-size:13px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
    title: `${title}${company}`,
  }));
  if (score != null) {
    head.appendChild(_el('span', {
      cls: 'memory-count',
      text: `${score}% match`,
      title: 'How well this role fits what you told the assistant',
      style: 'font-size:10px;opacity:0.7;white-space:nowrap;',
    }));
  }
  card.appendChild(head);

  const why = row.why_suggested || row.reason || '';
  const meta = [row.work_mode, row.salary, row.source].filter(Boolean).join(' · ');
  if (why || meta) {
    card.appendChild(_el('div', {
      text: why || meta,
      title: why ? 'Why the assistant suggested this' : '',
      style: 'font-size:11px;opacity:0.72;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
    }));
  }

  // Actions row.
  const actions = _el('div', { style: 'display:flex;gap:6px;margin-top:7px;flex-wrap:wrap;' });

  // Only render a clickable link for real web URLs — never javascript:/data:/etc.,
  // even though the link comes from trusted same-origin infrastructure (defense in depth).
  if (row.link && _isWebUrl(row.link)) {
    const open = _el('a', {
      cls: 'memory-toolbar-btn',
      html: `${_ICON_LINK}Open`,
      title: 'Open the job posting in a new tab',
      attrs: { href: row.link, target: '_blank', rel: 'noopener noreferrer' },
      style: 'text-decoration:none;',
    });
    actions.appendChild(open);
  }

  const approve = _el('button', {
    cls: 'memory-toolbar-btn applicant-digest-approve',
    html: `${_ICON_CHECK}Approve`,
    title: 'Greenlight this role for an application',
    attrs: { type: 'button' },
  });
  approve.addEventListener('click', () => _onApprove(panel, card, row, approve));
  actions.appendChild(approve);

  const pass = _el('button', {
    cls: 'memory-toolbar-btn applicant-digest-pass',
    html: `${_ICON_PASS}Pass`,
    title: 'Skip this role and tell the assistant why (helps next time)',
    attrs: { type: 'button' },
  });
  pass.addEventListener('click', () => _onPass(panel, card, row, pass));
  actions.appendChild(pass);

  card.appendChild(actions);
  return card;
}

function _disableRow(card) {
  card.querySelectorAll('button').forEach(b => { b.disabled = true; });
}

function _fadeOutRow(card) {
  card.style.transition = 'opacity 0.25s ease, max-height 0.25s ease';
  card.style.opacity = '0';
  setTimeout(() => { try { card.remove(); } catch (_) {} }, 260);
}

// --- actions ---------------------------------------------------------------

async function _onApprove(panel, card, row, btn) {
  const id = _rowActionId(row);
  if (!id) { showToast('This role is not ready to approve yet.'); return; }
  _disableRow(card);
  try {
    await _api(`/applications/${encodeURIComponent(id)}/approve`, { method: 'POST' });
    showToast('Approved — the assistant will take it from here.');
    _fadeOutRow(card);
  } catch (e) {
    btn.disabled = false;
    card.querySelectorAll('button').forEach(b => { b.disabled = false; });
    showToast(e.message || 'Could not approve right now.');
  }
}

async function _onPass(panel, card, row, btn) {
  const id = _rowActionId(row);
  if (!id) { showToast('This role is not ready to act on yet.'); return; }
  // Feedback is mandatory on the decline path (the engine enforces it); ask for
  // a short reason up front so the user is never bounced with a 422.
  const reason = await styledPrompt(
    'Why pass on this one? A short reason teaches the assistant what to skip next time.',
    {
      title: 'Pass on this role',
      placeholder: 'e.g. too junior, wrong location, not my stack',
      confirmText: 'Pass',
      cancelText: 'Keep',
      maxLength: 280,
    },
  );
  if (reason == null) return;          // user cancelled
  if (!reason.trim()) {
    showToast('Add a short reason so the assistant can learn from it.');
    return;
  }
  _disableRow(card);
  try {
    await _api(`/applications/${encodeURIComponent(id)}/decline`, {
      method: 'POST',
      body: { feedback_text: reason.trim(), criteria_delta: {} },
    });
    showToast('Passed — thanks, that helps the next round.');
    _fadeOutRow(card);
  } catch (e) {
    card.querySelectorAll('button').forEach(b => { b.disabled = false; });
    showToast(e.message || 'Could not save that right now.');
  }
}

async function _onFeedback(panel, campaignId) {
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  const text = await styledPrompt(
    'Tell the assistant anything about its suggestions — what to show more or less of.',
    {
      title: 'Send feedback',
      placeholder: 'e.g. more remote roles, fewer recruiter agencies',
      confirmText: 'Send',
      cancelText: 'Cancel',
      maxLength: 500,
    },
  );
  if (text == null) return;
  if (!text.trim()) { showToast('Nothing to send.'); return; }
  try {
    await _api('/feedback/freetext', {
      method: 'POST',
      body: { campaign_id: campaignId, text: text.trim(), criteria_delta: {} },
    });
    showToast('Thanks — feedback sent.');
  } catch (e) {
    showToast(e.message || 'Could not send feedback right now.');
  }
}

// --- load + wire -----------------------------------------------------------

async function _loadDigest(panel, campaignId) {
  if (!campaignId) {
    _renderMessage(panel, 'No job search yet. Set one up to start getting daily updates.');
    return;
  }
  _renderMessage(panel, 'Loading today’s updates…');
  try {
    const payload = await _api(`/digest/${encodeURIComponent(campaignId)}`);
    _renderDigest(panel, payload);
  } catch (e) {
    _renderMessage(panel,
      e.status === 503 || e.status === 504
        ? 'The assistant is offline right now. Try again shortly.'
        : (e.message || 'Could not load updates right now.'),
    );
  }
}

function _currentCampaign(panel) {
  const sel = panel.querySelector('#applicant-digest-campaign');
  return sel ? sel.value : '';
}

async function _populateCampaigns(panel) {
  const sel = panel.querySelector('#applicant-digest-campaign');
  if (!sel) return '';
  let campaigns = [];
  try {
    const data = await _api('/campaigns');
    campaigns = (data && Array.isArray(data.campaigns)) ? data.campaigns : [];
  } catch (_) {
    campaigns = [];
  }
  sel.innerHTML = '';
  if (!campaigns.length) {
    sel.appendChild(_el('option', { text: 'No job search yet', attrs: { value: '' } }));
    sel.disabled = true;
    return '';
  }
  sel.disabled = false;
  const remembered = (() => { try { return localStorage.getItem(LAST_CAMPAIGN_KEY) || ''; } catch (_) { return ''; } })();
  const known = new Set(campaigns.map(c => String(c.id)));
  const initial = known.has(remembered) ? remembered
    : (window.__applicantActiveCampaign && known.has(String(window.__applicantActiveCampaign))
        ? String(window.__applicantActiveCampaign)
        : String(campaigns[0].id));
  for (const c of campaigns) {
    const opt = _el('option', { text: c.name || c.id, attrs: { value: String(c.id) } });
    if (String(c.id) === initial) opt.selected = true;
    sel.appendChild(opt);
  }
  return initial;
}

function _wire(panel) {
  if (panel.dataset.wired === '1') return;
  panel.dataset.wired = '1';
  const sel = panel.querySelector('#applicant-digest-campaign');
  if (sel) {
    sel.addEventListener('change', () => {
      const id = sel.value;
      try { localStorage.setItem(LAST_CAMPAIGN_KEY, id); } catch (_) {}
      _loadDigest(panel, id);
    });
  }
  const refresh = panel.querySelector('#applicant-digest-refresh');
  if (refresh) refresh.addEventListener('click', () => _loadDigest(panel, _currentCampaign(panel)));
  const fb = panel.querySelector('#applicant-digest-feedback');
  if (fb) fb.addEventListener('click', () => _onFeedback(panel, _currentCampaign(panel)));
}

// Tell the engine the user is reading updates in-app right now, so it can hold
// back the duplicate chat/Discord push for the same digest. Fire-and-forget.
function _signalPresence() {
  try {
    fetch(`${API_BASE}/api/applicant/email/presence`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ present: true }),
      keepalive: true,
    }).catch(() => {});
  } catch (_) {}
}

/**
 * Mount the Applicant "Daily updates" panel into an open email-library modal.
 * No-op (and removes any stale panel) unless the assistant's email/digest
 * surface is active. Safe to call every time the popup opens.
 */
export async function mountApplicantDigest(modal) {
  if (!modal) return;
  const active = await _emailSectionActive();
  if (!active) {
    // Not configured / engine down: make sure no stale panel lingers.
    const stale = _panelEl(modal);
    if (stale) stale.remove();
    return;
  }
  // The modal may have been closed/reopened while we awaited features.
  if (!document.body.contains(modal)) return;
  const panel = _ensurePanel(modal);
  if (!panel) return;
  _wire(panel);
  _signalPresence();
  const campaignId = await _populateCampaigns(panel);
  await _loadDigest(panel, campaignId);
}

export default { mountApplicantDigest };
