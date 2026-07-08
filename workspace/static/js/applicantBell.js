// static/js/applicantBell.js
//
// P0-3 (P0-3b) — the TOP-BAR NOTIFICATION BELL, the THIRD of the shell's three
// notification surfaces. The other two already exist and are reused, never
// rebuilt: the rail's waiting-on-you area (applicantRail.js) and transient
// toasts (ui.js showToast). The bell is a NEW LENS over the SAME owner-scoped
// backing the rail's waiting area and the Portal both read —
//   GET /api/applicant/portal/pending
// — so it introduces NO new engine endpoint and duplicates NO Portal/Today
// logic. It shows the pending COUNT on the bell and a DROPDOWN of the SAME
// pending items; clicking an item opens Today (the one-at-a-time run-through)
// via the SAME `window.openApplicantToday` launcher the rail uses, where the
// item is actually acted on.
//
// "Acting on an item clears it from bell, rail, AND portal at once" is real
// because all three read that one backing feed: when any of them resolves an
// item, the Portal's authoritative `_setBadge` dispatches the shared
// `applicant:pending-changed` document event, which the bell AND the rail both
// listen for and re-read immediately — no surface waits out its own poll to
// catch up, and no surface keeps a private copy of "what's pending."
//
// The bell is owner-only by construction: `/pending` is gated by
// `require_engine_owner`, so a non-owner (or a down/gated engine) makes the
// fetch throw and the whole bell stays hidden — no dead UI, matching the
// shell's "sections appear as they become real" principle.

import { esc, _fetchJSON } from './applicantCore.js';

// The shared cross-surface refresh signal. The Portal's `_setBadge` dispatches
// it on every count change (resolve / snooze / bulk-approve / poll); the rail
// and this bell both listen so a resolution anywhere lands everywhere at once.
export const PENDING_CHANGED_EVENT = 'applicant:pending-changed';

const PORTAL_API = '/api/applicant/portal';
const POLL_MS = 45000;
const MAX_DROPDOWN_ROWS = 8;

let _mounted = false;
let _pollStop = null;
let _open = false;

// ── Pure helpers (unit-tested headlessly via the JS harness) ─────────────────

// The compact bell-badge label: '' when nothing is pending (badge hidden),
// the count otherwise, capped at '99+'. Never throws on a junk count.
export function _bellCountLabel(count) {
  const n = Number(count) || 0;
  if (n <= 0) return '';
  return n > 99 ? '99+' : String(n);
}

// Build the dropdown's item rows from the SAME pending feed the rail/Portal
// read. Each row is a menu button carrying its action id + campaign so the
// click handler can hand off to Today; the list is capped (a "+N more" footer
// points the rest at Today) so a huge queue never builds an unbounded menu.
// Never throws on a malformed row — an item with no title falls back to a
// calm generic line, mirroring the rail's waiting-area copy.
export function _bellItemRows(items, cap) {
  const list = Array.isArray(items) ? items : [];
  const max = Number(cap) > 0 ? Number(cap) : MAX_DROPDOWN_ROWS;
  if (!list.length) return '';
  const shown = list.slice(0, max);
  const rows = shown.map((it) => {
    const item = (it && typeof it === 'object') ? it : {};
    const title = esc(item.title || 'Needs your attention');
    const where = item.campaign_name
      ? `<span class="applicant-bell-where">${esc(item.campaign_name)}</span>`
      : '';
    const id = esc(String(item.id == null ? '' : item.id));
    return `<button type="button" class="applicant-bell-item" role="menuitem" data-action-id="${id}">`
      + `<span class="applicant-bell-item-title">${title}</span>${where}</button>`;
  }).join('');
  const extra = list.length - shown.length;
  const more = extra > 0
    ? `<div class="applicant-bell-more">+${extra} more in Today</div>`
    : '';
  return rows + more;
}

// ── DOM handles ──────────────────────────────────────────────────────────────

function _wrap() { return document.getElementById('applicant-bell-wrap'); }
function _btn() { return document.getElementById('applicant-bell-btn'); }
function _badge() { return document.getElementById('applicant-bell-badge'); }
function _dropdown() { return document.getElementById('applicant-bell-dropdown'); }

// ── Open Today (the run-through where items are acted on) ─────────────────────
//
// Reuses the SAME launcher the rail's waiting gadget uses — the bell never
// invents a second path into a surface, and never rebuilds Today's
// resolve/answer/snooze controls.
function _openToday() {
  try {
    if (typeof window.openApplicantToday === 'function') return window.openApplicantToday();
  } catch { /* fall through */ }
  try {
    if (window.applicantPortalModule && typeof window.applicantPortalModule.openApplicantPortal === 'function') {
      return window.applicantPortalModule.openApplicantPortal();
    }
  } catch { /* fall through */ }
  return undefined;
}

