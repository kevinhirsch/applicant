// static/js/applicantAutomationSettings.js
//
// Settings > Automation (dark-engine audit items
// 82/83/84/85/86/87/88/89/90/91/92/93/94/95/96/97/98/99/100/101/102/103/104/105/106/107)
// — a generic engine-preferences tab. The dark-engine audit found ~20 engine config knobs
// that were env-only with zero Settings UI ("the workspace Settings surface
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
//   * Application quality (item 91) — the minimum share of a form's fields
//     Applicant must be able to fill before offering an application for
//     submit rather than flagging it for review; (items 97/98) the
//     work-authorization eligibility filter and the max listing age, both
//     scam/mismatch guards on which postings even enter the pipeline.
//   * Assistant memory (item 99) — whether memory/skills writes the agent
//     proposes auto-apply or wait for your review, plus the character
//     budgets that cap how much of that memory rides along in every prompt.
//   * AI routing (item 102) — whether the smart model router prefers an
//     online local endpoint over a cloud one (the master on/off switch and
//     live routing status live on the model-ladder tab, item 74; this is
//     just the policy). Kept in this same save mechanism rather than
//     duplicating a second GET/PUT wiring on the ladder tab.
//   * Advanced (items 105/106/107) — the context-compression token
//     threshold, how many consecutive failed loop ticks trigger a stall
//     alert, and the experimental plan-as-data pre-fill planner flag.
//   * Automation sandbox (item 92) — which sandbox Applicant automates in
//     (local container vs a native Windows VM) and the stealth persona.
//   * Browser engine, advanced (item 93) — the browser ALL outbound
//     automation routes through, and its channel.
//   * Assistant tools (item 94) — the assistant/loop tool-autonomy master
//     switches (per-tool detail lives on the Tools tab).
//   * Documents (items 95/104) — company-research enrichment for cover
//     letters, and resume render fidelity.
//   * Desktop assist (item 96) — the backend/capture-mode/approval-posture
//     for background desktop control (click/type/scroll), confined to the
//     sandbox/takeover surface.
//   * Proactive updates (item 100) — cadence toggles for the memory-curation
//     nudge, periodic campaign status pushes, and the "still blocked on
//     essentials" reminder.
//   * Automation network (item 101) — the discovery-crawler proxy list; also
//     where the residential-egress mode/attestation/proxy URL (item 89) live,
//     as a companion network setting.
//   * Live takeover appearance (item 103) — the desktop environment and
//     remote-view technology used for the one-click live-takeover session.
//   * Captcha handling (item 83) — human hand-off (default, safe) vs. avoid
//     vs. farming interactive challenges to a paid third-party solving
//     service; a plain-language warning that the service option is a paid
//     external dependency that may conflict with some sites' terms of
//     service, and an explicit opt-in. The solver API key is a SECRET: it is
//     sealed in the engine's credential vault and this card never receives it
//     back from the server — only whether one is already saved.
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

/** A `<select>` styled like every other `.settings-input` control, wired for
 * `_readForm` via `data-as-field` (same convention as the text/number/checkbox
 * inputs below). `options` is `[value, label]` pairs; `current` picks the
 * `selected` one. Shared by every new SELECT-style knob added below so each
 * is a one-liner instead of a hand-rolled `<option>` list. */
