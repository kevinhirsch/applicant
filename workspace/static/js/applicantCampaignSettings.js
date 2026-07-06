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
//   * Duplicate — clone this campaign's criteria/settings into a fresh campaign
//     under a new name (dark-engine audit item 36): the natural "same search,
//     new city" move, instead of rebuilding a similar search by hand.
//   * Download activity log — export the campaign's complete, ordered action
//     trail as a JSON file (dark-engine audit item 31): the engine already
//     builds this export; it was reachable only from an admin account before
//     now, even though every action in it belongs to the one owner of this
//     deployment.
//   * Danger zone — permanently delete the campaign (dark-engine audit item 17):
//     the engine already purges every store on delete (résumés, PII, generated
//     materials, application history, banked credentials); this just gives the
//     owner a confirmed, reachable way to trigger it.
//
// Mounted lazily by settings.js when the Campaign tab opens, into
// #ao-settings-campaign. Re-renders fresh each open so it reflects saved state.

import { esc, _toast, _fetchJSON, _post, _put, errText } from './applicantCore.js';
import uiModule from './ui.js';

const BASE = '/api/applicant/campaigns';

const RUN_MODES = [
  ['continuous', 'Continuous (24/7)'],
  ['fixed_duration', 'Fixed duration'],
  ['until_n_viable', "Until I've found enough good matches"],
];

// Mirrors the engine's own hard safety cap on daily throughput (dark-engine
// audit item 25's clamp). Surfaced in the field label itself (lens 11 #51)
// so the ceiling is visible before a user types past it, not just after.
const MAX_DAILY_TARGET = 30;

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
  if (conversions != null) bits.push(`${esc(String(conversions))} led to applications`);
  return bits.length ? bits.join(' · ') : 'No data yet';
}

// Known job-board brand names get their real capitalization; anything else
// falls back to a plain title-cased guess so an unrecognized source key never
// renders as a raw slug.
const _KNOWN_SOURCE_BRANDS = {
  linkedin: 'LinkedIn',
  ziprecruiter: 'ZipRecruiter',
  indeed: 'Indeed',
  glassdoor: 'Glassdoor',
  ashby: 'Ashby',
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  workday: 'Workday',
};

function _sourceLabel(key) {
  // "jobspy:indeed" -> "Indeed", "linkedin" -> "LinkedIn".
  const tail = String(key || '').split(':').pop() || String(key || '');
  const known = _KNOWN_SOURCE_BRANDS[tail.toLowerCase()];
  return known || (tail.charAt(0).toUpperCase() + tail.slice(1));
}

