// static/js/applicantNav.js
//
// SINGLE SOURCE OF TRUTH for the Applicant job-search navigation.
//
// The front door has two nav surfaces that show the same destinations:
//   - the collapsed icon rail (`#icon-rail`), shown when the sidebar is narrow;
//   - the wide sidebar tools list (`#tools-section`), shown when expanded.
// They used to be two hand-maintained blocks of markup in index.html that
// drifted apart (different items, different labels, different order — the "7
// nav disagreements"). This module owns ONE ordered NAV array and renders BOTH
// surfaces from it, emitting the EXACT element ids the rest of the app already
// binds to (feature-gating in app.js `refreshApplicantFeatures`, the launcher
// wiring in each applicant* module, the `_railToolMap` delegation in app.js).
// Because both surfaces come from the same array they CANNOT diverge again, and
// a new destination is a one-line edit here instead of two blocks of markup.
//
// Scope: this renderer owns ONLY the job-search destination region of each
// surface. It never touches the native scaffolding around it — search / new
// chat / delete session / the dynamic chat+documents indicators / the sessions,
// email and models sections / the settings gear / the chat-unification new-chat
// launchers. Those stay as static markup in index.html; renderNav fills the two
// mount points (`#applicant-rail-nav`, `#applicant-sidebar-nav`) between them.
//
// The ids emitted here are the same ids `applicant_features.APPLICANT_SECTIONS`
// lists in its `nav_ids` — keep the two in lockstep. A gated section whose
// nav_id is NOT emitted here would fail OPEN (its locked control would be
// clickable), so `test_applicant_nav_single_source.py` asserts every gated
// nav_id is present in this array.

// ── icon path fragments (the inner <path>/<rect>/… of each destination's SVG,
//    reused verbatim from the pre-existing rail buttons so the icons are
//    pixel-identical to what shipped) ─────────────────────────────────────────
const ICON = {
  today:    '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
  tracker:  '<rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="10" rx="1"/><rect x="17" y="4" width="4" height="7" rx="1"/>',
  results:  '<path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/>',
  activity: '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
  documents:'<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h4"/>',
  gallery:  '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
  profile:  '<path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/>',
  email:    '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
  calendar: '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
  chat:     '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  compare:  '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>',
  runlog:   '<line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>',
  trust:    '<path d="M12 2 4 5v6c0 5.25 3.4 9.74 8 11 4.6-1.26 8-5.75 8-11V5z"/><path d="M9 12l2 2 4-4"/>',
  update:   '<path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7"/><polyline points="8 12 12 16 16 12"/><line x1="12" y1="3" x2="12" y2="16"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  theme:    '<circle cx="13.5" cy="6.5" r=".5" fill="currentColor"/><circle cx="17.5" cy="10.5" r=".5" fill="currentColor"/><circle cx="8.5" cy="7.5" r=".5" fill="currentColor"/><circle cx="6.5" cy="12.5" r=".5" fill="currentColor"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z"/>',
};

