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
const _ICON_SEARCH =
  '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px;"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>';

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

// Same shape as _api but against the manual deep-research proxy
// (/api/applicant/research/*) instead of the email/digest proxy.
async function _apiResearch(path, { method = 'GET', body = null } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body != null) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(`${API_BASE}/api/applicant/research${path}`, opts);
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
      <button type="button" class="memory-toolbar-btn" id="applicant-digest-survey" title="Answer a few quick questions to help the assistant tune what it sends">
        Quick survey
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

  // Manual deep-research trigger: kick a research run on this company/role and
  // show the report. The agent researches on its own when it hits a gap; this is
  // the user-initiated counterpart, sharing the same capped/cached engine path.
  const research = _el('button', {
    cls: 'memory-toolbar-btn applicant-digest-research',
    html: `${_ICON_SEARCH}Research`,
    title: 'Run a quick background-research brief on this company/role',
    attrs: { type: 'button' },
  });
  research.addEventListener('click', () => _onResearch(panel, row, research));
  actions.appendChild(research);

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

// Build a short research query from a digest row (title + company), so the run
// is about the right thing even when the engine has no extra context yet.
function _researchQuery(row) {
  const role = row.title || row.role || '';
  const company = row.company || '';
  if (role && company) return `${role} at ${company}`;
  return role || company || 'this role';
}

