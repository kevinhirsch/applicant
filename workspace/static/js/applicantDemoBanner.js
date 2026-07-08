// static/js/applicantDemoBanner.js
//
// Seeded-demo mode banner + one-click "Clear demo data" (P0-2).
//
// When the engine runs under DEMO_MODE and a synthetic dataset is loaded, this
// module shows a persistent, unmistakable "Demo data" banner across the top of
// the app and offers a single control that wipes the seeded data with no
// residue. It exists so every screenshot / demo / fixture is honestly labelled
// as synthetic, and so the demo state is reversible from the white-labeled
// front door — not just from an operator shell.
//
// ADDITIVE and self-contained: it self-boots on DOM ready, talks to the engine
// ONLY through the owner-scoped workspace proxy at /api/applicant/demo (never
// the engine directly), and degrades to invisible whenever the engine isn't in
// demo mode (the proxy reports demo_active:false) or is unreachable. Styling
// reuses the workspace design system (.cal-btn / .cal-btn-primary).
//
// Node-importability: every browser-global reference is guarded, so the pure
// render helper (demoBannerHTML) can be imported and asserted headlessly by the
// JS test suite (workspace/tests/js/*).

import { esc, _fetchJSON, _post, _toast } from './applicantCore.js';

const API = '/api/applicant/demo';
const BANNER_ID = 'applicant-demo-banner';

// ── pure render helper (unit-tested headlessly) ─────────────────────────────
//
// Given the proxy's status payload, return the banner's inner HTML — or '' when
// there is nothing to show (not in demo mode / no seeded data). Kept pure (no
// DOM, no I/O) so it slices cleanly into the headless JS suite.
export function demoBannerHTML(status) {
  if (!status || status.demo_active !== true) return '';
  const counts = (status && typeof status.counts === 'object' && status.counts) || {};
  const apps = Number(counts.applications) || 0;
  // A short, honest summary of what's loaded — never a fabricated number.
  const detail = apps > 0
    ? `${apps} sample application${apps === 1 ? '' : 's'} and related activity are loaded.`
    : 'Sample data is loaded.';
  return `
    <span class="applicant-demo-banner__dot" aria-hidden="true"></span>
    <span class="applicant-demo-banner__text">
      <strong>Demo data</strong> — ${esc(detail)} Nothing here is real.
    </span>
    <button type="button" class="cal-btn cal-btn-primary" id="applicant-demo-clear">
      Clear demo data
    </button>`;
}

// ── DOM plumbing (guarded; only runs in the browser) ────────────────────────

function _ensureHost() {
  if (typeof document === 'undefined') return null;
  let host = document.getElementById(BANNER_ID);
  if (!host) {
    host = document.createElement('div');
    host.id = BANNER_ID;
    host.setAttribute('role', 'status');
    host.hidden = true;
    // Prepend so the strip sits above all app chrome.
    if (document.body) document.body.insertBefore(host, document.body.firstChild);
  }
  return host;
}

function _render(host, status) {
  if (!host) return;
  const html = demoBannerHTML(status);
  if (!html) {
    host.hidden = true;
    host.innerHTML = '';
    if (typeof document !== 'undefined' && document.body) {
      document.body.classList.remove('has-applicant-demo-banner');
    }
    return;
  }
  host.innerHTML = html;
  host.hidden = false;
  if (typeof document !== 'undefined' && document.body) {
    document.body.classList.add('has-applicant-demo-banner');
  }
  const btn = host.querySelector('#applicant-demo-clear');
  if (btn) btn.addEventListener('click', clearDemoData, { once: true });
}

export async function refreshDemoBanner() {
  const host = _ensureHost();
  if (!host) return;
  let status;
  try {
    status = await _fetchJSON(`${API}/status`);
  } catch {
    _render(host, null); // never let a status failure block the app
    return;
  }
  _render(host, status);
}

export async function clearDemoData() {
  let result;
  try {
    result = await _post(`${API}/clear`, {});
  } catch {
    _toast('Could not clear demo data — the engine may be unreachable.');
    return;
  }
  if (result && result.cleared) {
    _toast('Demo data cleared.');
    // The seeded surfaces must re-render empty — a reload is the simplest,
    // most honest way to refresh every one of them at once.
    if (typeof window !== 'undefined' && window.location && typeof window.location.reload === 'function') {
      window.location.reload();
    } else {
      const host = _ensureHost();
      _render(host, { demo_active: false });
    }
  } else {
    _toast('Demo data is not loaded, or the engine is not in demo mode.');
    refreshDemoBanner();
  }
}

function _boot() {
  refreshDemoBanner();
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _boot);
  } else {
    _boot();
  }
}

const applicantDemoBannerModule = { demoBannerHTML, refreshDemoBanner, clearDemoData };
try {
  if (typeof window !== 'undefined') window.applicantDemoBannerModule = applicantDemoBannerModule;
} catch { /* no-op */ }

export default applicantDemoBannerModule;