// ── the ONE ordered navigation model ────────────────────────────────────────
//
// Each entry is a group (Today · My Job Search · Applications · Profile · Inbox
// · Calendar · Chat · [spacer] · Settings). Groups with one item render as a
// single destination; the multi-item groups (My Job Search, Applications)
// render their members individually in 2a — Pass 2b collapses each into a
// single tabbed host without changing this data's shape.
//
// Per-item fields:
//   rail   id of the icon-rail button (icon only + tooltip).
//   side   id of the sidebar list-item (icon + visible label); null = rail-only.
//   label  the ONE canonical name for this destination (sidebar visible text).
//   title  tooltip (title + aria-label). The rich, voice-audited copy is kept
//          verbatim from the shipped buttons so the copy pass is preserved.
//   icon   key into ICON above.
//   delegate  (optional) id whose .click() the SIDEBAR item forwards to, for
//          destinations whose own module only wires the rail id (Tracker,
//          Results, Activity) or whose sidebar door is the settings gear.
const NAV = [
  { group: 'today', items: [
    { rail: 'rail-portal', side: 'tool-portal-btn', label: 'Today', icon: 'today', title: 'Pending — everything that needs your attention, across all your job searches' },
  ] },
  { group: 'search', items: [
    { rail: 'rail-tracker', side: 'tool-tracker-btn', label: 'Tracker', icon: 'tracker', title: 'Tracker — where each application stands', delegate: 'rail-tracker' },
    { rail: 'rail-results', side: 'tool-results-btn', label: 'Results', icon: 'results', title: "Results — how your applications are doing and what's working", delegate: 'rail-results' },
    { rail: 'rail-activity', side: 'tool-activity-btn', label: 'Activity', icon: 'activity', title: "Activity — a live feed of what I'm doing", delegate: 'rail-activity' },
  ] },
  { group: 'applications', items: [
    // sideExtra keeps the sidebar Library's inline "+ new document" button
    // (library-new-doc-btn — wired in app.js, styled in style.css) that lived
    // inside the old tool-library-btn list-item.
    { rail: 'rail-archive', side: 'tool-library-btn', label: 'Documents', icon: 'documents', title: 'Documents — your resumes, cover letters, and application files',
      sideExtra: '<button type="button" class="list-item-plus-btn" id="library-new-doc-btn" title="New document"><svg class="list-item-plus-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="width:11px;height:11px;"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg><span class="list-item-plus-label">new</span></button>' },
    { rail: 'rail-applicant-gallery', side: 'tool-applicant-gallery-btn', label: 'Gallery', icon: 'gallery', title: 'Application Gallery — screenshots and materials from my work' },
  ] },
  { group: 'profile', items: [
    { rail: 'rail-memory', side: 'tool-memory-btn', label: 'Profile', icon: 'profile', title: 'Profile — the details I use to apply for you' },
  ] },
  { group: 'inbox', items: [
    { rail: 'rail-email', side: 'tool-email-btn', label: 'Daily updates', icon: 'email', title: 'Daily updates — the roles I flagged for you today' },
  ] },
  { group: 'calendar', items: [
    { rail: 'rail-calendar', side: 'tool-calendar-btn', label: 'Calendar', icon: 'calendar', title: 'Calendar' },
  ] },
  { group: 'chat', items: [
    { rail: 'rail-assistant', side: 'tool-assistant-btn', label: 'Chat', icon: 'chat', title: 'Job Assistant — ask about your applications and what needs your attention' },
  ] },
  // Secondary utilities. They keep the canonical `rail: null` (so they stay OUT
  // of the reconciled PRIMARY rail order the single-source test pins) but each
  // now also carries a `railId` (S1-6): renderNav emits a collapsed-rail twin
  // for it too, so a user with the sidebar collapsed can still reach Compare /
  // Run log / Trust instead of the rail silently dropping them. The twins are
  // wired by app.js's `_railToolMap` (railId -> the sidebar `side` id), the same
  // delegation the other rail icons use. Names are disambiguated from the
  // primary nav: the live feed is "Activity" (tool-activity-btn) while the
  // history + run-controls + update surface here is "Run log" (tool-debug-btn).
  { group: 'utilities', items: [
    { rail: null, side: 'tool-compare-btn', railId: 'rail-applicant-compare', label: 'Compare', icon: 'compare', title: 'Compare — put two models or drafts side by side' },
    { rail: null, side: 'tool-debug-btn', railId: 'rail-debug', label: 'Run log', icon: 'runlog', title: 'Run log — application history, run controls, and updates' },
    // Themes — pulled out of Settings onto the sidebar so the look & colors are a
    // one-click destination. Both doors open the same picker (#theme-modal): the
    // sidebar item forwards to the hidden #tool-theme-btn via `delegate`, and the
    // collapsed-rail twin #rail-theme is wired to it in app.js `_railToolMap`.
    { rail: null, side: 'tool-theme-nav-btn', railId: 'rail-theme', label: 'Themes', icon: 'theme', title: 'Themes — change the look and colors', delegate: 'tool-theme-btn' },
  ] },
  { spacer: true },
  { group: 'bottom', items: [
    // Update is a rail-only utility (no sidebar twin); it stays gated on its own
    // `rail-update` id in applicant_features.
    { rail: 'rail-update', side: null, label: 'Update', icon: 'update', title: 'Update Applicant' },
    // Settings: the rail button keeps its existing "expand the sidebar" behavior
    // (wired in app.js); the sidebar item opens Settings via the existing gear.
    { rail: 'rail-settings', side: 'tool-settings-btn', label: 'Settings', icon: 'settings', title: 'Settings', delegate: 'user-bar-settings' },
  ] },
];

