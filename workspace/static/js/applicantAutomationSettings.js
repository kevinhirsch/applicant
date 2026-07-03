// static/js/applicantAutomationSettings.js
//
// Settings > Automation (dark-engine audit items 82/84/85/86/87/88/90) — a
// generic engine-preferences tab. The dark-engine audit found ~20 engine config
// knobs that were env-only with zero Settings UI ("the workspace Settings surface
// mounts only four wizard renderers ... plus the campaign and model-ladder tabs —
// there is no generic engine-preferences tab", 08_engine_dark_matrix.md §B8). This
// module builds that tab; later phases add more cards here rather than inventing
// another tab.
//
// What it surfaces:
//   * Browser timezone + locale (item 82) — the fingerprint the pre-fill browser
//     presents; should match the egress exit IP's region or the tz/IP contradiction
//     is the exact tell the stealth layer exists to avoid.
//   * Let Applicant create accounts on job sites automatically (item 84) — opt-in
//     for the engine to create an ATS account from a vaulted credential instead of
//     always handing off to a human. The safety gate itself stays server-side
//     (ADR-0004); this is only the operator's opt-in switch.
//   * Per-company daily application cap (item 85) — the max applications sent to
//     the same company in one day (a volume/scam-avoidance safety valve, G07).
//   * How long we keep your personal data (item 87) — the parsed PII / EEO /
//     intake-data retention window; 0 (the default) means kept forever, so the
//     copy is deliberately plain and honest about what that means.
//   * Re-apply cooldown (item 88) — how many days before Applicant will apply to
//     the same company/role pair again (a duplicate-application safety valve).
//   * Approval timeout (item 90) — how many days a pending final-approval waits
//     before the application times out, plus an optional precise-seconds override
//     for fine-tuned control.
//   * Check-for-work interval (item 86) — how often the 24/7 background loop
//     ticks looking for new work.
//   * Run the data-retention sweep now (dark-engine audit item 37) — a manual
//     trigger + last-result report for the SAME prune the retention window
//     above configures. The window (item 87) only decides HOW LONG data is
//     kept; before now there was no way to run that sweep on demand or see
//     what it actually removed. Destructive (permanently deletes personal
//     data), so it is gated behind a plain-language confirm — same shape as
//     applicantRemote.js's / applicantCampaignSettings.js's ``_confirm``.
//
// STANDALONE tab module (not a wizard-step renderer) — same shape as
// applicantCampaignSettings.js / applicantModelLadder.js: talks only to the
// owner-scoped front-door proxy (/api/applicant/setup/automation), which proxies
// the engine's SetupService-backed config store. Mounted lazily by settings.js
// when the Automation tab opens; re-renders fresh each open so it reflects the
// latest saved state. The sweep-now button below talks to the SEPARATE
// admin-gated proxy (/api/applicant/admin/retention/prune), which runs the real
// engine cascade and hands back real per-store counts — never a fabricated one.

import { esc, _toast, _fetchJSON, _put, _post } from './applicantCore.js';
import uiModule from './ui.js';

const BASE = '/api/applicant/setup/automation';
const SWEEP_URL = '/api/applicant/admin/retention/prune';

let _host = null;
let _prefs = null;

async function _load() {
  try {
    return { available: true, prefs: await _fetchJSON(BASE) };
  } catch {
    return { available: false, prefs: null };
  }
}

