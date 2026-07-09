// static/js/applicantTelemetrySettings.js
//
// Settings > System > Error telemetry (P5-3): opt-in crash reporting that
// respects the product's privacy story.
//
//   * DEFAULT OFF. The toggle below starts unchecked until an operator
//     explicitly turns it on — this module never checks it for you.
//   * HARD off in local-only private mode. The banner below reads the
//     engine's own ``effective``/``local_only`` computation (GET
//     /api/applicant/setup/telemetry, proxying the engine's
//     SetupService.telemetry_status — see routes/applicant_setup_routes.py)
//     rather than deriving its own opinion, so it can never disagree with
//     what the engine will actually do.
//   * No bundled/default destination. The endpoint field is BLANK until the
//     operator supplies their own sink (self-hosted or otherwise) — there is
//     no Applicant-operated collector to silently phone home to.
//   * Redaction happens engine-side (observability/telemetry.py), not here —
//     this panel only toggles the preference; it never sees or sends a
//     payload itself.
//
// STANDALONE tab module (not a wizard-step renderer) — same shape as
// applicantAutomationSettings.js / applicantHealth.js: talks only to the
// owner-scoped front-door proxy, mounted lazily by settings.js when the
// System tab opens.

import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';

const BASE = '/api/applicant/setup/telemetry';

let _host = null;

async function _load() {
  try {
    return { available: true, status: await _fetchJSON(BASE) };
  } catch {
    return { available: false, status: null };
  }
}

function _bannerHTML(status) {
  if (!status || !status.local_only) return '';
  return `<div class="admin-toggle-sub" style="margin:6px 0 10px;padding:8px 10px;border-radius:6px;background:color-mix(in srgb, var(--color-warning,#e0a96c) 14%, transparent);">
    Local-only private mode is on, so error telemetry stays off no matter what is saved here — nothing about a crash leaves this deployment while that mode is active.
  </div>`;
}

function _cardHTML(status) {
  const enabled = !!(status && status.enabled);
  const endpoint = esc((status && status.endpoint) || '');
  const forcedOff = !!(status && status.local_only);
  const effective = !!(status && status.effective);
  return `<div class="admin-card">
    <h2><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;opacity:0.6"><path d="M12 9v4"/><path d="M12 17h.01"/><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>Error telemetry</h2>
    <div class="admin-toggle-sub" style="margin-bottom:8px">
      Off by default. If you turn this on, Applicant sends a sanitized crash signature (the error type, a scrubbed one-line message, which part of the app, the app version, and a coarse platform string) to a destination YOU configure below — never your résumé, job data, passwords, or API keys, and never to any Applicant-operated server, because there isn't one.
    </div>
    ${_bannerHTML(status)}
    <label style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
      <input type="checkbox" id="ats-enabled" data-as-field="enabled" ${enabled ? 'checked' : ''}>
      <span>Send crash reports</span>
    </label>
    <label style="display:block;font-size:12px;opacity:0.75;margin-bottom:4px;">Destination (your own server — no default)</label>
    <input type="text" id="ats-endpoint" data-as-field="endpoint" class="settings-input" style="width:100%;max-width:420px;" placeholder="https://your-own-telemetry-endpoint.example.com/ingest" value="${endpoint}">
    <div style="margin-top:10px;display:flex;align-items:center;gap:10px;">
      <button type="button" class="cal-btn" id="ats-save">Save</button>
      <span id="ats-msg" style="font-size:12px;"></span>
    </div>
    <div style="margin-top:8px;font-size:11px;opacity:0.6;">
      Currently ${effective ? 'active' : (forcedOff ? 'off (private mode)' : 'off')}.
    </div>
  </div>`;
}

function _readForm(host) {
  const enabledEl = host.querySelector('[data-as-field="enabled"]');
  const endpointEl = host.querySelector('[data-as-field="endpoint"]');
  const body = {};
  if (enabledEl) body.enabled = !!enabledEl.checked;
  if (endpointEl) body.endpoint = endpointEl.value.trim();
  return body;
}

async function _save() {
  if (!_host) return;
  const btn = _host.querySelector('#ats-save');
  const msg = _host.querySelector('#ats-msg');
  if (btn) btn.disabled = true;
  try {
    await _post(BASE, _readForm(_host));
    if (msg) { msg.textContent = 'Saved'; msg.style.color = 'var(--fg)'; }
    _toast('Telemetry preference saved');
    const { available, status } = await _load();
    if (available && _host) { _host.innerHTML = _cardHTML(status || {}); _wire(_host); }
  } catch (e) {
    if (msg) { msg.textContent = 'Failed to save'; msg.style.color = 'var(--red)'; }
    _toast(`Could not save telemetry preference: ${e.message || e}`);
  } finally {
    const freshBtn = _host && _host.querySelector('#ats-save');
    if (freshBtn) freshBtn.disabled = false;
  }
}

function _wire(host) {
  const saveBtn = host.querySelector('#ats-save');
  if (saveBtn) saveBtn.addEventListener('click', _save);
}

/**
 * Mount the Error telemetry card into `container` (a bare host div, e.g.
 * Settings -> System's `#ao-settings-telemetry`). Re-fetches fresh every
 * mount, same "always reflects the current server state" contract as
 * applicantAutomationSettings.js / applicantHealth.js.
 */
export async function mountApplicantTelemetrySettings(host) {
  if (!host) return;
  _host = host;
  host.innerHTML = '<p style="font-size:0.85rem;opacity:0.7;">Loading telemetry preference…</p>';
  const { available, status } = await _load();
  if (!available) {
    host.innerHTML =
      '<p style="font-size:0.85rem;opacity:0.7;">Applicant is offline — the telemetry preference will appear once it reconnects.</p>';
    return;
  }
  host.innerHTML = _cardHTML(status || {});
  _wire(host);
}

// Expose for settings.js to mount lazily on System-tab open (mirrors
// mountApplicantHealthPanel / mountApplicantAutomationSettings).
try { window.mountApplicantTelemetrySettings = mountApplicantTelemetrySettings; } catch { /* no-op */ }

const applicantTelemetrySettingsModule = { mountApplicantTelemetrySettings };
export default applicantTelemetrySettingsModule;
