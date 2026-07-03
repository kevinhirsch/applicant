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
import { showDigestEmailPreview } from './digestEmailPreview.js';

const API_BASE = window.location.origin;

// Remember the last campaign the user looked at so reopening the popup lands on
// the same digest. Shared global so any other surface can pre-select one too.
const LAST_CAMPAIGN_KEY = 'applicant-digest-last-campaign';

let _featurePromise = null;
let _busyFeedback = false; // re-entry guard for feedback/survey actions

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

// Compact relative time ("just now", "5m ago", "3h ago", "2d ago") — same
// phrasing convention used elsewhere in the workspace (e.g. the Activity feed's
// `_relTime`). Kept local rather than imported since none of the existing
// helpers are exported from their modules. Accepts an epoch-ms number (or
// anything `Date.parse` understands); returns '' when unparseable so the
// caller can omit the freshness line cleanly.
function _relWhen(value) {
  if (value == null || value === '') return '';
  let ms = null;
  if (typeof value === 'number') {
    ms = value < 1e12 ? value * 1000 : value; // seconds vs ms heuristic
  } else {
    const t = Date.parse(value);
    if (!Number.isNaN(t)) ms = t;
  }
  if (ms == null) return '';
  const diff = Date.now() - ms;
  if (!Number.isFinite(diff)) return '';
  const s = Math.round(diff / 1000);
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d}d ago`;
  try { return new Date(ms).toLocaleDateString(); } catch (_e) { return ''; }
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
    style: 'flex:0 0 auto;',
  });
  panel.innerHTML = `
    <div class="applicant-digest-head" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
      <span class="section-title" style="font-weight:600;display:flex;align-items:center;">
        ${_ICON_BELL}Daily updates
      </span>
      <select class="memory-sort-select applicant-digest-campaign" id="applicant-digest-campaign"
              title="Choose which job search to show updates for"
              style="flex:0 1 auto;min-width:0;max-width:200px;"></select>
      <span class="memory-count applicant-digest-freshness" id="applicant-digest-freshness"
            title="How long ago this list was last refreshed"
            style="margin-left:auto;font-size:10px;opacity:0.65;white-space:nowrap;"></span>
      <button type="button" class="memory-toolbar-btn" id="applicant-digest-refresh" title="Check for new updates">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:3px;"><path d="M1 4v6h6"/><path d="M23 20v-6h-6"/><path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15"/></svg>
        Refresh
      </button>
      <button type="button" class="memory-toolbar-btn" id="applicant-digest-preview" title="Preview the digest exactly as it will be emailed to you">
        Preview email
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
    <div class="applicant-digest-bulk-bar" id="applicant-digest-bulk-bar" style="display:none;align-items:center;gap:8px;margin:0 0 6px;">
      <label class="memory-bulk-check-all"><input type="checkbox" id="applicant-digest-select-all"> All</label>
      <span class="memory-count" id="applicant-digest-selected-count" style="font-size:11px;opacity:0.75;">0 selected</span>
      <button type="button" class="memory-toolbar-btn applicant-digest-approve-selected" id="applicant-digest-approve-selected">
        ${_ICON_CHECK}Approve selected
      </button>
      <button type="button" class="memory-toolbar-btn applicant-digest-decline-selected" id="applicant-digest-decline-selected">
        ${_ICON_PASS}Decline selected
      </button>
    </div>
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

  // Every reload replaces the row set, so any prior selection can no longer
  // point at an on-screen row — drop it and collapse the bulk-actions bar.
  _selectionFor(panel).clear();
  _updateBulkBar(panel);

  const rows = (payload && Array.isArray(payload.rows)) ? payload.rows : [];
  if (!rows.length) {
    // Empty-day note: surface the engine's rationale — what was searched and why
    // (C2). Prefer the engine's ready-made `note` (which already folds in the
    // "Searched: …" summary); otherwise build a friendly line and append the
    // separate `searched` summary so the silence is never ambiguous.
    let note = (payload && payload.note) ? String(payload.note)
      : 'No new roles cleared the bar today. The assistant keeps looking and will let you know.';
    const searched = payload && payload.searched ? String(payload.searched) : '';
    if (searched && note.indexOf(searched) === -1) {
      note += ` Searched: ${searched}.`;
    }
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

// Build one digest row card with its full action set (Open / Approve / Pass /
// Research), all wired to the engine. This is the single source of truth for a
// digest row so the Email-tab panel and the Portal home base render and behave
// identically (C1) — neither duplicates the markup or the handlers.
//
// `ctx` supplies what the actions need without a hard dependency on the Email
// panel's DOM: `getCampaignId()` (for the research run) and an optional
// `onResolved(card, row)` hook fired after an approve/pass succeeds (the Portal
// uses it to refresh its count). When omitted the row falls back to the
// fade-out-in-place behaviour used inside the Email panel.
//
// Bulk selection (opt-in, quick-wins #4J "bulk digest actions") is threaded
// through the same `ctx`: pass `selectable: true`, `isSelected` (bool), and
// `onToggleSelect(id, checked)` to get a leading checkbox wired to the
// caller's selection state. Callers that don't pass `selectable` (the Portal
// embed) see no checkbox — this stays a strict opt-in so existing callers are
// unaffected.
// Presubmit-safety warning badge (duplicate-application guard, scam/ghost-job
// check, daily per-company volume cap, work-authorization eligibility check —
// dark-engine audit #43, product-gaps backlog). The engine now runs ALL FOUR
// checks that gate the pipeline at approval time read-only against every
// digest row (`applicant.application.services.digest_service.build_digest`),
// so a row can carry `warnings: [{check, message}, ...]` — informational
// only, never hides the row. Reuses the exact warning-chip visual pattern the
// Portal already uses for task urgency (`applicant-portal-badge` +
// `var(--color-warning, ...)`, see applicantPortal.js `_urgencyBadge`)
// instead of inventing a new one.
function _warningBadge(row) {
  const warnings = Array.isArray(row.warnings) ? row.warnings.filter((w) => w && w.message) : [];
  if (!warnings.length) return null;
  const checks = new Set(warnings.map((w) => w.check));
  let label;
  if (checks.has('duplicate_cooldown')) {
    label = 'You already applied to a similar role at this company';
  } else if (checks.has('per_company_volume')) {
    label = "You've hit today's application limit for this company";
  } else if (
    checks.has('eligibility_sponsorship')
    || checks.has('eligibility_no_sponsorship')
    || checks.has('eligibility_clearance')
  ) {
    label = 'This posting may not match your work-authorization profile';
  } else {
    label = 'This posting has some red flags — read before applying';
  }
  return _el('span', {
    cls: 'applicant-portal-badge applicant-digest-warning',
    text: label,
    title: warnings.map((w) => w.message).join(' '),
    style: 'background:var(--color-warning,#e0a96c);color:#000;font-size:10px;font-weight:600;'
      + 'padding:1px 6px;border-radius:8px;margin-left:6px;vertical-align:middle;white-space:normal;',
  });
}

// Referral nudge (product-gaps backlog: "referral/network prompt"). Purely
// informational, client-side only — NOT a new integration (no LinkedIn/network-
// graph scraping; that's explicitly out of scope). Referrals convert far better
// than cold applications, so for a posting at a notably large/well-known company
// (where the owner is statistically more likely to know someone there) we show a
// small, dismissible reminder to check their network before applying cold.
// Reuses the SAME warning/note-chip visual pattern `_warningBadge` above already
// established (`applicant-portal-badge`, see applicantPortal.js `_urgencyBadge`)
// rather than inventing new UI — just a different (informational, not warning)
// semantic color token that already exists in style.css (`--color-accent`).
//
// Low-frequency/non-naggy by design: shown at most once per posting, and a
// dismiss control persists per-posting in localStorage (`applicant_` prefix,
// matching this session's key-naming convention — see applicantPortal.js's
// `MILESTONES_SEEN_KEY` / `NOTIF_SEEN_KEY`) so a dismissed posting's nudge never
// reappears, even across reloads/days.
const REFERRAL_DISMISSED_KEY = 'applicant_digest_referral_dismissed';

// A small heuristic list of notably large/well-known employers — where a
// referral is most plausible because the owner is more likely to know someone
// there. Deliberately just a client-side name match, not a data integration.
const _REFERRAL_LIKELY_COMPANIES = [
  'google', 'alphabet', 'amazon', 'microsoft', 'apple', 'meta', 'facebook',
  'netflix', 'salesforce', 'oracle', 'ibm', 'adobe', 'nvidia', 'intel',
  'cisco', 'sap', 'stripe', 'uber', 'lyft', 'airbnb', 'linkedin', 'spotify',
  'tesla', 'goldman sachs', 'jpmorgan', 'morgan stanley', 'deloitte',
  'accenture', 'mckinsey', 'pwc', 'kpmg', 'ernst & young', 'walmart',
  'target', 'disney', 'samsung', 'sony', 'dell', 'hewlett packard',
  'vmware', 'twitter', 'block inc', 'paypal', 'ebay', 'shopify',
  'atlassian', 'servicenow', 'workday', 'twilio', 'snowflake', 'palantir',
  'boeing', 'lockheed martin', 'general electric', 'johnson & johnson',
  'pfizer', 'visa', 'mastercard', 'american express', 'wells fargo',
  'bank of america', 'citigroup', 'capital one',
];

function _isNotablyLargeCompany(company) {
  if (!company) return false;
  const c = String(company).toLowerCase();
  return _REFERRAL_LIKELY_COMPANIES.some((name) => c.indexOf(name) !== -1);
}

function _referralDismissedSet() {
  try {
    const raw = localStorage.getItem(REFERRAL_DISMISSED_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch (_) {
    return new Set();
  }
}

function _isReferralDismissed(id) {
  if (!id) return false;
  return _referralDismissedSet().has(id);
}

function _dismissReferralNudge(id) {
  if (!id) return;
  try {
    const seen = _referralDismissedSet();
    seen.add(id);
    localStorage.setItem(REFERRAL_DISMISSED_KEY, JSON.stringify(Array.from(seen)));
  } catch (_) { /* best-effort */ }
}

// Builds the dismissible referral-nudge row, or null when it shouldn't show
// (no company, not a notably large one, no stable id to dismiss against, or
// already dismissed for this posting). Never blocks/hides the row itself —
// purely an optional extra line, same spirit as `_warningBadge`.
function _referralNudge(row) {
  const company = row.company || '';
  const id = _rowActionId(row);
  if (!id || !_isNotablyLargeCompany(company) || _isReferralDismissed(id)) return null;

  const wrap = _el('div', {
    cls: 'applicant-portal-badge applicant-digest-referral',
    style: 'display:flex;align-items:center;gap:8px;margin-top:6px;padding:3px 8px;'
      + 'border-radius:8px;background:var(--color-accent,#00aaff);color:#fff;'
      + 'font-size:11px;font-weight:500;white-space:normal;',
  });
  wrap.appendChild(_el('span', {
    text: `Know anyone at ${company}? A referral can significantly improve your odds — worth a quick check before applying.`,
    style: 'flex:1;',
  }));
  const dismiss = _el('button', {
    text: '×',
    title: 'Dismiss this tip — it won’t show again for this posting',
    attrs: { type: 'button', 'aria-label': 'Dismiss referral tip' },
    style: 'flex:0 0 auto;background:none;border:none;color:inherit;cursor:pointer;'
      + 'font-size:14px;line-height:1;padding:0 2px;opacity:0.85;',
  });
  dismiss.addEventListener('click', () => {
    _dismissReferralNudge(id);
    wrap.remove();
  });
  wrap.appendChild(dismiss);
  return wrap;
}

export function buildDigestRow(row, ctx = {}) {
  const card = _el('div', {
    cls: 'doclib-card applicant-digest-row',
    style: 'padding:9px 10px;margin-bottom:6px;cursor:default;',
  });
  const actionId = _rowActionId(row);
  card.dataset.actionId = actionId;

  const title = row.title || row.summary || 'Untitled role';
  const company = row.company ? ` · ${row.company}` : '';
  const score = (row.viability_score != null) ? row.viability_score : null;

  const head = _el('div', { style: 'display:flex;align-items:baseline;gap:8px;' });

  if (ctx.selectable && actionId) {
    const cb = _el('input', {
      cls: 'memory-select-cb applicant-digest-select',
      attrs: { type: 'checkbox', 'aria-label': `Select ${title}${company}` },
      style: 'flex:0 0 auto;',
    });
    cb.checked = !!ctx.isSelected;
    cb.addEventListener('change', () => {
      if (typeof ctx.onToggleSelect === 'function') ctx.onToggleSelect(actionId, cb.checked, card);
    });
    head.appendChild(cb);
  }

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
  const warnBadge = _warningBadge(row);
  if (warnBadge) head.appendChild(warnBadge);
  card.appendChild(head);

  const why = row.why_suggested || row.reason || '';
  const meta = [row.work_mode, row.salary, row.source].filter(Boolean).join(' · ');
  if (why || meta) {
    // Why-this-role rationale: allow it to wrap to two lines instead of a single
    // truncated line (C3), so the reasoning is actually readable.
    card.appendChild(_el('div', {
      text: why || meta,
      title: why ? 'Why the assistant suggested this' : '',
      style: 'font-size:11px;opacity:0.72;margin-top:2px;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;',
    }));
  }

  const referralNudge = _referralNudge(row);
  if (referralNudge) card.appendChild(referralNudge);

  const getCampaignId = typeof ctx.getCampaignId === 'function' ? ctx.getCampaignId : () => '';
  const onResolved = typeof ctx.onResolved === 'function' ? ctx.onResolved : null;

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
  approve.addEventListener('click', () => _onApprove(card, row, approve, onResolved));
  actions.appendChild(approve);

  const pass = _el('button', {
    cls: 'memory-toolbar-btn applicant-digest-pass',
    html: `${_ICON_PASS}Pass`,
    title: 'Skip this role and tell the assistant why (helps next time)',
    attrs: { type: 'button' },
  });
  pass.addEventListener('click', () => _onPass(card, row, pass, onResolved));
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
  research.addEventListener('click', () => _onResearch(getCampaignId(), row, research));
  actions.appendChild(research);

  card.appendChild(actions);
  return card;
}

// --- bulk selection (Email-panel only; Portal's embed doesn't opt in) ------
//
// One selection Set per mounted panel (there is only ever one live email-lib
// panel, but a WeakMap avoids a stale module-level singleton across
// close/reopen cycles). Selection is cleared whenever the digest is reloaded
// (new rows) so it can never reference a row that's no longer on screen.
const _selectionByPanel = new WeakMap();

function _selectionFor(panel) {
  let sel = _selectionByPanel.get(panel);
  if (!sel) { sel = new Set(); _selectionByPanel.set(panel, sel); }
  return sel;
}

function _updateBulkBar(panel) {
  const sel = _selectionFor(panel);
  const bar = panel.querySelector('#applicant-digest-bulk-bar');
  const count = panel.querySelector('#applicant-digest-selected-count');
  const selectAll = panel.querySelector('#applicant-digest-select-all');
  if (count) count.textContent = `${sel.size} selected`;
  if (bar) bar.style.display = sel.size > 0 ? 'flex' : 'none';
  if (selectAll && sel.size === 0) selectAll.checked = false;
}

// Email-panel adapter: render a row bound to the panel's campaign selector and
// its bulk-selection state.
function _buildRow(panel, row) {
  const sel = _selectionFor(panel);
  const id = _rowActionId(row);
  return buildDigestRow(row, {
    getCampaignId: () => _currentCampaign(panel),
    selectable: true,
    isSelected: id ? sel.has(id) : false,
    onToggleSelect: (rowId, checked) => {
      if (checked) sel.add(rowId); else sel.delete(rowId);
      _updateBulkBar(panel);
    },
    // Keep the selection set (and the bulk-bar count) truthful when a row
    // resolves via its own single-row Approve/Pass button too.
    onResolved: (_card, resolvedRow) => {
      const rid = _rowActionId(resolvedRow);
      if (rid && sel.delete(rid)) _updateBulkBar(panel);
    },
  });
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

async function _onApprove(card, row, btn, onResolved) {
  const id = _rowActionId(row);
  if (!id) { showToast('This role is not ready to approve yet.'); return; }
  _disableRow(card);
  try {
    await _api(`/applications/${encodeURIComponent(id)}/approve`, { method: 'POST' });
    showToast('Approved — the assistant will take it from here.');
    _fadeOutRow(card);
    if (onResolved) { try { onResolved(card, row); } catch (_) {} }
  } catch (e) {
    btn.disabled = false;
    card.querySelectorAll('button').forEach(b => { b.disabled = false; });
    showToast(e.message || 'Could not approve right now.');
  }
}

async function _onPass(card, row, btn, onResolved) {
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
    if (onResolved) { try { onResolved(card, row); } catch (_) {} }
  } catch (e) {
    card.querySelectorAll('button').forEach(b => { b.disabled = false; });
    showToast(e.message || 'Could not save that right now.');
  }
}

// --- bulk approve / decline (quick-wins #4J "bulk digest actions") ---------
//
// There is no bulk engine endpoint for actually approving/declining
// applications (the pending-actions "resolve-bulk" route only clears Portal
// to-do notifications; even the engine's own chat "approve all today's roles"
// directive loops the per-posting approve call — see
// `ChatService._do_approve_all`). So these loop the SAME per-row
// `/applications/{id}/approve` / `/applications/{id}/decline` calls the
// single-row buttons already use, one request per selected row.

function _selectedRowCard(panel, id) {
  return panel.querySelector(
    `#applicant-digest-body .applicant-digest-row[data-action-id="${(window.CSS && CSS.escape) ? CSS.escape(id) : id}"]`,
  );
}

function _setBulkBusy(panel, busy) {
  ['#applicant-digest-approve-selected', '#applicant-digest-decline-selected', '#applicant-digest-select-all']
    .forEach((sel) => {
      const el = panel.querySelector(sel);
      if (el) el.disabled = busy;
    });
}

async function _onBulkApprove(panel) {
  const sel = _selectionFor(panel);
  if (!sel.size) return;
  const ids = Array.from(sel);
  _setBulkBusy(panel, true);
  let ok = 0;
  let fail = 0;
  for (const id of ids) {
    const card = _selectedRowCard(panel, id);
    if (card) _disableRow(card);
    try {
      await _api(`/applications/${encodeURIComponent(id)}/approve`, { method: 'POST' });
      ok += 1;
      sel.delete(id);
      if (card) _fadeOutRow(card);
    } catch (_e) {
      fail += 1;
      if (card) card.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    }
  }
  _setBulkBusy(panel, false);
  _updateBulkBar(panel);
  if (ok) {
    showToast(`Approved ${ok} role${ok === 1 ? '' : 's'}${fail ? ` — ${fail} couldn’t be approved.` : '.'}`);
  } else {
    showToast('Could not approve the selected roles.');
  }
}

async function _onBulkDecline(panel) {
  const sel = _selectionFor(panel);
  if (!sel.size) return;
  // Same mandatory-feedback rule as the single-row Pass: one shared reason
  // covers the whole batch (the engine records it per application).
  const reason = await styledPrompt(
    `Why pass on these ${sel.size} role${sel.size === 1 ? '' : 's'}? A short reason teaches the assistant what to skip next time.`,
    {
      title: `Pass on ${sel.size} role${sel.size === 1 ? '' : 's'}`,
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
  const ids = Array.from(sel);
  _setBulkBusy(panel, true);
  let ok = 0;
  let fail = 0;
  for (const id of ids) {
    const card = _selectedRowCard(panel, id);
    if (card) _disableRow(card);
    try {
      await _api(`/applications/${encodeURIComponent(id)}/decline`, {
        method: 'POST',
        body: { feedback_text: reason.trim(), criteria_delta: {} },
      });
      ok += 1;
      sel.delete(id);
      if (card) _fadeOutRow(card);
    } catch (_e) {
      fail += 1;
      if (card) card.querySelectorAll('button').forEach((b) => { b.disabled = false; });
    }
  }
  _setBulkBusy(panel, false);
  _updateBulkBar(panel);
  if (ok) {
    showToast(`Passed on ${ok} role${ok === 1 ? '' : 's'}${fail ? ` — ${fail} couldn’t be saved.` : ' — thanks, that helps the next round.'}`);
  } else {
    showToast('Could not save that right now.');
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

// Peek the cache before ever spending a research run (dark-engine audit item
// 38): a `null` return means nothing is cached yet for this query — the
// caller falls back to a fresh POST .../run. Any other failure (engine down,
// setup gate) is rethrown so it surfaces the same way a run failure would.
async function _apiResearchCached(campaignId, query) {
  try {
    return await _apiResearch(
      `/${encodeURIComponent(campaignId)}/cached?query=${encodeURIComponent(query)}`,
    );
  } catch (e) {
    if (e.status === 404) return null;
    throw e;
  }
}

async function _onResearch(campaignId, row, btn) {
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  const company = row.company || '';
  const role = row.title || row.role || '';
  const query = _researchQuery(row);
  const original = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `${_ICON_SEARCH}Researching…`;
  try {
    // A prior run may already have this exact brief cached — reuse it for
    // free instead of burning another research run on the same question.
    let report = await _apiResearchCached(campaignId, query);
    if (!report) {
      report = await _apiResearch(`/${encodeURIComponent(campaignId)}/run`, {
        method: 'POST',
        body: {
          query,
          company: company || null,
          role: role || null,
        },
      });
    }
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
  box.style.cssText = '--window-w:560px;';

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

async function _onFeedback(panel, campaignId, btn) {
  // Re-entry guard: hold the flag AND disable the triggering toolbar button for
  // the whole prompt + submit window, so a second click while the prompt is open
  // (or the POST is in flight) cannot fire a duplicate feedback note.
  if (_busyFeedback) return;
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  _busyFeedback = true;
  if (btn) btn.disabled = true;
  try {
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
    await _api('/feedback/freetext', {
      method: 'POST',
      body: { campaign_id: campaignId, text: text.trim(), criteria_delta: {} },
    });
    showToast('Thanks — feedback sent.');
  } catch (e) {
    showToast(e.message || 'Could not send feedback right now.');
  } finally {
    _busyFeedback = false;
    if (btn) btn.disabled = false;
  }
}

// --- email preview (#402: render the digest exactly as it will be emailed) ---
// Delegates to the dedicated digestEmailPreview module, which fetches the engine-
// rendered digest-email HTML through /api/applicant/email/digest/{id}/email and
// shows it in a sandboxed iframe (the email "as sent").
async function _onPreviewEmail(panel, campaignId) {
  return showDigestEmailPreview(campaignId);
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
    box.style.cssText = '--window-w:440px;';

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

async function _onSurvey(panel, campaignId, btn) {
  // Re-entry guard: hold the flag AND disable the triggering toolbar button for
  // the whole survey + submit window, so a second click while the survey modal is
  // open (or the POST is in flight) cannot fire a duplicate survey submission.
  if (_busyFeedback) return;
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  _busyFeedback = true;
  if (btn) btn.disabled = true;
  try {
    const answers = await _askSurvey();
    if (answers == null) return;                       // cancelled
    if (!Object.keys(answers).length) {
      showToast('Pick at least one answer, or use Send feedback for a free note.');
      return;
    }
    const res = await _api('/feedback/survey', {
      method: 'POST',
      body: { campaign_id: campaignId, answers },
    });
    // A core detail inferred from the survey is held for confirmation (FR-FB-3) and
    // now waits in the portal — point the user there instead of a silent "thanks".
    const pending = (res && Array.isArray(res.pending)) ? res.pending.length : 0;
    if (pending > 0) {
      showToast(`Thanks — ${pending} change${pending === 1 ? '' : 's'} need${pending === 1 ? 's' : ''} your OK in your to-do list.`);
    } else {
      showToast('Thanks — that helps the assistant tune things.');
    }
  } catch (e) {
    showToast(e.message || 'Could not send the survey right now.');
  } finally {
    _busyFeedback = false;
    if (btn) btn.disabled = false;
  }
}

// --- load + wire -----------------------------------------------------------

// --- freshness indicator (quick-wins #4J "updated Ns ago") -----------------
//
// A small "Updated Ns ago" readout next to the campaign picker so the user
// can tell at a glance how stale the on-screen list is, without having to
// guess whether Refresh actually did anything. Updates on every successful
// load, and otherwise ages forward on its own piggybacked on the presence
// heartbeat's existing ~60s `setInterval` (see `_signalPresence` below) —
// deliberately NOT a second interval loop, so this file keeps the single
// content-poll-free heartbeat the hidden-tab-polling regression test pins.
function _renderFreshness(panel) {
  const el = panel.querySelector('#applicant-digest-freshness');
  if (!el) return;
  const ts = Number(panel.dataset.loadedAt || 0);
  el.textContent = ts ? `Updated ${_relWhen(ts)}` : '';
}

async function _loadDigest(panel, campaignId) {
  if (!campaignId) {
    _renderMessage(panel, 'No job search yet. Set one up to start getting daily updates.');
    panel.dataset.loadedAt = '';
    _renderFreshness(panel);
    return;
  }
  _renderMessage(panel, 'Loading today’s updates…');
  try {
    const payload = await _api(`/digest/${encodeURIComponent(campaignId)}`);
    _renderDigest(panel, payload);
    panel.dataset.loadedAt = String(Date.now());
    _renderFreshness(panel);
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
  const preview = panel.querySelector('#applicant-digest-preview');
  if (preview) preview.addEventListener('click', () => _onPreviewEmail(panel, _currentCampaign(panel)));
  const fb = panel.querySelector('#applicant-digest-feedback');
  if (fb) fb.addEventListener('click', () => _onFeedback(panel, _currentCampaign(panel), fb));
  const survey = panel.querySelector('#applicant-digest-survey');
  if (survey) survey.addEventListener('click', () => _onSurvey(panel, _currentCampaign(panel), survey));

  const selectAll = panel.querySelector('#applicant-digest-select-all');
  if (selectAll) {
    selectAll.addEventListener('change', () => {
      const sel = _selectionFor(panel);
      const checked = selectAll.checked;
      panel.querySelectorAll('#applicant-digest-body .applicant-digest-row').forEach((card) => {
        const id = card.dataset.actionId;
        if (!id) return;
        if (checked) sel.add(id); else sel.delete(id);
        const cb = card.querySelector('.applicant-digest-select');
        if (cb) cb.checked = checked;
      });
      _updateBulkBar(panel);
    });
  }
  const bulkApprove = panel.querySelector('#applicant-digest-approve-selected');
  if (bulkApprove) bulkApprove.addEventListener('click', () => _onBulkApprove(panel));
  const bulkDecline = panel.querySelector('#applicant-digest-decline-selected');
  if (bulkDecline) bulkDecline.addEventListener('click', () => _onBulkDecline(panel));
}

// Web-presence heartbeat (FR-NOTIF-2). Tells the engine the user is verifiably
// here — focused tab + recent input — so it pre-empts the duplicate chat/Discord
// push only while that is TRUE, and the signal DECAYS the moment they leave. The
// engine treats a presence signal as fresh for ~90s, so we re-signal well inside
// that window and explicitly send present:false on blur / hidden / unload. (Replaces
// the old one-shot present:true, which suppressed Discord indefinitely after a
// single digest view.)
let _presenceTimer = null;
let _presenceBound = false;
let _lastActivityTs = 0;
// The most recently mounted digest panel, so the presence heartbeat's
// existing interval (below) can also age the "Updated Ns ago" freshness
// label forward without a second setInterval loop.
let _freshnessPanel = null;

function _postPresence(present) {
  try {
    fetch(`${API_BASE}/api/applicant/email/presence`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ present: !!present }),
      keepalive: true,
    }).catch(() => {});
  } catch (_) {}
}

function _markPresenceActivity() { _lastActivityTs = Date.now(); }

// Verifiably present = tab visible AND focused AND user-active within ~90s.
function _isVerifiablyHere() {
  const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden';
  const focused = typeof document === 'undefined' || !document.hasFocus || document.hasFocus();
  const active = (Date.now() - _lastActivityTs) < 90000;
  return !hidden && focused && active;
}

function _signalPresence() {
  _markPresenceActivity();
  _postPresence(true);
  if (_presenceTimer) return; // heartbeat already running for this page session
  if (typeof window !== 'undefined' && !_presenceBound) {
    _presenceBound = true;
    ['pointerdown', 'keydown', 'pointermove', 'scroll'].forEach((ev) => {
      try { window.addEventListener(ev, _markPresenceActivity, { passive: true }); } catch (_) {}
    });
    const leave = () => _postPresence(false);
    const enter = () => { _markPresenceActivity(); _postPresence(true); };
    try {
      document.addEventListener('visibilitychange', () => {
        (document.visibilityState === 'hidden') ? leave() : enter();
      });
      window.addEventListener('blur', leave);
      window.addEventListener('focus', enter);
      window.addEventListener('pagehide', leave);
    } catch (_) {}
  }
  // Re-signal inside the engine's ~90s freshness window; each beat reflects whether
  // the user is still verifiably here, so presence lapses on its own when they go.
  // Piggybacks the freshness-label tick onto this same beat (see `_freshnessPanel`
  // above) instead of adding a second interval loop.
  try {
    _presenceTimer = setInterval(() => {
      _postPresence(_isVerifiablyHere());
      if (_freshnessPanel && document.body.contains(_freshnessPanel)) _renderFreshness(_freshnessPanel);
    }, 60000);
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
  _freshnessPanel = panel;
  _signalPresence();
  const campaignId = await _populateCampaigns(panel);
  await _loadDigest(panel, campaignId);
}

// Shared digest data accessors so other surfaces (the Portal home base) can
// render today's digest with the exact same engine calls and row renderer
// instead of duplicating any of it (C1). All soft-degrade like the panel above.

// List the owner's job searches (campaigns). Returns [] on any failure.
export async function listCampaigns() {
  try {
    const data = await _api('/campaigns');
    return (data && Array.isArray(data.campaigns)) ? data.campaigns : [];
  } catch (_) {
    return [];
  }
}

// Fetch the digest payload for one job search (campaign).
export async function fetchDigest(campaignId) {
  if (!campaignId) return { rows: [], empty: true };
  return _api(`/digest/${encodeURIComponent(campaignId)}`);
}

// The remembered/last-viewed job search id, shared with the Email panel so both
// surfaces land on the same one.
export function rememberedCampaignId() {
  try { return localStorage.getItem(LAST_CAMPAIGN_KEY) || ''; } catch (_) { return ''; }
}

export async function loadEmailInbox() {
  try {
    const data = await _api('/inbox');
    return (data && Array.isArray(data.items)) ? data.items : [];
  } catch (_) {
    return [];
  }
}

export async function dismissNotification(id) {
  return _api(`/inbox/${encodeURIComponent(id)}/dismiss`, { method: 'POST' });
}

export async function triggerDigestDelivery(campaignId) {
  return _api(`/campaigns/${encodeURIComponent(campaignId)}/digest/deliver`, { method: 'POST' });
}

export default { mountApplicantDigest, buildDigestRow, listCampaigns, fetchDigest, rememberedCampaignId, loadEmailInbox, dismissNotification, triggerDigestDelivery };
