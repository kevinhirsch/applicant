// static/js/applicantCampaignSwitcher.js
//
// Shared campaign switcher (P1-10 — multi-campaign, issue #662). One small,
// self-contained module that owns "which job search am I looking at?" across
// the front door, LIFTED from the daily-updates panel's own per-campaign
// picker (emailLibrary/applicantDigest.js `_populateCampaigns`) rather than
// rebuilt: same owner-scoped `/api/applicant/campaigns` read, same
// remembered-selection localStorage pattern, same `.memory-sort-select` kit.
//
// What it adds over the digest's private picker:
//   * a SHARED selection ('' = all searches) persisted in localStorage and
//     mirrored onto `window.__applicantActiveCampaign` — the seam the digest
//     panel already reads as its default — so Today, Tracker, and the
//     daily-updates panel land on the same search;
//   * `mountCampaignSwitcher(host)` renders the select only when there are
//     two or more searches — a single-search deployment keeps its exact
//     pre-P1-10 chrome (no dead dropdown);
//   * `filterByCampaign(items)` — the one filtering rule every surface
//     reuses: an item is kept when no search is selected, when it carries the
//     selected `campaign_id`, or when it carries NO campaign id at all
//     (deployment-level rows such as "finish setup" must never silently
//     vanish under a filter — that would hide action-required work, the
//     exact silent degradation the honesty invariants forbid).
//
// The switcher is EMBEDDED in each surface's existing header (like the
// desktop-assist controls, it has no standalone nav door) — the engine's
// `multi_campaign_switcher` dormant surface reports live and the feature
// layer's section gates off that key with no nav_ids of its own.

import { esc, _fetchJSON } from './applicantCore.js';

const CAMPAIGNS_API = '/api/applicant/campaigns';

// '' = all searches. Shared across surfaces + sessions.
const ACTIVE_CAMPAIGN_KEY = 'applicant-active-campaign';

function _read() {
  try { return localStorage.getItem(ACTIVE_CAMPAIGN_KEY) || ''; } catch (_) { return ''; }
}

export function getActiveCampaignId() {
  return _read();
}

export function setActiveCampaignId(id) {
  const val = String(id || '');
  try { localStorage.setItem(ACTIVE_CAMPAIGN_KEY, val); } catch (_) { /* no-op */ }
  // The seam the daily-updates panel already reads for its default campaign.
  try { window.__applicantActiveCampaign = val; } catch (_) { /* no-op */ }
  try {
    window.dispatchEvent(new CustomEvent('applicant-campaign-change', { detail: { id: val } }));
  } catch (_) { /* no-op */ }
}

// The one shared filtering rule (see header comment): '' keeps everything;
// otherwise keep matches AND items with no campaign id (deployment-level rows
// are never hidden by a search filter).
export function filterByCampaign(items) {
  const active = _read();
  if (!active || !Array.isArray(items)) return Array.isArray(items) ? items : [];
  return items.filter((it) => {
    const cid = it && (it.campaign_id != null ? String(it.campaign_id) : '');
    return !cid || cid === active;
  });
}

export async function loadCampaigns() {
  try {
    const data = await _fetchJSON(CAMPAIGNS_API);
    const campaigns = (data && Array.isArray(data.campaigns)) ? data.campaigns : [];
    return campaigns.filter((c) => c && c.id);
  } catch (_) {
    return [];
  }
}

// Renders the switcher into `host` (any small header slot) when the owner has
// two or more searches; leaves `host` empty otherwise. Selecting persists the
// shared choice and notifies via the 'applicant-campaign-change' window event
// (each surface re-filters its already-loaded rows — no second data path).
export async function mountCampaignSwitcher(host, opts) {
  if (!host) return null;
  const campaigns = await loadCampaigns();
  if (campaigns.length < 2) {
    host.innerHTML = '';
    return null;
  }
  const known = new Set(campaigns.map((c) => String(c.id)));
  let active = _read();
  if (active && !known.has(active)) {
    // A remembered search that no longer exists (deleted) falls back to all —
    // never a filter silently pinned to nothing.
    active = '';
    setActiveCampaignId('');
  }
  const allLabel = (opts && opts.allLabel) || 'All searches';
  host.innerHTML = `
    <select class="memory-sort-select applicant-campaign-switcher"
            title="Choose which job search to show"
            aria-label="Job search"
            style="flex:0 1 auto;min-width:0;max-width:180px;">
      <option value=""${active ? '' : ' selected'}>${esc(allLabel)}</option>
      ${campaigns.map((c) => `
        <option value="${esc(String(c.id))}"${String(c.id) === active ? ' selected' : ''}>${esc(c.name || c.id)}</option>`).join('')}
    </select>`;
  const sel = host.querySelector('select');
  sel.addEventListener('change', () => setActiveCampaignId(sel.value));
  return sel;
}

// Boot: mirror the persisted selection onto the window seam so surfaces that
// only read `window.__applicantActiveCampaign` (the digest panel's default)
// see it even before any switcher has been mounted this session.
try { window.__applicantActiveCampaign = _read(); } catch (_) { /* no-op */ }

export default {
  getActiveCampaignId,
  setActiveCampaignId,
  filterByCampaign,
  loadCampaigns,
  mountCampaignSwitcher,
};