async function _onResearch(panel, row, btn) {
  const campaignId = _currentCampaign(panel);
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  const company = row.company || '';
  const role = row.title || row.role || '';
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `${_ICON_SEARCH}Researching…`;
  try {
    const report = await _apiResearch(`/${encodeURIComponent(campaignId)}/run`, {
      method: 'POST',
      body: {
        query: _researchQuery(row),
        company: company || null,
        role: role || null,
      },
    });
    _showReport(report, { company, role });
  } catch (e) {
    showToast(
      e.status === 503 || e.status === 504
        ? 'The assistant is offline right now. Try again shortly.'
        : (e.message || 'Could not run research right now.'),
    );
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

// Show a research report in a small self-contained modal (same lightweight modal
// shell as the survey above; no new modal system). Handles the engine's degraded
// 200 payload (unavailable:true + reason) gracefully and shows budget remaining.
function _showReport(report, { company = '', role = '' } = {}) {
  let overlay = document.getElementById('applicant-research-overlay');
  if (overlay) overlay.remove();

  overlay = _el('div', { cls: 'modal', attrs: { id: 'applicant-research-overlay' } });
  const box = _el('div', { cls: 'modal-content styled-confirm-box' });
  box.style.cssText = 'max-width:560px;';

  const header = _el('div', { cls: 'modal-header' });
  const heading = [role, company].filter(Boolean).join(' · ');
  header.appendChild(_el('h4', { text: heading ? `Research — ${heading}` : 'Research brief' }));
  box.appendChild(header);

  const bodyEl = _el('div', { cls: 'modal-body' });
  bodyEl.style.cssText = 'max-height:60vh;overflow:auto;';
  const data = report || {};

  // Budget line (when the engine reported it).
  if (data.budget_remaining != null) {
    bodyEl.appendChild(_el('div', {
      cls: 'memory-count',
      text: `${data.budget_remaining} research run${data.budget_remaining === 1 ? '' : 's'} left for this job search${data.cached ? ' · served from a recent brief (no run used)' : ''}`,
      style: 'font-size:10px;opacity:0.7;margin-bottom:8px;',
    }));
  }

  if (data.unavailable) {
    // Channel off / budget exhausted — a graceful state, not an error.
    const reasons = {
      workspace_unavailable: 'Background research isn’t set up yet. Connect it in setup to enable research briefs.',
      budget_exhausted: 'You’ve used up this job search’s research runs for now. They refresh over time.',
      empty_query: 'There wasn’t enough to research on this role.',
      research_failed: 'The research run didn’t complete this time. Please try again shortly.',
    };
    bodyEl.appendChild(_el('p', {
      text: reasons[data.reason] || 'Research isn’t available for this one right now.',
      style: 'margin:4px 0;font-size:13px;opacity:0.85;',
    }));
  } else {
    if (data.summary) {
      bodyEl.appendChild(_el('p', {
        text: data.summary,
        style: 'margin:4px 0 12px;font-size:13px;line-height:1.5;',
      }));
    }
    const findings = Array.isArray(data.key_findings) ? data.key_findings : [];
    if (findings.length) {
      bodyEl.appendChild(_el('div', {
        text: 'Key findings',
        style: 'font-weight:600;font-size:12px;margin:8px 0 4px;',
      }));
      const ul = _el('ul', { style: 'margin:0 0 10px;padding-left:18px;font-size:12px;line-height:1.5;' });
      for (const f of findings) ul.appendChild(_el('li', { text: String(f) }));
      bodyEl.appendChild(ul);
    }
    const sources = Array.isArray(data.sources) ? data.sources : [];
    if (sources.length) {
      bodyEl.appendChild(_el('div', {
        text: 'Sources',
        style: 'font-weight:600;font-size:12px;margin:8px 0 4px;',
      }));
      const list = _el('div', { style: 'display:flex;flex-direction:column;gap:3px;' });
      for (const s of sources) {
        const url = (s && (s.url || s.link)) || '';
        const label = (s && (s.title || s.name)) || url || 'Source';
        if (url && _isWebUrl(url)) {
          list.appendChild(_el('a', {
            text: label,
            attrs: { href: url, target: '_blank', rel: 'noopener noreferrer' },
            style: 'font-size:12px;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;',
            title: url,
          }));
        } else {
          list.appendChild(_el('div', { text: label, style: 'font-size:12px;opacity:0.8;' }));
        }
      }
      bodyEl.appendChild(list);
    }
    if (!data.summary && !findings.length && !sources.length) {
      bodyEl.appendChild(_el('p', {
        text: 'No findings came back for this one.',
        style: 'margin:4px 0;font-size:13px;opacity:0.8;',
      }));
    }
  }
  box.appendChild(bodyEl);

  const footer = _el('div', { cls: 'modal-footer' });
  const closeBtn = _el('button', {
    cls: 'confirm-btn confirm-btn-primary', text: 'Close', attrs: { type: 'button' },
  });
  footer.appendChild(closeBtn);
  box.appendChild(footer);
  overlay.appendChild(box);
  document.body.appendChild(overlay);

  function cleanup() {
    closeBtn.removeEventListener('click', onClose);
    overlay.removeEventListener('click', onBackdrop);
    document.removeEventListener('keydown', onKey);
    try { overlay.remove(); } catch (_) {}
  }
  function onClose() { cleanup(); }
  function onBackdrop(e) { if (e.target === overlay) cleanup(); }
  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cleanup(); }
  }
  closeBtn.addEventListener('click', onClose);
  overlay.addEventListener('click', onBackdrop);
  document.addEventListener('keydown', onKey);
  closeBtn.focus();
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

// --- guided survey (a few structured questions) ----------------------------
//
// A short, optional survey that complements the free-text note above: instead
// of an open box it asks a handful of pointed questions with fixed choices, so
// the answers fold cleanly into the next run's learning. Each question carries a
// plain-language label, a one-line "why we ask" hint, and a small set of
// choices. Answers post to the survey endpoint as a {question_key: choice} map;
// blank (skipped) questions are dropped so a partial survey is fine. The whole
// thing is self-contained here (its own lightweight modal) so the shared prompt
// helpers stay single-purpose.
const _SURVEY_QUESTIONS = [
  {
    key: 'relevance',
    label: 'How on-target were today’s roles?',
    hint: 'Whether the suggestions matched the kind of job you actually want.',
    choices: [
      { value: 'great', label: 'Spot on' },
      { value: 'ok', label: 'Mixed' },
      { value: 'off', label: 'Mostly off' },
    ],
  },
  {
    key: 'resume_quality',
    label: 'How well did the tailored resume read?',
    hint: 'Your take on the resume the assistant prepared for these roles.',
    choices: [
      { value: 'strong', label: 'Strong' },
      { value: 'fine', label: 'Fine' },
      { value: 'needs_work', label: 'Needs work' },
    ],
  },
  {
    key: 'pacing',
    label: 'How does the volume feel?',
    hint: 'Whether you’re getting too many, too few, or about the right number of suggestions.',
    choices: [
      { value: 'too_many', label: 'Too many' },
      { value: 'just_right', label: 'About right' },
      { value: 'too_few', label: 'Too few' },
    ],
  },
];

// Build + show a small modal of the survey questions. Resolves to a
// {question_key: choice_value} map of the answered questions (skipped ones are
// omitted), or null if the user cancels / dismisses. Self-contained: it creates
// its own overlay (reused across opens) and never touches the shared modals.
function _askSurvey() {
  return new Promise(resolve => {
    let overlay = document.getElementById('applicant-survey-overlay');
    if (overlay) overlay.remove();   // rebuild fresh so choices always reset

    overlay = _el('div', { cls: 'modal', attrs: { id: 'applicant-survey-overlay' } });
    const box = _el('div', { cls: 'modal-content styled-confirm-box' });
    box.style.cssText = 'max-width:440px;';

    const header = _el('div', { cls: 'modal-header' });
    header.appendChild(_el('h4', { text: 'Quick survey' }));
    box.appendChild(header);

    const bodyEl = _el('div', { cls: 'modal-body' });
    bodyEl.appendChild(_el('p', {
      text: 'A few quick questions help the assistant tune what it sends. Answer any that apply — skip the rest.',
      style: 'margin:0 0 10px;font-size:12px;opacity:0.8;',
    }));

    // question_key -> currently selected choice value
    const selected = {};

    for (const q of _SURVEY_QUESTIONS) {
      const group = _el('div', { style: 'margin-bottom:12px;' });
      const lbl = _el('div', {
        text: q.label,
        title: q.hint,
        style: 'font-weight:600;font-size:12px;display:flex;align-items:center;gap:5px;',
      });
      // Inline "why we ask" tooltip marker (hover for the hint).
      lbl.appendChild(_el('span', {
        text: '?',
        title: q.hint,
        attrs: { 'aria-label': q.hint },
        style: 'display:inline-flex;align-items:center;justify-content:center;width:14px;height:14px;border-radius:50%;border:1px solid currentColor;font-size:9px;opacity:0.6;cursor:help;',
      }));
      group.appendChild(lbl);

      const opts = _el('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;margin-top:5px;' });
      for (const c of q.choices) {
        const chip = _el('button', {
          cls: 'memory-toolbar-btn',
          text: c.label,
          attrs: { type: 'button' },
          style: 'font-size:11px;',
        });
        chip.addEventListener('click', () => {
          // Toggle: clicking the selected chip clears it (skip the question).
          const already = selected[q.key] === c.value;
          opts.querySelectorAll('button').forEach(b => b.classList.remove('active'));
          if (already) {
            delete selected[q.key];
          } else {
            selected[q.key] = c.value;
            chip.classList.add('active');
          }
        });
        opts.appendChild(chip);
      }
      group.appendChild(opts);
      bodyEl.appendChild(group);
    }
    box.appendChild(bodyEl);

    const footer = _el('div', { cls: 'modal-footer' });
    const cancelBtn = _el('button', {
      cls: 'confirm-btn confirm-btn-secondary', text: 'Cancel', attrs: { type: 'button' },
    });
    const okBtn = _el('button', {
      cls: 'confirm-btn confirm-btn-primary', text: 'Send', attrs: { type: 'button' },
    });
    footer.appendChild(cancelBtn);
    footer.appendChild(okBtn);
    box.appendChild(footer);
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    function cleanup(result) {
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      overlay.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      try { overlay.remove(); } catch (_) {}
      resolve(result);
    }
    function onOk() { cleanup({ ...selected }); }
    function onCancel() { cleanup(null); }
    function onBackdrop(e) { if (e.target === overlay) cleanup(null); }
    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        cleanup(null);
      }
    }
    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    overlay.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
    okBtn.focus();
  });
}

async function _onSurvey(panel, campaignId) {
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  const answers = await _askSurvey();
  if (answers == null) return;                       // cancelled
  if (!Object.keys(answers).length) {
    showToast('Pick at least one answer, or use Send feedback for a free note.');
    return;
  }
  try {
    await _api('/feedback/survey', {
      method: 'POST',
      body: { campaign_id: campaignId, answers },
    });
    showToast('Thanks — that helps the assistant tune things.');
  } catch (e) {
    showToast(e.message || 'Could not send the survey right now.');
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
  const survey = panel.querySelector('#applicant-digest-survey');
  if (survey) survey.addEventListener('click', () => _onSurvey(panel, _currentCampaign(panel)));
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