function _cardHTML(prefs) {
  const tz = esc(prefs.egress_timezone || 'America/Phoenix');
  const locale = esc(prefs.egress_locale || 'en-US');
  const allowAccounts = !!prefs.allow_automated_accounts;
  const cap = Number.isFinite(prefs.presubmit_max_apps_per_company_per_day)
    ? prefs.presubmit_max_apps_per_company_per_day
    : 3;
  const retentionDays = Number.isFinite(prefs.pii_retention_days)
    ? prefs.pii_retention_days
    : 0;
  const cooldownDays = Number.isFinite(prefs.presubmit_duplicate_cooldown_days)
    ? prefs.presubmit_duplicate_cooldown_days
    : 30;
  const approvalDays = Number.isFinite(prefs.approval_timeout_days)
    ? prefs.approval_timeout_days
    : 30;
  const approvalWaitSeconds = Number.isFinite(prefs.approval_wait_seconds)
    ? prefs.approval_wait_seconds
    : '';
  const checkInterval = Number.isFinite(prefs.scheduler_interval_seconds)
    ? prefs.scheduler_interval_seconds
    : 60;
  return `
    <div class="admin-card">
      <h2>Browser identity</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        The timezone and locale Applicant's automated browser presents. Keep these
        matched to where your traffic actually exits from — a mismatch is the kind
        of inconsistency automated-browsing detection looks for.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-timezone">Timezone</label>
        <input id="as-timezone" class="settings-input" type="text" value="${tz}"
               placeholder="America/Phoenix" data-as-field="egress_timezone">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-locale">Locale</label>
        <input id="as-locale" class="settings-input" type="text" value="${locale}"
               placeholder="en-US" data-as-field="egress_locale">
      </div>
    </div>
    <div class="admin-card">
      <h2 style="display:flex;align-items:center;gap:6px;">
        Account creation
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-allow-accounts">
          <input type="checkbox" id="as-allow-accounts" data-as-field="allow_automated_accounts" ${allowAccounts ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Let Applicant create accounts on job sites automatically, using a saved
        sign-in from your vault, instead of always handing that step to you. CAPTCHAs,
        email/SMS verification, and the final submit always stay a human step no
        matter what this is set to.
      </div>
    </div>
    <div class="admin-card">
      <h2>Per-company daily limit</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        The most applications Applicant will send to the same company in one day —
        a safety valve against over-applying to one place.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-company-cap">Applications per company per day</label>
        <input id="as-company-cap" class="settings-input" type="number" min="0" step="1"
               value="${esc(String(cap))}" data-as-field="presubmit_max_apps_per_company_per_day"
               style="max-width:120px">
      </div>
    </div>
    <div class="admin-card">
      <h2>Re-apply cooldown</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        How many days Applicant waits before applying to the same company and role
        again, once you've already applied there.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-cooldown">Days before re-applying</label>
        <input id="as-cooldown" class="settings-input" type="number" min="0" step="1"
               value="${esc(String(cooldownDays))}" data-as-field="presubmit_duplicate_cooldown_days"
               style="max-width:120px">
      </div>
    </div>
    <div class="admin-card">
      <h2>How long we keep your personal data</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        How many days Applicant keeps the personal details you shared during
        setup — resume answers, EEO/diversity answers, and other application-intake
        data — before deleting them. Set this to <strong>0</strong> to keep this
        data forever (the default, and today's behavior) — nothing is ever
        automatically deleted unless you set a number of days here.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-retention">Days to keep your data (0 = keep forever)</label>
        <input id="as-retention" class="settings-input" type="number" min="0" step="1"
               value="${esc(String(retentionDays))}" data-as-field="pii_retention_days"
               style="max-width:120px">
      </div>
      <div class="settings-row" style="gap:8px; margin-top:4px;">
        <button type="button" class="cal-btn" id="as-sweep-now">Run data-retention sweep now</button>
        <span id="as-sweep-msg" class="admin-toggle-sub"></span>
      </div>
      <div id="as-sweep-result" class="admin-toggle-sub" style="margin-top:6px;"></div>
    </div>
    <div class="admin-card">
      <h2>Approval timeout</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        How long Applicant waits for your decision on a final submission before
        the application times out and is set aside. 0 days means it waits
        indefinitely.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-approval-days">Days to wait</label>
        <input id="as-approval-days" class="settings-input" type="number" min="0" step="1"
               value="${esc(String(approvalDays))}" data-as-field="approval_timeout_days"
               style="max-width:120px">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-approval-seconds">Precise override (seconds)</label>
        <input id="as-approval-seconds" class="settings-input" type="number" min="0" step="1"
               value="${esc(String(approvalWaitSeconds))}" placeholder="Leave blank to use days above"
               data-as-field="approval_wait_seconds" style="max-width:180px">
      </div>
    </div>
    <div class="admin-card">
      <h2>How often Applicant checks for work</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        How frequently the background loop looks for new job listings, pending
        actions, and other work. Lower values react faster; higher values
        reduce load.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-check-interval">Check interval (seconds)</label>
        <input id="as-check-interval" class="settings-input" type="number" min="1" step="1"
               value="${esc(String(checkInterval))}" data-as-field="scheduler_interval_seconds"
               style="max-width:120px">
      </div>
    </div>
    <div class="settings-row" style="gap:8px">
      <button type="button" class="cal-btn cal-btn-primary" id="as-save">Save changes</button>
      <span id="as-msg" class="admin-toggle-sub"></span>
    </div>`;
}

/** Plain-language render of one sweep result (real per-store counts, never fabricated). */
function _sweepResultHTML(result) {
  if (!result || typeof result !== 'object') return '';
  if (result.skipped || !result.window_days) {
    return 'Nothing to remove — your retention window is set to keep data forever '
      + '(0 days), so the sweep did not delete anything.';
  }
  const stores = Object.entries(result.by_store || {})
    .filter(([, n]) => Number(n) > 0)
    .map(([store, n]) => `${esc(store.replace(/_/g, ' '))}: ${esc(String(n))}`)
    .join(', ');
  const total = Number.isFinite(result.pruned) ? result.pruned : 0;
  if (total === 0) {
    return `Ran the sweep for data older than ${esc(String(result.window_days))} days — `
      + 'nothing was old enough to remove.';
  }
  return `Removed ${esc(String(total))} record${total === 1 ? '' : 's'} older than `
    + `${esc(String(result.window_days))} days`
    + (stores ? ` (${stores}).` : '.');
}