function _railButton(item) {
  // A primary destination emits under `item.rail`; a secondary utility twin
  // (S1-6) under `item.railId` (Compare/Run log/Trust — deliberately not `rail`
  // so it stays out of the single-source PRIMARY rail order).
  const railId = item.rail || item.railId;
  return (
    `<button type="button" class="icon-rail-btn" id="${railId}" title="${item.title}" aria-label="${item.title}">` +
    `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICON[item.icon]}</svg>` +
    `</button>`
  );
}

function _sidebarItem(item) {
  return (
    `<div class="list-item" id="${item.side}" role="button" tabindex="0" title="${item.title}">` +
    `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.5;">${ICON[item.icon]}</svg>` +
    `<span class="grow">${item.label}</span>` +
    (item.sideExtra || '') +
    `</div>`
  );
}

let _rendered = false;

/**
 * Render both nav surfaces from the NAV array. Idempotent — the first call
 * wins; later calls (a second app.js boot pass, a re-import) are no-ops so the
 * launcher wiring the applicant* modules attach to these ids is never torn
 * down and re-created out from under them.
 */
export function renderNav() {
  if (_rendered) return;
  const railMount = document.getElementById('applicant-rail-nav');
  const sideMount = document.getElementById('applicant-sidebar-nav');
  if (!railMount && !sideMount) return; // shell markup not present (e.g. a test page)

  const railHTML = [];
  const sideHTML = [];
  let firstGroup = true;
  for (const group of NAV) {
    if (group.spacer) {
      // Pins the bottom cluster (Update · Settings) to the foot of the rail.
      // (`#applicant-rail-nav` is display:contents, so this is a real flex
      //  child of `.icon-rail`.) The sidebar list needs no spacer.
      railHTML.push('<div class="rail-nav-spacer" style="flex:1 1 auto"></div>');
      continue;
    }
    // Group separator in the rail only (decision: rail uses separators, no
    // captions — matches the existing `.rail-separator`). The very first group
    // needs no leading separator.
    if (!firstGroup && group.group !== 'bottom') {
      railHTML.push('<div class="rail-separator"></div>');
    }
    firstGroup = false;
    for (const item of group.items) {
      // A primary destination (`rail`) OR a secondary utility twin (`railId`,
      // S1-6) both emit a rail button; `rail` also feeds the single-source
      // order test, `railId` deliberately does not (secondary, wired via
      // app.js `_railToolMap`).
      if (item.rail || item.railId) railHTML.push(_railButton(item));
      if (item.side) sideHTML.push(_sidebarItem(item));
    }
  }

  if (railMount) railMount.innerHTML = railHTML.join('');
  if (sideMount) sideMount.innerHTML = sideHTML.join('');
  _rendered = true;
  _wireDelegates();
}

/**
 * Wire the sidebar items whose destination module does not itself wire the
 * sidebar id (Tracker/Results/Activity only wire their rail button; the
 * Settings sidebar door forwards to the gear). Everything else is wired by its
 * own module (Portal/Chat/Gallery launcher polls) or by app.js's `_railToolMap`
 * (Documents/Profile/Calendar/Daily-updates), so we must NOT double-wire those.
 */
function _wireDelegates() {
  for (const group of NAV) {
    if (!group.items) continue;
    for (const item of group.items) {
      if (!item.delegate || !item.side) continue;
      const sideEl = document.getElementById(item.side);
      if (!sideEl || sideEl._applicantNavWired) continue;
      sideEl._applicantNavWired = true;
      const forward = () => {
        const target = document.getElementById(item.delegate);
        if (target) target.click();
      };
      sideEl.addEventListener('click', forward);
      sideEl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          forward();
        }
      });
    }
  }
}

const applicantNavModule = { renderNav, NAV };
try { window.applicantNavModule = applicantNavModule; } catch (_) { /* no-op */ }

// Self-boot: render as early as this module evaluates (its <script> tag sits
// before app.js), so every launcher id exists before app.js's boot body wires
// them by getElementById and before the applicant* modules' launcher polls run.
// app.js also calls renderNav() before refreshApplicantFeatures() as a
// belt-and-suspenders ordering guarantee; the idempotent guard makes that a
// no-op.
try { renderNav(); } catch (_) { /* non-fatal — the shell may not be present yet */ }

export default applicantNavModule;
