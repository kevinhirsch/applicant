// static/js/applicantCampaignSettings.js
//
// Campaign + discovery-source settings (issue #301) — Settings → Campaign tab.
// ADDITIVE and self-contained: it talks only to the owner-scoped front-door proxy
// (/api/applicant/campaigns/*) which proxies the engine. The engine owns all the
// logic and the safety clamps (throughput hard cap, exploration-budget range); this
// module only renders the config and posts edits back.
//
// What it surfaces per campaign:
//   * rename, archive / reactivate
//   * run mode (continuous / fixed duration / until N viable)
//   * daily throughput target (how many roles a day to work, capped engine-side)
//   * exploration budget (how much to try new sources vs. proven ones)
//   * discovery sources with their learned yield stats + a quick on/off toggle
//   * Danger zone — permanently delete the campaign (dark-engine audit item 17):
//     the engine already purges every store on delete (résumés, PII, generated
//     materials, application history, banked credentials); this just gives the
//     owner a confirmed, reachable way to trigger it.
//
// Mounted lazily by settings.js when the Campaign tab opens, into
// #ao-settings-campaign. Re-renders fresh each open so it reflects saved state.

import { esc, _toast, _fetchJSON, _post, _put } from './applicantCore.js';
import uiModule from './ui.js';

const BASE = '/api/applicant/campaigns';

const RUN_MODES = [
  ['continuous', 'Continuous (24/7)'],
  ['fixed_duration', 'Fixed duration'],
  ['until_n_viable', 'Until enough viable roles'],
];

function _runModeLabel(mode) {
  const found = RUN_MODES.find((m) => m[0] === mode);
  return found ? found[1] : (mode || 'continuous');
}

async function _loadCampaigns() {
  try {
    const data = await _fetchJSON(BASE);
    return { available: data.engine_available !== false, campaigns: data.campaigns || [] };
  } catch {
    return { available: false, campaigns: [] };
  }
}

async function _loadSources(campaignId) {
  try {
    const data = await _fetchJSON(`${BASE}/${encodeURIComponent(campaignId)}/sources`);
    return data.items || [];
  } catch {
    return [];
  }
}

function _yieldSummary(stats) {
  // The engine returns a free-form per-source yield_stats dict (e.g. postings /
  // conversions seen). Render the most useful numbers in plain language, falling
  // back to "no data yet" so a fresh source never shows a blank.
  if (!stats || typeof stats !== 'object') return 'No data yet';
  const postings = stats.postings ?? stats.found ?? stats.seen;
  const conversions = stats.conversions ?? stats.converted;
  const bits = [];
  if (postings != null) bits.push(`${esc(String(postings))} found`);
  if (conversions != null) bits.push(`${esc(String(conversions))} converted`);
  return bits.length ? bits.join(' · ') : 'No data yet';
}

function _sourceLabel(key) {
  // "jobspy:indeed" -> "Indeed", "linkedin" -> "Linkedin".
  const tail = String(key || '').split(':').pop() || String(key || '');
  return tail.charAt(0).toUpperCase() + tail.slice(1);
}