function _readForm(host) {
  const get = (field) => host.querySelector(`[data-as-field="${field}"]`);
  const tzEl = get('egress_timezone');
  const localeEl = get('egress_locale');
  const allowEl = get('allow_automated_accounts');
  const capEl = get('presubmit_max_apps_per_company_per_day');
  const retentionEl = get('pii_retention_days');
  const cooldownEl = get('presubmit_duplicate_cooldown_days');
  const approvalDaysEl = get('approval_timeout_days');
  const approvalSecondsEl = get('approval_wait_seconds');
  const checkIntervalEl = get('scheduler_interval_seconds');
  const body = {};
  if (tzEl) body.egress_timezone = tzEl.value.trim();
  if (localeEl) body.egress_locale = localeEl.value.trim();
  if (allowEl) body.allow_automated_accounts = !!allowEl.checked;
  if (capEl) {
    const cap = parseInt(capEl.value, 10);
    if (Number.isFinite(cap)) body.presubmit_max_apps_per_company_per_day = cap;
  }
  if (retentionEl) {
    const retention = parseInt(retentionEl.value, 10);
    if (Number.isFinite(retention)) body.pii_retention_days = retention;
  }
  if (cooldownEl) {
    const cooldown = parseInt(cooldownEl.value, 10);
    if (Number.isFinite(cooldown)) body.presubmit_duplicate_cooldown_days = cooldown;
  }
  if (approvalDaysEl) {
    const days = parseInt(approvalDaysEl.value, 10);
    if (Number.isFinite(days)) body.approval_timeout_days = days;
  }
  // Blank = leave the persisted override alone (falls back to the days setting
  // above); only send a value when the operator actually typed one.
  if (approvalSecondsEl && approvalSecondsEl.value.trim() !== '') {
    const seconds = parseFloat(approvalSecondsEl.value);
    if (Number.isFinite(seconds)) body.approval_wait_seconds = seconds;
  }
  if (checkIntervalEl) {
    const interval = parseFloat(checkIntervalEl.value);
    if (Number.isFinite(interval)) body.scheduler_interval_seconds = interval;
  }
  return body;
}

async function _save() {
  if (!_host) return;
  const btn = _host.querySelector('#as-save');
  const msg = _host.querySelector('#as-msg');
  if (btn) btn.disabled = true;
  try {
    await _put(BASE, _readForm(_host));
    if (msg) { msg.textContent = 'Saved'; msg.style.color = 'var(--fg)'; }
    _toast('Automation preferences saved');
    const { available, prefs } = await _load();
    if (available) { _prefs = prefs; }
  } catch (e) {
    if (msg) { msg.textContent = 'Failed to save'; msg.style.color = 'var(--red)'; }
    _toast(`Could not save automation preferences: ${e.message || e}`);
  } finally {
    if (btn) btn.disabled = false;
    if (msg) setTimeout(() => { msg.textContent = ''; }, 2000);
  }
}

// Same async confirm shape as applicantRemote.js's / applicantCampaignSettings.js's
// `_confirm()`: uiModule.styledConfirm with a window.confirm fallback.
async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

async function _runSweep() {
  if (!_host) return;
  const btn = _host.querySelector('#as-sweep-now');
  const msg = _host.querySelector('#as-sweep-msg');
  const resultEl = _host.querySelector('#as-sweep-result');
  const ok = await _confirm(
    'Run the data-retention sweep now? This permanently deletes any personal '
    + 'data (resume answers, EEO/diversity answers, and other application-intake '
    + 'data) older than the retention window above. This cannot be undone.',
    { confirmText: 'Delete old data', cancelText: 'Cancel', danger: true });
  if (!ok) return;
  if (btn) btn.disabled = true;
  if (msg) { msg.textContent = 'Running…'; msg.style.color = ''; }
  try {
    const result = await _post(SWEEP_URL, {});
    if (msg) { msg.textContent = ''; }
    if (resultEl) resultEl.innerHTML = _sweepResultHTML(result);
    _toast('Data-retention sweep complete');
  } catch (e) {
    if (msg) { msg.textContent = 'Sweep failed'; msg.style.color = 'var(--red)'; }
    if (resultEl) resultEl.textContent = '';
    _toast(`Could not run the data-retention sweep: ${e.message || e}`);
  } finally {
    if (btn) btn.disabled = false;
    if (msg) setTimeout(() => { msg.textContent = ''; }, 2000);
  }
}

function _wire(host) {
  const saveBtn = host.querySelector('#as-save');
  if (saveBtn) saveBtn.addEventListener('click', _save);
  const sweepBtn = host.querySelector('#as-sweep-now');
  if (sweepBtn) sweepBtn.addEventListener('click', _runSweep);
}

export async function mountApplicantAutomationSettings(host) {
  if (!host) return;
  _host = host;
  host.innerHTML = '<p style="font-size:0.85rem;opacity:0.7;">Loading automation preferences…</p>';
  const { available, prefs } = await _load();
  if (!available) {
    host.innerHTML =
      '<p style="font-size:0.85rem;opacity:0.7;">Applicant is offline — automation preferences will appear once it reconnects.</p>';
    return;
  }
  _prefs = prefs;
  host.innerHTML = _cardHTML(prefs || {});
  _wire(host);
}

// Expose for settings.js to mount lazily on tab open (mirrors
// mountApplicantCampaignSettings / mountApplicantModelLadder).
window.mountApplicantAutomationSettings = mountApplicantAutomationSettings;

export default { mountApplicantAutomationSettings };
