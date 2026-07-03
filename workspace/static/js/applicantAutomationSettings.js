// static/js/applicantAutomationSettings.js
//
// Settings > Automation (dark-engine audit items 82/84/85/87/88) — the FIRST cut
// of a generic engine-preferences tab. The dark-engine audit found ~20 engine
// config knobs that were env-only with zero Settings UI ("the workspace Settings
// surface mounts only four wizard renderers ... plus the campaign and
// model-ladder tabs — there is no generic engine-preferences tab",
// 08_engine_dark_matrix.md §B8). This module builds that tab; later phases add
// more cards here rather than inventing another tab.
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
//
// STANDALONE tab module (not a wizard-step renderer) — same shape as
// applicantCampaignSettings.js / applicantModelLadder.js: talks only to the
// owner-scoped front-door proxy (/api/applicant/setup/automation), which proxies
// the engine's SetupService-backed config store. Mounted lazily by settings.js
// when the Automation tab opens; re-renders fresh each open so it reflects the
// latest saved state.

import { esc, _toast, _fetchJSON, _put } from './applicantCore.js';

const BASE = '/api/applicant/setup/automation';

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
    </div>
    <div class="settings-row" style="gap:8px">
      <button type="button" class="cal-btn cal-btn-primary" id="as-save">Save changes</button>
      <span id="as-msg" class="admin-toggle-sub"></span>
    </div>`;
}

function _readForm(host) {
  const get = (field) => host.querySelector(`[data-as-field="${field}"]`);
  const tzEl = get('egress_timezone');
  const localeEl = get('egress_locale');
  const allowEl = get('allow_automated_accounts');
  const capEl = get('presubmit_max_apps_per_company_per_day');
  const retentionEl = get('pii_retention_days');
  const cooldownEl = get('presubmit_duplicate_cooldown_days');
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

function _wire(host) {
  const saveBtn = host.querySelector('#as-save');
  if (saveBtn) saveBtn.addEventListener('click', _save);
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
