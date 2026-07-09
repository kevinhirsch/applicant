// static/js/applicantHealth.js
//
// Honest health panel (P1-3, issue #655): the engine's boot-time capability
// self-report — postgres / résumé renderer / browser / orchestrator, each
// real-vs-stub with a plain-language label and actionable fix copy — proxied
// read-only through routes/applicant_health_routes.py
// (GET /api/applicant/health/capabilities). ONE data source, TWO renders:
//
//   • mountApplicantHealthPanel(container) — the full panel for
//     Settings -> System: every capability, its status, and (when degraded)
//     the concrete fix. Mounted lazily on tab open via
//     window.mountApplicantHealthPanel, the SAME lazy-mount convention
//     settings.js's mountRelocatedSetupStep already uses for
//     applicantCampaignSettings.js / applicantModelLadder.js /
//     applicantAutomationSettings.js.
//   • renderApplicantPortalHealthBanner(host) — a compact banner mounted into
//     the Pending Portal (the nav's "Today" home base — see
//     applicantPortal.js's own header comment: "the workspace's primary
//     home-base surface"). Renders NOTHING when everything is real, ONE
//     designed banner when the engine is unreachable (never blank/broken
//     sections), and a plain-language banner naming which LOAD-BEARING
//     capabilities are degraded otherwise — never the always-real
//     orchestrator alone, since a shim-vs-dbos difference doesn't block the
//     search from running.
//
// Honesty invariant (H-series): the absence of a check must never render as
// a check — an unreachable engine or a gated read shows its own designed
// state, never a silently-empty "everything's fine".

import uiModule from './ui.js';
import { esc, _fetchJSON, loadingHTML, errorHTML, wireRetry } from './applicantCore.js';

const API = '/api/applicant/health/capabilities';

// The redacted diagnostic-bundle command (P5-1, "Support machinery"). This
// needs to run on the deploy HOST (it shells out to `docker compose`), which
// is why this is a copyable command rather than a live "Download" button —
// the containers this panel itself runs inside have no Docker access to
// collect from. Every secret-bearing value is redacted by the script itself
// before anything is written (scripts/lib/diagnostic_redact.py); see
// docs/support.md for the full picture (issue templates, community chat).
const _DIAGNOSTIC_BUNDLE_CMD = 'bash scripts/diagnostic-bundle.sh';

// ── Settings -> System: the full panel ──────────────────────────────────────

function _statusPillHTML(status) {
  const ok = status === 'real';
  const color = ok ? 'var(--color-success,#4caf50)' : 'var(--color-danger,#e06c6c)';
  const label = ok ? 'Working' : 'Degraded';
  return `<span style="display:inline-flex;align-items:center;gap:4px;font-size:10px;font-weight:600;padding:2px 8px;border-radius:8px;white-space:nowrap;background:color-mix(in srgb, ${color} 18%, transparent);color:${color};">${label}</span>`;
}

function _capabilityRowHTML(cap) {
  const degraded = cap && cap.status !== 'real';
  const requiredTag = cap && cap.load_bearing
    ? ' <span style="opacity:0.55;font-weight:400;font-size:11px;">(required)</span>'
    : '';
  return `<div class="admin-card" style="padding:10px 12px;margin-bottom:8px;${degraded ? 'border-color:color-mix(in srgb, var(--color-danger,#e06c6c) 45%, var(--border));' : ''}">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;">
      <div style="font-weight:600;">${esc((cap && (cap.label || cap.name)) || '')}${requiredTag}</div>
      ${_statusPillHTML(cap && cap.status)}
    </div>
    ${cap && cap.detail ? `<div style="margin-top:4px;font-size:12px;opacity:0.75;">${esc(cap.detail)}</div>` : ''}
    ${degraded && cap && cap.fix ? `<div style="margin-top:8px;font-size:12px;line-height:1.5;padding:8px 10px;border-radius:6px;background:color-mix(in srgb, var(--color-warning,#e0a96c) 14%, transparent);">${esc(cap.fix)}</div>` : ''}
  </div>`;
}