function _campaignCard(c) {
  const id = esc(c.id);
  const archived = c.active === false;
  const modeOpts = RUN_MODES.map(
    ([v, label]) =>
      `<option value="${v}"${c.run_mode === v ? ' selected' : ''}>${esc(label)}</option>`,
  ).join('');
  const throughput = Number.isFinite(c.throughput_target) ? c.throughput_target : 15;
  const budgetPct = Math.round((Number(c.exploration_budget) || 0) * 100);
  return `
    <div class="admin-card" data-campaign-id="${id}"${archived ? ' style="opacity:0.65"' : ''}>
      <h2 style="display:flex;align-items:center;gap:8px">
        <span class="cs-name-label">${esc(c.name) || '(unnamed)'}</span>
        ${archived ? '<span class="memory-badge" style="font-size:0.7rem">Archived</span>' : ''}
      </h2>
      <div class="settings-row">
        <label class="settings-label" for="cs-name-${id}">Name</label>
        <input id="cs-name-${id}" class="settings-input" type="text" value="${esc(c.name)}"
               data-cs-field="name" placeholder="Campaign name">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="cs-mode-${id}">Run mode</label>
        <select id="cs-mode-${id}" class="settings-input" data-cs-field="run_mode">${modeOpts}</select>
      </div>
      <div class="settings-row">
        <label class="settings-label" for="cs-tput-${id}">Daily target
          <span style="opacity:0.6;font-weight:normal">(roles/day; capped for safety)</span></label>
        <input id="cs-tput-${id}" class="settings-input" type="number" min="1" max="30"
               value="${esc(String(throughput))}" data-cs-field="throughput_target" style="max-width:120px">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="cs-budget-${id}">Exploration budget
          <span style="opacity:0.6;font-weight:normal">(% effort on new sources)</span></label>
        <input id="cs-budget-${id}" class="settings-input" type="number" min="0" max="100" step="5"
               value="${esc(String(budgetPct))}" data-cs-field="exploration_pct" style="max-width:120px">
      </div>
      <div class="settings-row" style="gap:8px">
        <button type="button" class="cal-btn cs-save" data-cs-id="${id}">Save changes</button>
        <button type="button" class="cal-btn cs-archive" data-cs-id="${id}" data-cs-active="${archived ? '0' : '1'}">
          ${archived ? 'Reactivate' : 'Archive'}
        </button>
      </div>
      <div class="cs-sources" data-cs-sources-for="${id}">
        <div class="admin-toggle-sub" style="margin:10px 0 6px">Discovery sources</div>
        <div class="cs-sources-list" style="font-size:0.85rem;opacity:0.7">Loading…</div>
      </div>
      <div class="cs-danger-zone" style="margin-top:14px;padding-top:10px;border-top:1px solid color-mix(in srgb, var(--color-danger, #e06c75) 30%, transparent)">
        <div class="admin-toggle-label" style="color:#e55">Danger zone</div>
        <div class="admin-toggle-sub" style="margin-bottom:8px">
          Permanently deletes this campaign and everything in it — résumés, applications,
          discovery sources, and learned criteria. This cannot be undone.
        </div>
        <button type="button" class="cal-btn cal-btn-danger cs-delete" data-cs-id="${id}"
                title="Permanently delete this campaign and purge its data">Delete this campaign</button>
      </div>
    </div>`;
}

function _renderSources(host, campaignId, items) {
  const list = host.querySelector(`[data-cs-sources-for="${CSS.escape(campaignId)}"] .cs-sources-list`);
  if (!list) return;
  if (!items.length) {
    list.innerHTML = '<span style="opacity:0.6">No sources available yet.</span>';
    return;
  }
  list.innerHTML = items
    .map((s) => {
      const key = esc(s.source_key);
      const on = s.enabled !== false;
      return `
        <label class="settings-row" style="cursor:pointer;align-items:center;gap:8px">
          <input type="checkbox" data-cs-source="${key}" ${on ? 'checked' : ''}>
          <span style="flex:1"><strong>${esc(_sourceLabel(s.source_key))}</strong>
            <span style="opacity:0.6">— ${_yieldSummary(s.yield_stats)}</span></span>
        </label>`;
    })
    .join('');
}

async function _wireSources(host, campaignId) {
  const items = await _loadSources(campaignId);
  _renderSources(host, campaignId, items);
  const container = host.querySelector(`[data-cs-sources-for="${CSS.escape(campaignId)}"]`);
  if (!container) return;
  container.querySelectorAll('input[data-cs-source]').forEach((cb) => {
    cb.addEventListener('change', async () => {
      const sourceKey = cb.getAttribute('data-cs-source');
      try {
        await _put(`${BASE}/${encodeURIComponent(campaignId)}/sources/${encodeURIComponent(sourceKey)}`, {
          enabled: cb.checked,
        });
        _toast(`${_sourceLabel(sourceKey)} ${cb.checked ? 'enabled' : 'disabled'}`);
      } catch (e) {
        cb.checked = !cb.checked; // revert on failure
        _toast(`Could not update source: ${e.message || e}`);
      }
    });
  });
}

function _readEdits(card) {
  const get = (field) => card.querySelector(`[data-cs-field="${field}"]`);
  const body = {
    name: get('name')?.value?.trim() || undefined,
    run_mode: get('run_mode')?.value || undefined,
  };
  const tput = parseInt(get('throughput_target')?.value, 10);
  if (Number.isFinite(tput)) body.throughput_target = tput;
  const pct = parseInt(get('exploration_pct')?.value, 10);
  if (Number.isFinite(pct)) body.exploration_budget = Math.max(0, Math.min(pct, 100)) / 100;
  return body;
}