// Live-vs-sample indicator (dark-engine audit item 65). The offline lane backs
// EVERY source with a fake client that returns the exact same registry shape as a
// real job board, so without an explicit marker a user can't tell a synthetic
// "example.test" row from a real discovery result. `live` comes straight from the
// engine (GET .../sources item.live) — plain language either way, no jargon.
function _liveBadge(live) {
  return live
    ? '<span class="memory-badge" style="font-size:0.7rem;opacity:0.75">Live</span>'
    : '<span class="memory-badge" style="font-size:0.7rem;opacity:0.75" ' +
        'title="This source is returning sample data, not real job listings">Sample data</span>';
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
        <span class="memory-badge cs-dirty-badge" id="cs-dirty-${id}"
              style="font-size:0.7rem;display:none" role="status">Unsaved changes</span>
      </h2>
      <div class="admin-toggle-sub cs-scope-caption" style="margin:-6px 0 10px;opacity:0.65">
        These settings apply to this search only — not your other searches or the deployment as a whole.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="cs-name-${id}">Name
          <span style="opacity:0.6;font-weight:normal">(just for you — how this search shows up in your list)</span></label>
        <input id="cs-name-${id}" class="settings-input" type="text" value="${esc(c.name)}"
               data-cs-field="name" placeholder="Search name" maxlength="120"
               title="A label to tell this search apart from your others — doesn't affect what I search for">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="cs-mode-${id}">Run mode
          <span style="opacity:0.6;font-weight:normal">(when I stop looking for this search)</span></label>
        <select id="cs-mode-${id}" class="settings-input" data-cs-field="run_mode"
                title="Continuous: I never stop looking. Fixed duration: I stop after a set time. Until enough matches: I stop once you’ve approved enough">${modeOpts}</select>
      </div>
      <div class="settings-row">
        <label class="settings-label" for="cs-tput-${id}">Daily target
          <span style="opacity:0.6;font-weight:normal">(roles/day; up to ${MAX_DAILY_TARGET}, capped for safety)</span></label>
        <input id="cs-tput-${id}" class="settings-input" type="number" min="1" max="${MAX_DAILY_TARGET}"
               value="${esc(String(throughput))}" data-cs-field="throughput_target" style="max-width:120px">
      </div>
      <div class="admin-toggle-sub cs-tput-note" id="cs-tput-note-${id}" style="opacity:0.75;margin:-6px 0 4px;display:none;" role="status"></div>
      <div class="settings-row">
        <label class="settings-label" for="cs-budget-${id}">Trying new sources
          <span style="opacity:0.6;font-weight:normal">(% of my effort spent on unproven job boards)</span></label>
        <input id="cs-budget-${id}" class="settings-input" type="number" min="0" max="100" step="5"
               value="${esc(String(budgetPct))}" data-cs-field="exploration_pct" style="max-width:120px">
      </div>
      <div class="settings-row" style="gap:8px">
        <button type="button" class="cal-btn cs-save" data-cs-id="${id}">Save changes</button>
        <button type="button" class="cal-btn cs-archive" data-cs-id="${id}" data-cs-active="${archived ? '0' : '1'}">
          ${archived ? 'Reactivate' : 'Archive'}
        </button>
        <button type="button" class="cal-btn cs-duplicate" data-cs-id="${id}"
                title="Start a new search with this one's criteria and settings">Duplicate</button>
        <button type="button" class="cal-btn cs-audit-log" data-cs-id="${id}"
                title="Download every action taken on this search as a JSON file">Download activity log</button>
      </div>
      <div class="cs-sources" data-cs-sources-for="${id}">
        <div class="admin-toggle-sub" style="margin:10px 0 6px">Discovery sources</div>
        <div class="cs-sources-banner"></div>
        <div class="cs-sources-list" style="font-size:0.85rem;opacity:0.7">Loading…</div>
      </div>
      <div class="cs-danger-zone" style="margin-top:14px;padding-top:10px;border-top:1px solid color-mix(in srgb, var(--color-danger, #e06c75) 30%, transparent)">
        <div class="admin-toggle-label" style="color:#e55">Danger zone</div>
        <div class="admin-toggle-sub" style="margin-bottom:8px">
          Permanently deletes this search and everything in it — résumés, applications,
          discovery sources, and learned criteria. This cannot be undone.
        </div>
        <button type="button" class="cal-btn cal-btn-danger cs-delete" data-cs-id="${id}"
                title="Permanently delete this search and purge its data">Delete this search</button>
      </div>
    </div>`;
}

function _renderSources(host, campaignId, items) {
  const scope = host.querySelector(`[data-cs-sources-for="${CSS.escape(campaignId)}"]`);
  const list = scope?.querySelector('.cs-sources-list');
  const banner = scope?.querySelector('.cs-sources-banner');
  if (!list) return;
  if (banner) {
    // Every source is currently backed by sample data (dark-engine audit item 65) —
    // spell it out once above the list instead of making the user infer it from
    // per-row badges alone.
    const anyLive = items.some((s) => s.live === true);
    banner.innerHTML = items.length && !anyLive
      ? '<div class="admin-toggle-sub" style="margin-bottom:8px;opacity:0.85">' +
          'Using sample data for every source below — connect a real job board to see real listings.' +
        '</div>'
      : '';
  }
  if (!items.length) {
    list.innerHTML = '<span style="opacity:0.6">No sources available yet.</span>';
    return;
  }
  list.innerHTML = items
    .map((s) => {
      const key = esc(s.source_key);
      const on = s.enabled !== false;
      return `
        <label class="settings-row" style="cursor:pointer;align-items:center;gap:8px"
               title="On: I search ${esc(_sourceLabel(s.source_key))} for new roles. Off: I skip it — what I’ve already learned about it is kept in case you turn it back on.">
          <input type="checkbox" data-cs-source="${key}" ${on ? 'checked' : ''}>
          <span style="flex:1"><strong>${esc(_sourceLabel(s.source_key))}</strong>
            ${_liveBadge(s.live === true)}
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
        _toast(`I couldn’t update that source: ${errText(e)}`);
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
  const saveBtn = card.querySelector('.cs-save');
  // Dirty indicator (lens 11 #34): name/mode/target/exploration-budget all
  // share one explicit "Save changes" button, while the source checkboxes
  // below save instantly on change — a mixed model that isn't legible
  // without something marking "you have edits not saved yet". Any field
  // wired to the Save button flips this badge on; a successful save clears
  // it (via the fresh re-render), a failed save leaves it showing since the
  // edit is still unsaved.
  const dirtyBadge = card.querySelector(`#cs-dirty-${CSS.escape(id)}`);
  const _setDirty = (on) => {
    if (dirtyBadge) dirtyBadge.style.display = on ? '' : 'none';
  };
  card.querySelectorAll('[data-cs-field]').forEach((el) => {
    el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', () => _setDirty(true));
  });
  saveBtn?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      await _patch(`${BASE}/${encodeURIComponent(id)}`, _readEdits(card));
      _toast('Search updated');
      await mountApplicantCampaignSettings(host); // re-render fresh (clears the dirty badge too)
    } catch (e) {
      _toast(`I couldn’t save that: ${errText(e)}`);
      btn.disabled = false;
    }
  });
  // Enter-to-commit from the rename field, mirroring the chat composer's
  // create-campaign chord (micro-interactions audit #24).
  card.querySelector('[data-cs-field="name"]')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      saveBtn?.click();
    }
  });
  // Client-side clamp on the daily-throughput input so a typed-then-capped
  // value doesn't look like a silent bug once the engine's own hard cap
  // rewrites it server-side (micro-interactions audit #25).
  const tputInput = card.querySelector('[data-cs-field="throughput_target"]');
  const tputNote = card.querySelector(`#cs-tput-note-${CSS.escape(id)}`);
  tputInput?.addEventListener('change', () => {
    const raw = parseInt(tputInput.value, 10);
    if (!Number.isFinite(raw)) return;
    const min = parseInt(tputInput.min, 10) || 1;
    const max = parseInt(tputInput.max, 10) || 30;
    const clamped = Math.max(min, Math.min(raw, max));
    if (clamped !== raw) {
      tputInput.value = String(clamped);
      if (tputNote) {
        tputNote.textContent = `Capped at ${clamped} for safety.`;
        tputNote.style.display = '';
      }
    } else if (tputNote) {
      tputNote.style.display = 'none';
    }
  });
  card.querySelector('.cs-archive')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const active = btn.getAttribute('data-cs-active') === '1';
    // Archiving stops a whole job search — confirm first (weight follows
    // consequence, micro-interactions audit #41). Reactivating stays a
    // single click; it only resumes work, nothing is lost by a mis-click.
    if (active) {
      const name = card.querySelector('.cs-name-label')?.textContent?.trim() || 'this search';
      const ok = await _confirm(
        `Archive "${name}"? I’ll stop working this job search until you reactivate it.`,
        { confirmText: 'Archive', cancelText: 'Keep active' },
      );
      if (!ok) return;
    }
    btn.disabled = true;
    try {
      await _patch(`${BASE}/${encodeURIComponent(id)}`, { active: !active });
      _toast(active ? 'Search archived' : 'Search reactivated');
      await mountApplicantCampaignSettings(host);
    } catch (e) {
      _toast(`I couldn’t update that: ${errText(e)}`);
      btn.disabled = false;
    }
  });
  card.querySelector('.cs-duplicate')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const name = card.querySelector('.cs-name-label')?.textContent?.trim() || 'this search';
    const newName = (uiModule.styledPrompt
      ? await uiModule.styledPrompt(`Name the new search (a copy of "${name}").`, {
          title: 'Duplicate search',
          defaultValue: `${name} (copy)`,
          confirmText: 'Duplicate',
        })
      : window.prompt('Name the new search:', `${name} (copy)`));
    if (newName == null) return; // cancelled
    btn.disabled = true;
    try {
      await _post(`${BASE}/${encodeURIComponent(id)}/clone`, { name: newName.trim() || undefined });
      _toast('Search duplicated');
      await mountApplicantCampaignSettings(host); // re-render fresh with the new campaign
    } catch (e) {
      _toast(`I couldn’t duplicate that search: ${errText(e)}`);
      btn.disabled = false;
    }
  });
  card.querySelector('.cs-audit-log')?.addEventListener('click', () => {
    // A plain authenticated GET download (same-origin, cookie session already
    // covers it) — the proxy's Content-Disposition header does the rest, same
    // pattern as the résumé/preview PDF downloads elsewhere in this workspace.
    try {
      window.open(`${BASE}/${encodeURIComponent(id)}/audit-log/export.json`, '_blank', 'noopener');
    } catch (e) {
      _toast(`I couldn’t open the activity log: ${errText(e)}`);
    }
  });
  card.querySelector('.cs-delete')?.addEventListener('click', async (ev) => {
    const btn = ev.currentTarget;
    const name = card.querySelector('.cs-name-label')?.textContent?.trim() || 'this search';
    const ok = await _confirm(
      `Permanently delete "${name}"? Its résumés, applications, discovery sources, and learned ` +
        'criteria will be purged and cannot be recovered.',
      { confirmText: 'Delete permanently', cancelText: 'Keep search', danger: true },
    );
    if (!ok) return;
    btn.disabled = true;
    try {
      await _del(`${BASE}/${encodeURIComponent(id)}`);
      _toast('Search deleted');
      await mountApplicantCampaignSettings(host); // re-render fresh without it
    } catch (e) {
      _toast(`I couldn’t delete that search: ${errText(e)}`);
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
  const create = async () => {
    const name = input.value.trim();
    if (!name) {
      _toast('Give the search a name first');
      return;
    }
    btn.disabled = true;
    try {
      await _post(BASE, { name });
      _toast('Search created');
      await mountApplicantCampaignSettings(host);
    } catch (e) {
      _toast(`I couldn’t create that search: ${errText(e)}`);
      btn.disabled = false;
    }
  };
  btn.addEventListener('click', create);
  // Enter-to-commit, mirroring the chat composer's own create-campaign
  // chord (micro-interactions audit #24: "no Enter-to-commit, no maxlength").
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.isComposing) {
      e.preventDefault();
      create();
    }
  });
}