function _selectHTML(id, field, options, current) {
  const opts = options
    .map(
      ([v, label]) =>
        `<option value="${esc(v)}"${current === v ? ' selected' : ''}>${esc(label)}</option>`,
    )
    .join('');
  return `<select id="${id}" class="settings-input" data-as-field="${field}" style="max-width:260px">${opts}</select>`;
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
  const fillRateFloor = Number.isFinite(prefs.ats_match_rate_floor)
    ? prefs.ats_match_rate_floor
    : 0.2;
  const eligibilityEnabled = prefs.presubmit_eligibility_enabled !== false;
  const maxListingAgeDays = Number.isFinite(prefs.presubmit_max_listing_age_days)
    ? prefs.presubmit_max_listing_age_days
    : 90;
  const memoryWriteApproval = prefs.memory_write_approval !== false;
  const skillsWriteApproval = prefs.skills_write_approval !== false;
  const memoryMaxChars = Number.isFinite(prefs.memory_max_chars)
    ? prefs.memory_max_chars
    : 8000;
  const userMaxChars = Number.isFinite(prefs.user_max_chars) ? prefs.user_max_chars : 4000;
  const preferLocal = prefs.llm_smart_routing_prefer_local !== false;
  const compressThreshold = Number.isFinite(prefs.context_compress_threshold)
    ? prefs.context_compress_threshold
    : 64000;
  const failureAlertThreshold = Number.isFinite(prefs.loop_failure_alert_threshold)
    ? prefs.loop_failure_alert_threshold
    : 3;
  const usePlanner = !!prefs.prefill_use_planner;
  const sandboxBackend = prefs.sandbox_backend || 'local';
  const stealthPersona = prefs.stealth_persona || '';
  const browserEngine = prefs.browser_engine || 'camoufox';
  const browserChannel = prefs.browser_channel || 'chrome';
  const chatTools = prefs.chat_tools || 'off';
  const loopTools = prefs.loop_tools || 'off';
  const materialResearchEnabled = !!prefs.material_research_enabled;
  const resumeRender = prefs.resume_render || 'auto';
  const cuaBackend = prefs.computer_use_backend || 'noop';
  const cuaMode = prefs.computer_use_mode || 'som';
  const cuaApprovals = prefs.computer_use_approvals || 'manual';
  const curationSchedule = prefs.curation_schedule || 'off';
  const statusUpdateSchedule = prefs.status_update_schedule || 'off';
  const essentialsNudgeSchedule = prefs.essentials_nudge_schedule || 'off';
  const discoveryProxiesText = String(prefs.discovery_proxies || '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
    .join('\n');
  const takeoverDesktop = prefs.takeover_desktop || 'cinnamon';
  const remoteViewBackend = prefs.remote_view_backend || 'webtop';
  const captchaStrategy = prefs.captcha_strategy || 'human';
  const captchaService = prefs.captcha_service || 'capsolver';
  const captchaKeyConfigured = !!prefs.captcha_api_key_configured;
  const egressMode = prefs.egress_mode || 'direct';
  const egressResidential = !!prefs.egress_residential;
  const egressProxyUrl = esc(prefs.egress_proxy_url || '');
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
    <div class="admin-card">
      <h2>Application quality</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Guards on which postings Applicant applies to and which finished
        applications it offers you to submit.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-fill-floor">Minimum form-fill rate before flagging for review (0-1)</label>
        <input id="as-fill-floor" class="settings-input" type="number" min="0" max="1" step="0.05"
               value="${esc(String(fillRateFloor))}" data-as-field="ats_match_rate_floor"
               style="max-width:120px">
      </div>
      <div class="admin-toggle-sub" style="margin:2px 0 10px;opacity:0.7;">
        If Applicant can't fill at least this share of a form's fields, it sets the
        application aside for you to review instead of offering it for submit.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-listing-age">Skip postings older than (days)</label>
        <input id="as-listing-age" class="settings-input" type="number" min="0" step="1"
               value="${esc(String(maxListingAgeDays))}" data-as-field="presubmit_max_listing_age_days"
               style="max-width:120px">
      </div>
      <h2 style="display:flex;align-items:center;gap:6px;margin-top:10px;">
        Filter out postings you're not eligible for
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-eligibility">
          <input type="checkbox" id="as-eligibility" data-as-field="presubmit_eligibility_enabled" ${eligibilityEnabled ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub">
        When on, Applicant skips postings whose work-authorization, sponsorship,
        or clearance requirements don't match what you told it about yourself.
      </div>
    </div>
    <div class="admin-card">
      <h2>Assistant memory</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        How the assistant handles things it learns about you, and how much of
        that memory it keeps in mind on every turn.
      </div>
      <h2 style="display:flex;align-items:center;gap:6px;font-size:1em;">
        Review memory updates before they're saved
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-memory-approval">
          <input type="checkbox" id="as-memory-approval" data-as-field="memory_write_approval" ${memoryWriteApproval ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        When off, non-sensitive memory the assistant proposes is applied
        automatically instead of waiting for your approval.
      </div>
      <h2 style="display:flex;align-items:center;gap:6px;font-size:1em;">
        Review skill updates before they're saved
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-skills-approval">
          <input type="checkbox" id="as-skills-approval" data-as-field="skills_write_approval" ${skillsWriteApproval ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        When off, skills the assistant proposes are saved automatically
        instead of waiting for your approval.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-memory-chars">Memory budget (characters)</label>
        <input id="as-memory-chars" class="settings-input" type="number" min="1" step="100"
               value="${esc(String(memoryMaxChars))}" data-as-field="memory_max_chars"
               style="max-width:120px">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-user-chars">Preferences budget (characters)</label>
        <input id="as-user-chars" class="settings-input" type="number" min="1" step="100"
               value="${esc(String(userMaxChars))}" data-as-field="user_max_chars"
               style="max-width:120px">
      </div>
      <div class="admin-toggle-sub" style="opacity:0.7;">
        How much learned context (environment lessons / your preferences) rides
        along in every prompt. Higher budgets give the assistant more context at
        the cost of a longer prompt.
      </div>
    </div>
    <div class="admin-card">
      <h2 style="display:flex;align-items:center;gap:6px;">
        Prefer a local model when one is online
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-prefer-local">
          <input type="checkbox" id="as-prefer-local" data-as-field="llm_smart_routing_prefer_local" ${preferLocal ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub">
        When smart routing picks a model for a task, prefer an online local
        endpoint over a cloud one (keeps requests on your own hardware when
        possible). The on/off switch for smart routing itself, and which
        endpoint is actually serving requests right now, are on the model
        ladder tab.
      </div>
    </div>
    <div class="admin-card">
      <h2>Automation sandbox</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Which sandbox Applicant automates in, and the browser-fingerprint persona
        it presents there. Proxmox connection details are collected on the Sandbox
        setup step; this only picks which backend and persona are active.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-sandbox-backend">Sandbox backend</label>
        ${_selectHTML(
          'as-sandbox-backend',
          'sandbox_backend',
          [
            ['local', 'Local container sandbox'],
            ['proxmox-windows', 'Native Windows VM (Proxmox)'],
          ],
          sandboxBackend,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-stealth-persona">Stealth persona</label>
        ${_selectHTML(
          'as-stealth-persona',
          'stealth_persona',
          [
            ['', 'Auto (match the sandbox backend)'],
            ['linux', 'Linux (spoofed identity)'],
            ['native', 'Native (real browser identity)'],
          ],
          stealthPersona,
        )}
      </div>
    </div>
    <div class="admin-card">
      <h2>Browser engine (advanced)</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        The browser ALL outbound automation routes through. The anti-detect
        engine (the default) injects its own coherent fingerprint; the Chromium
        engine drives a real Chrome/Chromium browser and is required for the
        native Windows sandbox.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-browser-engine">Browser engine</label>
        ${_selectHTML(
          'as-browser-engine',
          'browser_engine',
          [
            ['camoufox', 'Anti-detect (default)'],
            ['chromium', 'Chromium (patchright + real Chrome)'],
          ],
          browserEngine,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-browser-channel">Browser channel</label>
        ${_selectHTML(
          'as-browser-channel',
          'browser_channel',
          [
            ['chrome', 'Google Chrome'],
            ['chromium', 'Chromium'],
          ],
          browserChannel,
        )}
      </div>
      <div class="admin-toggle-sub" style="opacity:0.7;">
        The browser channel only applies when the browser engine above is set to
        Chromium.
      </div>
    </div>
    <div class="admin-card">
      <h2>Assistant tools</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Let Applicant call its own tools (remember a fact, save a playbook, a
        bounded desktop action) instead of only replying in a single pass. Writes
        always wait for your review and the same safety stop-boundary applies
        either way.
      </div>
      <h2 style="display:flex;align-items:center;gap:6px;font-size:1em;">
        Let the assistant use tools while it works
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-chat-tools">
          <input type="checkbox" id="as-chat-tools" data-as-field="chat_tools" ${chatTools === 'auto' ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <h2 style="display:flex;align-items:center;gap:6px;font-size:1em;">
        Let the background loop use tools while it works
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-loop-tools">
          <input type="checkbox" id="as-loop-tools" data-as-field="loop_tools" ${loopTools === 'auto' ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
    </div>
    <div class="admin-card">
      <h2 style="display:flex;align-items:center;gap:6px;">
        Enrich cover letters with company research
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-material-research">
          <input type="checkbox" id="as-material-research" data-as-field="material_research_enabled" ${materialResearchEnabled ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        When on, cover-letter generation may fold in capped, cached company-research
        facts so letters can reference company-specific detail.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-resume-render">Resume render fidelity</label>
        ${_selectHTML(
          'as-resume-render',
          'resume_render',
          [
            ['auto', 'Auto (real render when available, else a plain fallback)'],
            ['on', 'Always render (force the real high-fidelity render)'],
            ['off', 'Never render (always use the plain fallback)'],
          ],
          resumeRender,
        )}
      </div>
    </div>
    <div class="admin-card">
      <h2>Desktop assist</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Lets Applicant control the sandboxed desktop directly (click/type/scroll)
        for situations the browser automation alone can't handle, confined to the
        automation sandbox / takeover surface.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-cua-backend">Desktop-assist backend</label>
        ${_selectHTML(
          'as-cua-backend',
          'computer_use_backend',
          [
            ['noop', 'Off (no side effects)'],
            ['cua', 'On (real driver)'],
          ],
          cuaBackend,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-cua-mode">Capture mode</label>
        ${_selectHTML(
          'as-cua-mode',
          'computer_use_mode',
          [
            ['som', 'Screenshot with numbered elements'],
            ['ax', 'Accessibility-tree text only'],
          ],
          cuaMode,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-cua-approvals">Approval posture</label>
        ${_selectHTML(
          'as-cua-approvals',
          'computer_use_approvals',
          [
            ['manual', 'Review each action'],
            ['session', 'One approval per takeover session'],
          ],
          cuaApprovals,
        )}
      </div>
    </div>
    <div class="admin-card">
      <h2>Proactive updates</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        How often Applicant reaches out on its own with memory-curation
        suggestions, campaign status updates, and reminders about what's still
        blocking automated applying.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-curation-schedule">Suggest memory/skill updates</label>
        ${_selectHTML(
          'as-curation-schedule',
          'curation_schedule',
          [
            ['off', 'Off'],
            ['daily', 'Daily'],
          ],
          curationSchedule,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-status-update-schedule">Send campaign status updates</label>
        ${_selectHTML(
          'as-status-update-schedule',
          'status_update_schedule',
          [
            ['off', 'Off'],
            ['daily', 'Daily'],
          ],
          statusUpdateSchedule,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-essentials-nudge-schedule">Remind me what's blocking applying</label>
        ${_selectHTML(
          'as-essentials-nudge-schedule',
          'essentials_nudge_schedule',
          [
            ['off', 'Off'],
            ['daily', 'Daily'],
          ],
          essentialsNudgeSchedule,
        )}
      </div>
    </div>
    <div class="admin-card">
      <h2>Automation network</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Optional proxy list Applicant's discovery crawler routes through instead of
        a direct connection. Leave blank to use a direct connection.
      </div>
      <div class="settings-row" style="align-items:flex-start;">
        <label class="settings-label" for="as-discovery-proxies">Discovery proxies</label>
        <textarea id="as-discovery-proxies" class="settings-input" data-as-field="discovery_proxies"
                  placeholder="One proxy URL per line, e.g. http://user:pass@proxy.example.com:8080"
                  rows="3" style="max-width:420px;">${esc(discoveryProxiesText)}</textarea>
      </div>
      <h2 style="font-size:1em;margin-top:14px;">Residential egress</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Route Applicant's browser automation itself (not just discovery) through a
        residential proxy instead of this server's own connection — useful when
        this server's connection would otherwise look like a datacenter to the
        sites Applicant applies on. Leave on "Direct" unless you have a
        residential proxy to point at.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-egress-mode">Egress mode</label>
        ${_selectHTML(
          'as-egress-mode',
          'egress_mode',
          [
            ['direct', 'Direct (this server\'s own connection)'],
            ['residential-proxy', 'Residential proxy'],
          ],
          egressMode,
        )}
      </div>
      <div class="settings-row" style="align-items:flex-start;">
        <label class="settings-label" for="as-egress-proxy-url">Proxy URL</label>
        <input id="as-egress-proxy-url" class="settings-input" type="text" value="${egressProxyUrl}"
               placeholder="http://user:pass@residential-proxy.example.com:8080"
               data-as-field="egress_proxy_url" style="max-width:420px;">
      </div>
      <h2 style="display:flex;align-items:center;gap:6px;font-size:1em;margin-top:6px;">
        This proxy is a genuine residential connection
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-egress-residential">
          <input type="checkbox" id="as-egress-residential" data-as-field="egress_residential" ${egressResidential ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub">
        Your explicit confirmation that the proxy above is a real residential
        exit, not a datacenter one. When egress mode is set to "Residential
        proxy" but this isn't checked, Applicant refuses to launch rather than
        risk exiting through a datacenter IP.
      </div>
    </div>
    <div class="admin-card">
      <h2>Captcha handling</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        What Applicant does when it hits a CAPTCHA while filling out an
        application.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-captcha-strategy">Strategy</label>
        ${_selectHTML(
          'as-captcha-strategy',
          'captcha_strategy',
          [
            ['human', 'Hand off to me (default, safest)'],
            ['avoid', 'Avoid where possible, otherwise hand off to me'],
            ['service', 'Solve automatically using a paid third-party service'],
          ],
          captchaStrategy,
        )}
      </div>
      <div class="admin-toggle-sub" style="margin:2px 0 10px;padding:8px;border-radius:6px;background:color-mix(in srgb, var(--red, #c0392b) 12%, transparent);">
        <strong>Before choosing "Solve automatically":</strong> this sends the
        CAPTCHA challenge to a paid third-party solving service you configure
        below, using an API key and account you set up and pay for yourself.
        Using an automated CAPTCHA-solving service may violate the terms of
        service of some job sites. Only turn this on if you understand and
        accept that risk. The default ("Hand off to me") never does this.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-captcha-service">Solving service</label>
        ${_selectHTML(
          'as-captcha-service',
          'captcha_service',
          [
            ['capsolver', 'CapSolver'],
            ['2captcha', '2Captcha'],
            ['anticaptcha', 'Anti-Captcha'],
          ],
          captchaService,
        )}
      </div>
      <div class="settings-row" style="align-items:flex-start;">
        <label class="settings-label" for="as-captcha-api-key">Service API key</label>
        <input id="as-captcha-api-key" class="settings-input" type="password" value=""
               placeholder="${captchaKeyConfigured ? 'Saved — leave blank to keep it' : 'Not set'}"
               autocomplete="new-password" data-as-field="captcha_api_key" style="max-width:280px;">
      </div>
      <div class="admin-toggle-sub" style="opacity:0.7;">
        ${captchaKeyConfigured
          ? 'A key is already saved and is never shown here again. Type a new one to replace it, or leave this blank to keep the saved key.'
          : 'Only used when the strategy above is "Solve automatically." Stored in the secure credential vault, never in plain settings, and never shown back to you once saved.'}
      </div>
    </div>
    <div class="admin-card">
      <h2>Live takeover appearance</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        The desktop environment and remote-view technology used for the one-click
        live-takeover session when Applicant hits a CAPTCHA, verification step, or
        final submit.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-takeover-desktop">Desktop environment</label>
        ${_selectHTML(
          'as-takeover-desktop',
          'takeover_desktop',
          [
            ['cinnamon', 'Cinnamon'],
            ['xfce', 'Xfce'],
            ['gnome', 'GNOME'],
            ['pantheon', 'Pantheon'],
          ],
          takeoverDesktop,
        )}
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-remote-view-backend">Remote-view technology</label>
        ${_selectHTML(
          'as-remote-view-backend',
          'remote_view_backend',
          [
            ['webtop', 'Full desktop (Webtop)'],
            ['neko', 'Browser only (Neko)'],
          ],
          remoteViewBackend,
        )}
      </div>
    </div>
    <div class="admin-card">
      <h2>Advanced</h2>
      <div class="admin-toggle-sub" style="margin-bottom:8px">
        Lower-level tuning knobs. The defaults work for most setups.
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-compress-threshold">Compress conversation above (tokens, 0 = never)</label>
        <input id="as-compress-threshold" class="settings-input" type="number" min="0" step="1000"
               value="${esc(String(compressThreshold))}" data-as-field="context_compress_threshold"
               style="max-width:140px">
      </div>
      <div class="settings-row">
        <label class="settings-label" for="as-failure-threshold">Alert after this many failed checks in a row</label>
        <input id="as-failure-threshold" class="settings-input" type="number" min="1" step="1"
               value="${esc(String(failureAlertThreshold))}" data-as-field="loop_failure_alert_threshold"
               style="max-width:120px">
      </div>
      <h2 style="display:flex;align-items:center;gap:6px;font-size:1em;margin-top:10px;">
        Experimental: plan-first form filling
        <span style="flex:1"></span>
        <label class="admin-switch" for="as-use-planner">
          <input type="checkbox" id="as-use-planner" data-as-field="prefill_use_planner" ${usePlanner ? 'checked' : ''}>
          <span class="admin-slider"></span>
        </label>
      </h2>
      <div class="admin-toggle-sub">
        Switches form-filling to an experimental planner that lays out each
        page's steps before acting, instead of deciding one action at a time.
        Off by default; the same review-before-submit safeguards still apply
        either way.
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
  const fillFloorEl = get('ats_match_rate_floor');
  const eligibilityEl = get('presubmit_eligibility_enabled');
  const listingAgeEl = get('presubmit_max_listing_age_days');
  const memoryApprovalEl = get('memory_write_approval');
  const skillsApprovalEl = get('skills_write_approval');
  const memoryCharsEl = get('memory_max_chars');
  const userCharsEl = get('user_max_chars');
  const preferLocalEl = get('llm_smart_routing_prefer_local');
  const compressThresholdEl = get('context_compress_threshold');
  const failureThresholdEl = get('loop_failure_alert_threshold');
  const usePlannerEl = get('prefill_use_planner');
  const sandboxBackendEl = get('sandbox_backend');
  const stealthPersonaEl = get('stealth_persona');
  const browserEngineEl = get('browser_engine');
  const browserChannelEl = get('browser_channel');
  const chatToolsEl = get('chat_tools');
  const loopToolsEl = get('loop_tools');
  const materialResearchEl = get('material_research_enabled');
  const resumeRenderEl = get('resume_render');
  const cuaBackendEl = get('computer_use_backend');
  const cuaModeEl = get('computer_use_mode');
  const cuaApprovalsEl = get('computer_use_approvals');
  const curationScheduleEl = get('curation_schedule');
  const statusUpdateScheduleEl = get('status_update_schedule');
  const essentialsNudgeScheduleEl = get('essentials_nudge_schedule');
  const discoveryProxiesEl = get('discovery_proxies');
  const takeoverDesktopEl = get('takeover_desktop');
  const remoteViewBackendEl = get('remote_view_backend');
  const captchaStrategyEl = get('captcha_strategy');
  const captchaServiceEl = get('captcha_service');
  const captchaApiKeyEl = get('captcha_api_key');
  const egressModeEl = get('egress_mode');
  const egressResidentialEl = get('egress_residential');
  const egressProxyUrlEl = get('egress_proxy_url');
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
  if (fillFloorEl) {
    const floor = parseFloat(fillFloorEl.value);
    if (Number.isFinite(floor)) body.ats_match_rate_floor = floor;
  }
  if (eligibilityEl) body.presubmit_eligibility_enabled = !!eligibilityEl.checked;
  if (listingAgeEl) {
    const age = parseInt(listingAgeEl.value, 10);
    if (Number.isFinite(age)) body.presubmit_max_listing_age_days = age;
  }
  if (memoryApprovalEl) body.memory_write_approval = !!memoryApprovalEl.checked;
  if (skillsApprovalEl) body.skills_write_approval = !!skillsApprovalEl.checked;
  if (memoryCharsEl) {
    const chars = parseInt(memoryCharsEl.value, 10);
    if (Number.isFinite(chars)) body.memory_max_chars = chars;
  }
  if (userCharsEl) {
    const chars = parseInt(userCharsEl.value, 10);
    if (Number.isFinite(chars)) body.user_max_chars = chars;
  }
  if (preferLocalEl) body.llm_smart_routing_prefer_local = !!preferLocalEl.checked;
  if (compressThresholdEl) {
    const threshold = parseInt(compressThresholdEl.value, 10);
    if (Number.isFinite(threshold)) body.context_compress_threshold = threshold;
  }
  if (failureThresholdEl) {
    const threshold = parseInt(failureThresholdEl.value, 10);
    if (Number.isFinite(threshold)) body.loop_failure_alert_threshold = threshold;
  }
  if (usePlannerEl) body.prefill_use_planner = !!usePlannerEl.checked;
  if (sandboxBackendEl) body.sandbox_backend = sandboxBackendEl.value;
  if (stealthPersonaEl) body.stealth_persona = stealthPersonaEl.value;
  if (browserEngineEl) body.browser_engine = browserEngineEl.value;
  if (browserChannelEl) body.browser_channel = browserChannelEl.value;
  // chat_tools / loop_tools render as plain bool toggles ("Let the assistant /
  // loop use tools") but the engine field is the string "off"/"auto".
  if (chatToolsEl) body.chat_tools = chatToolsEl.checked ? 'auto' : 'off';
  if (loopToolsEl) body.loop_tools = loopToolsEl.checked ? 'auto' : 'off';
  if (materialResearchEl) body.material_research_enabled = !!materialResearchEl.checked;
  if (resumeRenderEl) body.resume_render = resumeRenderEl.value;
  if (cuaBackendEl) body.computer_use_backend = cuaBackendEl.value;
  if (cuaModeEl) body.computer_use_mode = cuaModeEl.value;
  if (cuaApprovalsEl) body.computer_use_approvals = cuaApprovalsEl.value;
  if (curationScheduleEl) body.curation_schedule = curationScheduleEl.value;
  if (statusUpdateScheduleEl) body.status_update_schedule = statusUpdateScheduleEl.value;
  if (essentialsNudgeScheduleEl) {
    body.essentials_nudge_schedule = essentialsNudgeScheduleEl.value;
  }
  if (discoveryProxiesEl) {
    // Parse the textarea (one proxy per line, commas also accepted) into a
    // list, then join back into the comma-separated string the engine's
    // DISCOVERY_PROXIES-shaped field persists (matches config.py's own format).
    const proxies = discoveryProxiesEl.value
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    body.discovery_proxies = proxies.join(',');
  }
  if (takeoverDesktopEl) body.takeover_desktop = takeoverDesktopEl.value;
  if (remoteViewBackendEl) body.remote_view_backend = remoteViewBackendEl.value;
  if (captchaStrategyEl) body.captcha_strategy = captchaStrategyEl.value;
  if (captchaServiceEl) body.captcha_service = captchaServiceEl.value;
  // SECRET: only send a new key when the operator actually typed one. This
  // field never carries the saved value back down (the GET response only
  // ever surfaces `captcha_api_key_configured`, a boolean), so an untouched
  // blank input here means "keep whatever is already vaulted" -- omitting
  // the field entirely rather than sending an empty string that would wipe it.
  if (captchaApiKeyEl && captchaApiKeyEl.value.trim() !== '') {
    body.captcha_api_key = captchaApiKeyEl.value.trim();
  }
  if (egressModeEl) body.egress_mode = egressModeEl.value;
  if (egressResidentialEl) body.egress_residential = !!egressResidentialEl.checked;
  if (egressProxyUrlEl) body.egress_proxy_url = egressProxyUrlEl.value.trim();
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