// ── Rendering ────────────────────────────────────────────────────────────────

function _setBadge(count) {
  const badge = _badge();
  const btn = _btn();
  if (!badge) return;
  const label = _bellCountLabel(count);
  badge.textContent = label;
  badge.style.display = label ? '' : 'none';
  if (btn) {
    const n = Number(count) || 0;
    btn.setAttribute(
      'aria-label',
      n > 0
        ? `Notifications — ${n} thing${n === 1 ? '' : 's'} waiting on you`
        : 'Notifications — nothing waiting on you',
    );
  }
}

function _renderDropdown(items, count) {
  const dd = _dropdown();
  if (!dd) return;
  const n = Number(count) || (Array.isArray(items) ? items.length : 0);
  if (!n) {
    dd.innerHTML = '<div class="applicant-bell-empty">Nothing needs you right now.</div>';
    return;
  }
  dd.innerHTML = `
    <div class="applicant-bell-head">Waiting on you</div>
    <div class="applicant-bell-list">${_bellItemRows(items, MAX_DROPDOWN_ROWS)}</div>`;
  // Every item routes to Today, where it is actually handled — one delegated
  // handler instead of a listener per row.
  dd.querySelectorAll('.applicant-bell-item').forEach((row) => {
    row.addEventListener('click', () => { _close(); _openToday(); });
  });
  const more = dd.querySelector('.applicant-bell-more');
  if (more) {
    more.style.cursor = 'pointer';
    more.addEventListener('click', () => { _close(); _openToday(); });
  }
}

// ── Open / close ─────────────────────────────────────────────────────────────

function _close() {
  const dd = _dropdown();
  const btn = _btn();
  _open = false;
  if (dd) dd.classList.remove('open');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function _openMenu() {
  const dd = _dropdown();
  const btn = _btn();
  _open = true;
  if (dd) dd.classList.add('open');
  if (btn) btn.setAttribute('aria-expanded', 'true');
}

function _toggle() {
  if (_open) _close();
  else _openMenu();
}

// ── Refresh (the shared backing read) ────────────────────────────────────────

async function _refresh() {
  const wrap = _wrap();
  if (!wrap) return;
  let data;
  try {
    data = await _fetchJSON(`${PORTAL_API}/pending`);
  } catch {
    // Not the engine owner, or the engine is unreachable — no bell at all.
    wrap.style.display = 'none';
    _close();
    return;
  }
  if (!data || data.engine_available === false || data.gated === true) {
    // Engine down or setup unfinished: the bell has nothing honest to show yet.
    wrap.style.display = 'none';
    _close();
    return;
  }
  wrap.style.display = '';
  const items = Array.isArray(data.items) ? data.items : [];
  const count = Number(data.count) || items.length;
  _setBadge(count);
  _renderDropdown(items, count);
}

// ── Boot / wiring ────────────────────────────────────────────────────────────

export function mountApplicantBell() {
  if (_mounted) return;
  const wrap = _wrap();
  const btn = _btn();
  if (!wrap || !btn) return;
  _mounted = true;

  btn.addEventListener('click', (e) => { e.stopPropagation(); _toggle(); });
  // Click-away and Escape close the dropdown (matches the export menu / model
  // picker behaviour).
  document.addEventListener('click', (e) => {
    if (!_open) return;
    if (wrap.contains(e.target)) return;
    _close();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && _open) _close(); });

  // The shared cross-surface signal: a resolve anywhere re-reads the one feed.
  document.addEventListener(PENDING_CHANGED_EVENT, () => { _refresh(); });

  // Slow, visibility-aware poll so a backgrounded tab doesn't hammer the proxy.
  if (_pollStop) _pollStop();
  let timer = null;
  const tick = () => { _refresh(); };
  const start = () => { if (timer == null) timer = setInterval(tick, POLL_MS); };
  const stop = () => { if (timer != null) { clearInterval(timer); timer = null; } };
  const onVis = () => { if (document.visibilityState === 'visible') { tick(); start(); } else stop(); };
  document.addEventListener('visibilitychange', onVis);
  tick();
  if (document.visibilityState === 'visible') start();
  _pollStop = () => { stop(); document.removeEventListener('visibilitychange', onVis); };
}

function _boot() {
  if (_wrap()) { mountApplicantBell(); return; }
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    if (_wrap()) { mountApplicantBell(); clearInterval(iv); }
    else if (tries > 20) clearInterval(iv);
  }, 500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantBellModule = { mountApplicantBell, refresh: _refresh };
try { window.applicantBellModule = applicantBellModule; } catch { /* no-op */ }
try { window.mountApplicantBell = mountApplicantBell; } catch { /* no-op */ }

export default applicantBellModule;