export async function mountApplicantCampaignSettings(host) {
  if (!host) return;
  // This panel fully re-mounts on every save/archive/duplicate/delete/create
  // (a fuller "patch the one edited card in place" refactor is the real fix
  // for micro-interactions audit #39 and is deferred — see the task report);
  // in the meantime, mark the host a live/busy-aware region (a11y-deep audit
  // #12) and preserve the reader's scroll position across the swap instead
  // of always snapping back to the top.
  host.setAttribute('aria-live', 'polite');
  host.setAttribute('aria-busy', 'true');
  const savedScrollTop = host.scrollTop;
  host.innerHTML = '<p style="font-size:0.85rem;opacity:0.7;">Loading searches…</p>';
  const { available, campaigns } = await _loadCampaigns();
  if (!available) {
    host.innerHTML =
      '<p style="font-size:0.85rem;opacity:0.7;">I can’t connect right now — your search settings will appear once I’m back.</p>';
    host.setAttribute('aria-busy', 'false');
    return;
  }
  const createCard = `
    <div class="admin-card">
      <h2>Start a search</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">Each search has its own criteria, sources, and learning.</div>
      <div class="settings-row" style="gap:8px">
        <input id="cs-create-name" class="settings-input" type="text" placeholder="e.g. Senior Backend Engineer"
               aria-label="Search name" maxlength="120">
        <button type="button" class="cal-btn" id="cs-create">Start search</button>
      </div>
    </div>`;
  const cards = campaigns.length
    ? campaigns.map(_campaignCard).join('')
    : '<p style="font-size:0.85rem;opacity:0.7;">No searches yet — start one above.</p>';
  host.innerHTML = createCard + cards;
  host.scrollTop = savedScrollTop;
  host.setAttribute('aria-busy', 'false');
  await _wireCreate(host);
  for (const card of host.querySelectorAll('[data-campaign-id]')) {
    await _wireCard(host, card);
  }
}

// Expose for settings.js to mount lazily on tab open (mirrors mountApplicantModelLadder).
window.mountApplicantCampaignSettings = mountApplicantCampaignSettings;

export default { mountApplicantCampaignSettings };