function _panelSummaryHTML(data, caps) {
  if (data && data.all_real === true) {
    return `<div style="font-size:12px;opacity:0.8;margin-bottom:10px;">Everything the assistant needs is wired up and running for real.</div>`;
  }
  const degraded = Array.isArray(data && data.degraded) ? data.degraded.length : 0;
  const total = caps.length;
  return `<div style="font-size:12px;margin-bottom:10px;color:var(--color-danger,#e06c6c);">${degraded} of ${total} capabilit${degraded === 1 ? 'y is' : 'ies are'} running in a degraded/stub mode — see the fix below each one.</div>`;
}

// Running engine version (P3-5, release engineering). Renders nothing when the
// payload carries none (older engine / degraded read) — the absence of a
// version must never be dressed up as one.
function _versionLineHTML(data) {
  const v = data && data.version;
  if (!v) return '';
  return `<div style="font-size:11px;opacity:0.55;margin-bottom:6px;">Engine v${esc(String(v))}</div>`;
}

function _panelBodyHTML(data) {
  const caps = Array.isArray(data && data.capabilities) ? data.capabilities : [];
  if (!caps.length) {
    return `${_versionLineHTML(data)}<div style="font-size:12px;opacity:0.7;padding:8px 2px;">Nothing to report yet.</div>`;
  }
  return _versionLineHTML(data) + _panelSummaryHTML(data, caps) + caps.map(_capabilityRowHTML).join('');
}

async function _renderPanelInto(body) {
  if (!body) return;
  body.innerHTML = loadingHTML('Checking engine health…');
  try {
    const data = await _fetchJSON(API);
    if (data && data.engine_available === false) {
      body.innerHTML = errorHTML('Can’t reach the assistant right now — health status is unavailable.');
      wireRetry(body, () => _renderPanelInto(body));
      return;
    }
    if (data && data.gated === true) {
      body.innerHTML = `<div style="font-size:12px;opacity:0.75;padding:4px 2px;">${esc(data.message || 'Finish setup to see engine health.')}</div>`;
      return;
    }
    body.innerHTML = _panelBodyHTML(data || {});
  } catch (err) {
    body.innerHTML = errorHTML((err && err.message) || 'Something went wrong.');
    wireRetry(body, () => _renderPanelInto(body));
  }
}

function _copyDiagnosticCommand() {
  try {
    if (uiModule && typeof uiModule.copyToClipboard === 'function') {
      uiModule.copyToClipboard(_DIAGNOSTIC_BUNDLE_CMD);
      return;
    }
  } catch { /* fall through */ }
  try {
    navigator.clipboard.writeText(_DIAGNOSTIC_BUNDLE_CMD);
    if (uiModule && typeof uiModule.showToast === 'function') uiModule.showToast('Copied.');
  } catch { /* best-effort only */ }
}

// Filing a bug or support request? Point at the redacted diagnostic-bundle
// command (P5-1) — a copyable command, not a live download, since it needs
// Docker access this container doesn't have (see the module docstring above).
function _diagnosticsCardHTML() {
  return `<div class="admin-card" style="margin-top:12px;">
    <h2><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;opacity:0.6"><path d="M9 12l2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>Diagnostics</h2>
    <div class="admin-toggle-sub" style="margin-bottom:8px">Filing a bug or a support request? Run this on the machine hosting Applicant — it collects version/status/config/logs into one archive, with every secret redacted automatically before anything is written.</div>
    <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
      <code style="flex:1;min-width:200px;padding:6px 10px;border-radius:6px;background:color-mix(in srgb, var(--fg,#000) 6%, transparent);font-size:12px;">${esc(_DIAGNOSTIC_BUNDLE_CMD)}</code>
      <button type="button" class="cal-btn" id="applicant-health-copy-diag">Copy command</button>
    </div>
  </div>`;
}

/**
 * Mount the full health panel into `container` (a bare host div, e.g.
 * Settings -> System's `#ao-settings-health`). Re-fetches fresh every mount
 * (mirrors applicantCampaignSettings.js's own "re-render fresh each open"
 * contract) so the panel always reflects the current engine state.
 */