async function _wireCard(host, card) {
  const id = card.getAttribute('data-campaign-id');
  card.querySelector('.cs-save')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      await _patch(`${BASE}/${encodeURIComponent(id)}`, _readEdits(card));
      _toast('Campaign updated');
      await mountApplicantCampaignSettings(host); // re-render fresh
    } catch (e) {
      _toast(`Could not save: ${e.message || e}`);
      btn.disabled = false;
    }
  });
  card.querySelector('.cs-archive')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const active = btn.getAttribute('data-cs-active') === '1';
    btn.disabled = true;
    try {
      await _patch(`${BASE}/${encodeURIComponent(id)}`, { active: !active });
      _toast(active ? 'Campaign archived' : 'Campaign reactivated');
      await mountApplicantCampaignSettings(host);
    } catch (e) {
      _toast(`Could not update: ${e.message || e}`);
      btn.disabled = false;
    }
  });
  card.querySelector('.cs-delete')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const name = card.querySelector('.cs-name-label')?.textContent?.trim() || 'this campaign';
    const ok = await _confirm(
      `Permanently delete "${name}"? Its résumés, applications, discovery sources, and learned ` +
        'criteria will be purged and cannot be recovered.',
      { confirmText: 'Delete permanently', cancelText: 'Keep campaign', danger: true },
    );
    if (!ok) return;
    btn.disabled = true;
    try {
      await _del(`${BASE}/${encodeURIComponent(id)}`);
      _toast('Campaign deleted');
      await mountApplicantCampaignSettings(host); // re-render fresh without it
    } catch (e) {
      _toast(`Could not delete campaign: ${e.message || e}`);
      btn.disabled = false;
    }
  });
  await _wireSources(host, id);
}

// PATCH convenience (applicantCore only exports _post/_put).
function _patch(url, body) {
  return _fetchJSON(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// DELETE convenience (applicantCore only exports _post/_put).
function _del(url) {
  return _fetchJSON(url, { method: 'DELETE' });
}

// Same async confirm shape as applicantVault.js's `_confirm()` / applicantRemote.js's
// `_confirm()`: uiModule.styledConfirm with a window.confirm fallback.
async function _confirm(message, opts) {
  try {
    if (uiModule.styledConfirm) return await uiModule.styledConfirm(message, opts);
  } catch { /* fall through */ }
  try { return window.confirm(message); } catch { return false; }
}

async function _wireCreate(host) {
  const btn = host.querySelector('#cs-create');
  const input = host.querySelector('#cs-create-name');
  if (!btn || !input) return;
  btn.addEventListener('click', async () => {
    const name = input.value.trim();
    if (!name) {
      _toast('Give the campaign a name first');
      return;
    }
    btn.disabled = true;
    try {
      await _post(BASE, { name });
      _toast('Campaign created');
      await mountApplicantCampaignSettings(host);
    } catch (e) {
      _toast(`Could not create campaign: ${e.message || e}`);
      btn.disabled = false;
    }
  });
}

export async function mountApplicantCampaignSettings(host) {
  if (!host) return;
  host.innerHTML = '<p style="font-size:0.85rem;opacity:0.7;">Loading campaigns…</p>';
  const { available, campaigns } = await _loadCampaigns();
  if (!available) {
    host.innerHTML =
      '<p style="font-size:0.85rem;opacity:0.7;">Applicant is offline — campaign settings will appear once it reconnects.</p>';
    return;
  }
  const createCard = `
    <div class="admin-card">
      <h2>Create a campaign</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">A campaign is one job search — its own criteria, sources, and learning.</div>
      <div class="settings-row" style="gap:8px">
        <input id="cs-create-name" class="settings-input" type="text" placeholder="e.g. Senior Backend Engineer">
        <button type="button" class="cal-btn" id="cs-create">Create</button>
      </div>
    </div>`;
  const cards = campaigns.length
    ? campaigns.map(_campaignCard).join('')
    : '<p style="font-size:0.85rem;opacity:0.7;">No campaigns yet — create one above to get started.</p>';
  host.innerHTML = createCard + cards;
  await _wireCreate(host);
  for (const card of host.querySelectorAll('[data-campaign-id]')) {
    await _wireCard(host, card);
  }
}

// Expose for settings.js to mount lazily on tab open (mirrors mountApplicantModelLadder).
window.mountApplicantCampaignSettings = mountApplicantCampaignSettings;

export default { mountApplicantCampaignSettings };