export async function mountApplicantHealthPanel(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="admin-card">
      <h2><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:5px;opacity:0.6"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 2-3 4"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>Engine health</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">What the assistant actually has wired up — every silent stub is named here, with the fix.</div>
      <div id="applicant-health-body"></div>
    </div>
    ${_diagnosticsCardHTML()}`;
  await _renderPanelInto(container.querySelector('#applicant-health-body'));
  const copyBtn = container.querySelector('#applicant-health-copy-diag');
  if (copyBtn) copyBtn.addEventListener('click', _copyDiagnosticCommand);
}

// ── Portal ("Today" home base): the compact banner ─────────────────────────

function _openSystemSettings() {
  try {
    if (window.adminModule && typeof window.adminModule.open === 'function') {
      window.adminModule.open('system');
      return;
    }
  } catch { /* fall through */ }
  try { window.uiModule && window.uiModule.showToast && window.uiModule.showToast('Open Settings → System to see engine health'); } catch { /* no-op */ }
}

function _bannerShellHTML(title, sub, tone) {
  const accent = tone === 'danger' ? 'var(--color-danger,#e06c6c)' : 'var(--color-warning,#e0a96c)';
  return `<div class="admin-card" id="applicant-health-banner" style="padding:10px 12px;margin:0 2px 10px;border-color:color-mix(in srgb, ${accent} 45%, var(--border));">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;">
      <div style="min-width:0;">
        <div style="font-weight:600;font-size:13px;">${esc(title)}</div>
        <div style="font-size:12px;opacity:0.78;margin-top:2px;">${esc(sub)}</div>
      </div>
      <button type="button" class="cal-btn" data-role="open-system">See details</button>
    </div>
  </div>`;
}

function _degradedNames(caps, names) {
  const byName = {};
  (Array.isArray(caps) ? caps : []).forEach((c) => { if (c && c.name) byName[c.name] = c; });
  return (Array.isArray(names) ? names : [])
    .map((n) => (byName[n] && byName[n].label) || n)
    .filter(Boolean);
}

/**
 * Render (or clear) the compact health banner into `host`. Renders NOTHING
 * when the engine is reachable and nothing load-bearing is degraded — this
 * is a supplementary strip, not the primary Portal content, so it never
 * blocks or delays the pending queue it sits above.
 */
export async function renderApplicantPortalHealthBanner(host) {
  if (!host) return;
  try {
    const data = await _fetchJSON(API);
    if (data && data.engine_available === false) {
      // Single designed banner for "can't reach the assistant" — never a
      // blank/broken section (P1-3 DoD).
      host.innerHTML = _bannerShellHTML(
        'Can’t check engine health right now',
        'I’ve lost my connection — I’ll keep trying.',
        'warning',
      );
      const btn = host.querySelector('[data-role="open-system"]');
      if (btn) btn.addEventListener('click', _openSystemSettings);
      return;
    }
    if (data && data.gated === true) {
      host.innerHTML = ''; // setup isn't finished yet — the gated Portal state already covers this
      return;
    }
    const loadBearing = Array.isArray(data && data.load_bearing_degraded) ? data.load_bearing_degraded : [];
    if (!loadBearing.length) {
      host.innerHTML = '';
      return;
    }
    const names = _degradedNames(data.capabilities, loadBearing);
    const list = names.length ? names.join(', ') : 'part of the engine';
    host.innerHTML = _bannerShellHTML(
      'Something the search depends on is degraded',
      `${list} — running in a stub/degraded mode right now.`,
      'danger',
    );
    const btn = host.querySelector('[data-role="open-system"]');
    if (btn) btn.addEventListener('click', _openSystemSettings);
  } catch {
    // Best-effort supplementary strip — never break Portal's own load over this.
    host.innerHTML = '';
  }
}

try { window.mountApplicantHealthPanel = mountApplicantHealthPanel; } catch { /* no-op */ }

const applicantHealthModule = { mountApplicantHealthPanel, renderApplicantPortalHealthBanner };
export default applicantHealthModule;
