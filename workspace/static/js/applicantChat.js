// static/js/applicantChat.js
//
// Job Assistant — the Applicant engine's conversational surface, UNIFIED with
// the native Chats experience.
//
// This module used to open its own self-contained modal panel with a second,
// visually inferior message renderer. It now follows the exact pattern
// assistant.js proved for the personal assistant: the rail launcher resolves a
// dedicated per-user engine-backed chat session (GET /api/applicant/chat/session
// — a plain workspace Session flagged by the ENGINE_SESSION_URL sentinel in its
// endpoint_url) and opens it through selectSession(), so the conversation gets
// the full native chat UX for free: the Chats/sessions list (labelled
// "Job assistant"), the native renderer/markdown pipeline, and server-side
// history persistence.
//
// What stays applicant-specific, rendered as ADDITIONS inside the native
// surface while the Job Assistant session is active:
//   - the job-search picker / create form / pending-actions count, mounted as
//     a slim bar above the thread (#applicant-ja-bar);
//   - the guardrail tip above the composer (Chat Hint kit, FR-UIKIT-2);
//   - per-message job-action chips (proposed updates / gaps / search-update
//     confirms) — decorateEngineMessage(), invoked from chatRenderer.addMessage's
//     decoration seam for live turns and history reloads alike.
//
// The send path: chat.js's handleChatSubmit dispatches to sendEngineMessage()
// when isEngineSessionActive() — the turn goes to the engine through the
// workspace proxy (POST /api/applicant/chat/message, with session_id so the
// backend persists the turn into the same session), never the LLM stream.
//
// Activation: the launcher (rail-assistant) is greyed + click-guarded by the
// feature-activation layer in app.js until the engine reports a model is
// connected (the `chat` section, gated on `llm_configured`). We don't fight
// that — the job-search bar renders a graceful "connect a model" state if the
// surface is reached while the engine is unreachable.

import uiModule from './ui.js';
import markdownModule from './markdown.js';
import chatRenderer from './chatRenderer.js';
import {
  selectSession, getCurrentSessionId, getSessions, loadSessions,
} from './sessions.js';
import {
  esc, _toast, _fetchJSON, _post, errText, loadingHTML, errorHTML, gatedHTML, wireRetry,
  pollVisible,
} from './applicantCore.js';
// Chat Hint kit (FR-UIKIT-2): the ONE above-composer guidance affordance. The
// assistant's "ask me what needs your attention" guardrail tip is routed through
// the kit instead of being hand-rolled, so it shares the kit's chrome/anchor and
// per-user dismiss persistence. It mounts above the NATIVE composer's
// `.chat-input-bar` via the AppkitNotice kit while the Job Assistant session is
// the active chat, and is hidden again when the user switches away.
import appkitChatHint from './appkitChatHint.js';
import { registerRoute, setHash, clearHash, syncToken } from './hashRouter.js';

const API = '/api/applicant/chat';

//: Sentinel endpoint_url that flags the Job Assistant's workspace session
//: (mirrors ENGINE_SESSION_URL in routes/applicant_chat_routes.py). It is not
//: a real endpoint — it exists so the send path / model picker / sidebar can
//: recognise the session without any extra bookkeeping.
const ENGINE_SESSION_URL = 'applicant://engine';

//: The assistant's bubble label in the native renderer (persisted turns carry
//: it as metadata.character_name so history reloads label identically).
const ASSISTANT_LABEL = 'Job assistant';

// Design-audit #9: _fetchJSON's shared 15s default timeout is right for plain
// CRUD calls, but a chat turn runs the engine's full agent loop server-side —
// including remote-LLM round trips — and the workspace backend's /message
// proxy waits up to 90s for it (the dedicated _CHAT_TURN_TIMEOUT read budget
// in routes/applicant_chat_routes.py; everything else keeps the tight 30s
// ApplicantEngineClient default). A shorter browser-side abort would fire
// WHILE the backend is still legitimately waiting on the engine, surfacing a
// false "timed out" error for a request that was still in flight. Give this
// one call room to clear the backend's own budget with margin.
const MESSAGE_TIMEOUT_MS = 100000;

// The single guardrail/guidance hint for the Job Assistant composer. Registered
// once with the Chat Hint kit; `gameBuildOnly:false` so it is eligible here (this
// is not the game build), `persistDismiss:true` (the default) so a user's "Got
// it" sticks per-user across reloads.
const CHAT_HINT_KEY = 'applicant-assistant-guardrail';
let _chatHintRegistered = false;
function _ensureChatHintRegistered() {
  if (_chatHintRegistered || !appkitChatHint || typeof appkitChatHint.register !== 'function') return;
  appkitChatHint.register(CHAT_HINT_KEY, {
    html: 'Ask me what needs your attention, or tell me about your preferences and ' +
      "I’ll keep them up to date. Nothing goes out without your go-ahead.",
    gameBuildOnly: false,
  });
  _chatHintRegistered = true;
}

let _sessionId = null;        // resolved Job Assistant session id (this tab)
let _campaigns = [];
let _activeCampaignId = null;
let _engineAvailable = null;  // last /campaigns reachability (null = unknown)
let _sending = false;
let _renderSeq = 0; // monotonic - guards stale async renders on fast campaign switches

// ── Session identity ─────────────────────────────────────────────────────────

/** True when a cached /api/sessions row is the engine-backed Job Assistant
 *  session (identified by the endpoint sentinel — survives renames). */
export function isEngineSession(meta) {
  return !!(meta && meta.endpoint_url === ENGINE_SESSION_URL);
}

/** True when the CURRENTLY ACTIVE chat is the Job Assistant session. This is
 *  the one seam chat.js's send dispatch and modelPicker.js's visibility check
 *  both consult (via window.applicantChatModule). */
export function isEngineSessionActive() {
  const sid = getCurrentSessionId();
  if (!sid) return false;
  if (_sessionId && sid === _sessionId) return true;
  const meta = (getSessions() || []).find((s) => s.id === sid);
  return isEngineSession(meta);
}

// ── Open / hash routing ──────────────────────────────────────────────────────

let _openInFlight = false; // re-entrancy guard (double click / route replay)

export async function openApplicantChat(opts) {
  if (_openInFlight) return false;
  _openInFlight = true;
  // Hash routing (audit #7): '#chat' deep-links here; selectSession() below
  // then replaces it with the canonical '#<sessionId>' hash the native chat
  // owns, so the deep link lands on the unified surface instead of 404ing.
  if (!(opts && opts.skipHashUpdate)) setHash('chat');
  try {
    const info = await _fetchJSON(`${API}/session`);
    if (!info || !info.session_id) {
      // `quiet` suppresses failure toasts for opportunistic callers (the
      // bare-composer send probe in chat.js) that have their own fallback.
      if (!(opts && opts.quiet)) _toast('The assistant is unavailable right now');
      return false;
    }
    _sessionId = info.session_id;
    // The sidebar list and the send-path dispatch identify this session from
    // the cached /api/sessions payload — refresh the list when the id is
    // missing (a brand-new session, or one hydrated server-side after a
    // restart) so it shows up in Chats immediately.
    const known = (getSessions() || []).some((s) => s.id === _sessionId);
    if (!known) {
      try { await loadSessions(); } catch { /* list refresh is best-effort */ }
    }
    await selectSession(_sessionId);
    // selectSession hands the hash over to the native '#<sessionId>' form via
    // history.replaceState (no hashchange event) — re-sync the router's
    // change detector or the NEXT '#chat' navigation would short-circuit as
    // "nothing changed" and the deep link would go dead.
    syncToken();
    _syncExtras();
    return true;
  } catch (e) {
    console.error('openApplicantChat failed:', e);
    if (!(opts && opts.quiet)) _toast(errText(e));
    return false;
  } finally {
    _openInFlight = false;
  }
}

function _close() {
  // The unified surface lives in the native chat plane — there is no modal to
  // hide. Closing (back-button off '#chat', or a programmatic close) only
  // releases the hash token when it is actually ours.
  clearHash('chat');
}

// Exported so other modules/tests can close the Job Assistant surface without
// reaching into its private state, mirroring openApplicantChat's public export.
export function closeApplicantChat() { _close(); }

// ── Per-session extras (the job-search bar + composer hint) ─────────────────
//
// Mounted while the Job Assistant session is the active chat; torn down when
// the user switches to any other session. Driven by the
// 'applicant:session-selected' dispatch seam in sessions.js plus a cheap
// visibility-aware poll for paths that bypass selectSession (e.g. New Chat).

let _extrasMounted = false;

function _syncExtras() {
  if (isEngineSessionActive()) {
    _mountExtras();
    _extrasMounted = true;
  } else if (_extrasMounted) {
    _unmountExtras();
    _extrasMounted = false;
  }
}

// The Notice kit is a classic script (it publishes window.AppkitNoticeKit as
// its seam) and nothing in the boot chain loads it — without this the hint's
// show() would no-op forever behind its kit-absent guard. A side-effect
// dynamic import executes it once; cached thereafter.
let _noticeKitLoad = null;
function _ensureNoticeKitLoaded() {
  if (typeof window !== 'undefined' && window.AppkitNoticeKit) return Promise.resolve();
  if (!_noticeKitLoad) _noticeKitLoad = import('./appkitNotice.js').catch(() => null);
  return _noticeKitLoad;
}

function _mountExtras() {
  const history = document.getElementById('chat-history');
  if (!history || !history.parentNode) return;
  let bar = document.getElementById('applicant-ja-bar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'applicant-ja-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Job assistant controls');
    bar.style.cssText = 'margin:0 auto;width:100%;max-width:800px;padding:8px 12px 0;box-sizing:border-box;flex-shrink:0;';
    bar.innerHTML = loadingHTML();
    history.parentNode.insertBefore(bar, history);
    _refreshBar();
  }
  _ensureChatHintRegistered();
  _ensureNoticeKitLoaded().then(() => {
    // Re-check: the user may have switched away while the kit loaded.
    if (!isEngineSessionActive()) return;
    try { appkitChatHint.show(CHAT_HINT_KEY); } catch { /* kit unavailable — no-op */ }
  });
  // Belt-and-braces alongside updateModelPicker's own isEngineSessionActive
  // seam: that seam can lose the race when this module loads lazily AFTER
  // selectSession already ran its picker refresh — and a model picked here
  // would rewrite the session's endpoint out from under the engine sentinel.
  const pickerWrap = document.getElementById('model-picker-wrap');
  if (pickerWrap) pickerWrap.style.display = 'none';
  _maybeRenderIntro();
  _pruneThreadActions();
}

function _unmountExtras() {
  const bar = document.getElementById('applicant-ja-bar');
  if (bar) bar.remove();
  try { appkitChatHint.hide(CHAT_HINT_KEY); } catch { /* kit unavailable — no-op */ }
  // Give the picker back to whatever session is taking over (its own
  // updateModelPicker pass re-computes the proper state, incl. the
  // group-chat hide). Only runs on a real mounted→unmounted transition.
  const pickerWrap = document.getElementById('model-picker-wrap');
  if (pickerWrap && pickerWrap.style.display === 'none') pickerWrap.style.display = '';
}

async function _loadCampaigns() {
  const data = await _fetchJSON(`${API}/campaigns`);
  _engineAvailable = !(data && data.engine_available === false);
  _campaigns = Array.isArray(data && data.campaigns) ? data.campaigns : [];
  if (!_activeCampaignId && _campaigns.length) _activeCampaignId = _campaigns[0].id;
  return data;
}

async function _refreshBar() {
  const bar = document.getElementById('applicant-ja-bar');
  if (!bar) return;
  try {
    const data = await _loadCampaigns();
    if (!document.getElementById('applicant-ja-bar')) return; // unmounted while loading
    if (data && data.engine_available === false) { _renderOffline(bar); return; }
    if (!_campaigns.length) { _renderNoCampaign(bar); return; }
    _renderBarRow(bar);
  } catch (e) {
    bar.innerHTML = errorHTML(errText(e));
    wireRetry(bar, _refreshBar);
  }
}

// Not connected yet is a GATE, not an error — route it through the kit's gated
// affordance with a clear CTA wired to the same launcher the rest of the front
// door uses to reopen setup (window.launchApplicantSetup).
function _renderOffline(bar) {
  bar.innerHTML = gatedHTML(
    'Connect a model in Settings and I can answer questions about your '
      + 'applications and flag anything that needs your input.',
    '<button type="button" class="cal-btn cal-btn-primary" id="applicant-chat-connect-cta">Connect a model</button>',
  );
  const cta = bar.querySelector('#applicant-chat-connect-cta');
  if (cta) {
    cta.addEventListener('click', () => {
      try {
        if (typeof window.launchApplicantSetup === 'function') window.launchApplicantSetup();
      } catch { /* no-op — no launcher available, the button simply stays put */ }
    });
  }
}

function _renderNoCampaign(bar) {
  bar.innerHTML = `
    <div style="border:1px solid var(--border);border-radius:6px;padding:14px 12px;text-align:center;">
      <div style="font-size:13px;margin-bottom:8px;">Create a job search to get started</div>
      <div style="font-size:12px;opacity:0.7;max-width:420px;margin:0 auto 10px;">
        A job search groups its preferences, materials, and applications. Name it
        anything you like.
      </div>
      <div style="display:flex;gap:8px;justify-content:center;max-width:360px;margin:0 auto;">
        <input type="text" id="applicant-new-campaign" class="settings-select" placeholder="e.g. Backend roles 2026"
               aria-label="Job search name" style="flex:1;" />
        <button type="button" class="cal-btn cal-btn-primary" id="applicant-create-campaign">Create</button>
      </div>
    </div>`;
  const input = bar.querySelector('#applicant-new-campaign');
  const btn = bar.querySelector('#applicant-create-campaign');
  const create = async () => {
    const name = (input.value || '').trim();
    if (!name) { input.focus(); return; }
    btn.disabled = true;
    btn.textContent = 'Creating…';
    try {
      const created = await _post(`${API}/campaigns`, { name });
      _toast('Job search created');
      await _loadCampaigns();
      if (created && created.id) _activeCampaignId = created.id;
      _renderBarRow(bar);
    } catch (e) {
      _toast(errText(e) || 'Could not create the job search');
      btn.disabled = false;
      btn.textContent = 'Create';
    }
  };
  btn.addEventListener('click', create);
  input.addEventListener('keydown', (e) => {
    // micro-interactions audit #15: don't let an IME composition-commit Enter
    // (CJK / dead-key input) fire the create action.
    if (e.key === 'Enter' && !e.isComposing && e.keyCode !== 229) create();
  });
}

function _campaignPicker() {
  if (_campaigns.length <= 1) return '';
  const opts = _campaigns.map((c) =>
    `<option value="${esc(c.id)}"${c.id === _activeCampaignId ? ' selected' : ''}>${esc(c.name || c.id)}</option>`
  ).join('');
  return `
    <label style="display:flex;align-items:center;gap:6px;font-size:12px;flex-shrink:0;">
      <span style="opacity:0.7;">Job search</span>
      <select id="applicant-campaign-pick" class="settings-select" aria-label="Job search">${opts}</select>
    </label>`;
}

function _renderBarRow(bar) {
  bar.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;">
      ${_campaignPicker()}
      <div id="applicant-pending" style="flex:1;min-width:220px;"></div>
    </div>
    <div id="applicant-starters" style="display:none;flex-wrap:wrap;gap:6px;margin-top:8px;"></div>`;

  const pick = bar.querySelector('#applicant-campaign-pick');
  if (pick) {
    pick.addEventListener('change', () => {
      _activeCampaignId = pick.value;
      const seq = ++_renderSeq;
      _loadPending(seq);
    });
  }
  _renderStarters();
  _loadPending();
}

// ── Pending job actions ──────────────────────────────────────────────────────
//
// The Pending Portal is the single source of truth for everything awaiting the
// user across all job searches (C4). Rather than re-render a second, divergent
// list here (which let the same item behave differently in two places), the chat
// surfaces a live count and a link that opens the Portal home base. The Portal
// owns the affordances, the rendering, and the resolve/answer wiring.

async function _loadPending(seq) {
  const host = document.getElementById('applicant-pending');
  if (!host) return;
  try {
    // Cross-job-search count from the Portal proxy — the same source the rail
    // badge and the Portal home base use, so the number always agrees.
    const data = await _fetchJSON('/api/applicant/portal/pending');
    if (seq && seq !== _renderSeq) return; // stale — a newer switch is already in flight
    if (data && data.engine_available === false) { host.innerHTML = ''; return; }
    const count = (data && (data.count != null ? data.count : (data.items || []).length)) || 0;
    if (!count) { host.innerHTML = ''; return; }
    host.innerHTML = `
      <div class="applicant-pending-link" style="border:1px solid var(--border);border-radius:6px;padding:6px 10px;display:flex;justify-content:space-between;gap:8px;align-items:center;">
        <div style="font-size:12px;">
          <strong>${esc(count)} item${count === 1 ? '' : 's'} need${count === 1 ? 's' : ''} your attention</strong>
          <div style="opacity:0.6;font-size:11px;">Review and act on these in your Pending home base.</div>
        </div>
        <button type="button" class="cal-btn cal-btn-primary" id="applicant-open-portal" style="flex-shrink:0;">Open Pending</button>
      </div>`;
    const openBtn = host.querySelector('#applicant-open-portal');
    if (openBtn) {
      openBtn.addEventListener('click', () => {
        try {
          if (window.applicantPortalModule && typeof window.applicantPortalModule.openApplicantPortal === 'function') {
            window.applicantPortalModule.openApplicantPortal();
            return;
          }
        } catch { /* fall through */ }
        const rail = document.getElementById('rail-portal');
        if (rail) rail.click();
      });
    }
  } catch (e) {
    // Soft-degrade: a pending-actions failure must not break the conversation.
    host.innerHTML = '';
  }
}

// ── Starters + intro (empty-thread invitation) ──────────────────────────────

// A few tappable starter prompts so a blank thread reads as an invitation, not a
// dead end (delight #10 / quick-wins #18). Tapping one prefills the composer.
const _STARTER_PROMPTS = [
  "Tell me what you're looking for",
  'What have you found so far?',
  'Change what you look for',
  'How does this all work?',
];

function _threadIsEmpty() {
  const history = document.getElementById('chat-history');
  return !history || history.querySelectorAll('.msg').length === 0;
}

function _renderStarters() {
  const host = document.getElementById('applicant-starters');
  if (!host) return;
  if (!_threadIsEmpty() && !document.querySelector('#chat-history .applicant-ja-intro')) {
    host.style.display = 'none';
    return;
  }
  host.innerHTML = _STARTER_PROMPTS.map((p) =>
    `<button type="button" class="cal-btn applicant-starter" style="font-size:12px;">${esc(p)}</button>`
  ).join('');
  host.querySelectorAll('.applicant-starter').forEach((btn) => {
    btn.addEventListener('click', () => _prefillComposer(btn.textContent || ''));
  });
  host.style.display = 'flex';
}

// Prefill the NATIVE composer with a starter prompt and focus it, leaving the
// send under the user's control (we don't auto-send — they can tweak first).
function _prefillComposer(text) {
  const input = document.getElementById('message');
  if (!input) return;
  input.value = text;
  input.focus();
  try { input.setSelectionRange(text.length, text.length); } catch { /* no-op */ }
  try { if (uiModule.autoResize) uiModule.autoResize(input); } catch { /* no-op */ }
}

// First-visit greeting, rendered through the NATIVE renderer so it looks like
// every other assistant bubble. Client-side only (not persisted) — it appears
// while the thread is empty and naturally gives way to the real history.
function _maybeRenderIntro() {
  if (!_threadIsEmpty()) return;
  if (document.querySelector('#chat-history .applicant-ja-intro')) return;
  const wrap = chatRenderer.addMessage('assistant',
    'Hi — I can help with your job search. Ask me what needs your attention, ' +
    'or tell me about your preferences and I’ll keep them up to date.',
    ASSISTANT_LABEL);
  if (wrap) {
    wrap.classList.add('applicant-ja-intro');
    // The greeting is ephemeral — a footer offering delete/regenerate on it
    // would act on a message the server never stored.
    const footer = wrap.querySelector('.msg-footer');
    if (footer) footer.remove();
  }
  _renderStarters();
}

// ── Native-footer pruning for engine turns ──────────────────────────────────
//
// The native footer actions that re-enter the LLM streaming path (regenerate,
// rewrite shorter/simpler, fork, edit, resend, delete-by-id) can't apply to an
// engine-backed turn — the Applicant engine owns this conversation's replies.
// Keep copy; drop the rest. (.msg-action-btn covers exactly those; the copy
// affordance is .footer-copy-btn.)

function _pruneBubbleActions(wrap) {
  if (!wrap) return;
  wrap.querySelectorAll('.msg-footer .msg-action-btn').forEach((btn) => btn.remove());
}

function _pruneThreadActions() {
  document.querySelectorAll('#chat-history .msg').forEach((m) => _pruneBubbleActions(m));
}

// ── Job-action chips (per-message decoration) ───────────────────────────────

function _renderProposals(proposals) {
  if (!proposals || !proposals.length) return '';
  const rows = proposals.map((p, i) => {
    const applied = p.applied;
    const needs = p.requires_confirmation && !applied;
    const status = applied
      ? '<span style="color:var(--success,#3a8a3a);font-size:11px;">saved automatically</span>'
      : (needs ? '' : '<span style="opacity:0.6;font-size:11px;">no change needed</span>');
    const confirmBtn = needs
      ? `<button type="button" class="cal-btn cal-btn-primary applicant-confirm-btn" data-idx="${i}">Confirm</button>`
      : '';
    return `
      <div class="applicant-proposal" data-idx="${i}" style="border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-top:6px;font-size:12px;">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
          <div><strong>${esc(p.name)}</strong>: ${esc(p.value)}</div>
          ${confirmBtn}
        </div>
        <div style="margin-top:2px;">
          <span style="opacity:0.6;">${esc(p.kind)}${p.is_sensitive ? ' · sensitive' : ''}</span>
          ${status}
        </div>
      </div>`;
  }).join('');
  return `<div class="applicant-proposals" style="margin-top:8px;">
      <div style="font-size:11px;opacity:0.7;margin-bottom:2px;">Suggested updates</div>${rows}
    </div>`;
}

function _renderGaps(gaps) {
  if (!gaps || !gaps.length) return '';
  const items = gaps.map((g) => `<li>${esc(g)}</li>`).join('');
  return `<div style="margin-top:8px;font-size:12px;opacity:0.8;">
      <div style="font-size:11px;opacity:0.7;">Still missing</div>
      <ul style="margin:2px 0 0 16px;padding:0;">${items}</ul>
    </div>`;
}

// FR-FB-3 / FR-CRIT: render criteria refocus proposals that require confirmation.
// These come back as control_actions with kind="criteria" + requires_confirmation=true.
function _renderCriteriaActions(actions) {
  if (!actions || !actions.length) return '';
  const pending = actions.filter((a) => a.kind === 'criteria' && a.requires_confirmation && !a.applied);
  if (!pending.length) return '';
  const rows = pending.map((a, i) => {
    const summary = Object.entries(a.detail || {})
      .map(([k, v]) => `${esc(k)}: ${esc(String(v))}`).join(', ') || 'criteria update';
    return `
      <div class="applicant-criteria-action" data-idx="${i}"
           style="border:1px solid var(--border);border-radius:6px;padding:8px 10px;margin-top:6px;font-size:12px;">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
          <div><strong>Search update</strong>: ${summary}</div>
          <button type="button" class="cal-btn cal-btn-primary applicant-confirm-criteria-btn"
                  data-idx="${i}">Confirm</button>
        </div>
      </div>`;
  }).join('');
  return `<div class="applicant-criteria-actions" style="margin-top:8px;">
      <div style="font-size:11px;opacity:0.7;margin-bottom:2px;">Proposed search update</div>${rows}
    </div>`;
}

function _wireProposalButtons(container, proposals) {
  container.querySelectorAll('.applicant-confirm-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.idx);
      const p = proposals[idx];
      if (!p) return;
      if (!_activeCampaignId) { _toast('Pick or create a job search first'); return; }
      btn.disabled = true;
      btn.textContent = 'Saving…';
      try {
        await _post(`${API}/confirm`, {
          campaign_id: _activeCampaignId, name: p.name, value: p.value,
        });
        const row = container.querySelector(`.applicant-proposal[data-idx="${idx}"]`);
        if (row) {
          btn.remove();
          const meta = row.querySelector('div:last-child');
          if (meta) meta.innerHTML += ' <span style="color:var(--success,#3a8a3a);font-size:11px;">saved</span>';
        }
        _toast('Saved');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Confirm';
        _toast(errText(e) || 'Could not save');
      }
    });
  });
}

// FR-FB-3 / FR-CRIT: wire "Confirm" buttons for criteria refocus actions.
// Calls POST /api/applicant/chat/confirm-criteria with the campaign id and
// the detail dict from the control action.
function _wireCriteriaButtons(container, actions) {
  const pending = (actions || []).filter(
    (a) => a.kind === 'criteria' && a.requires_confirmation && !a.applied,
  );
  container.querySelectorAll('.applicant-confirm-criteria-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.idx);
      const a = pending[idx];
      if (!a) return;
      if (!_activeCampaignId) { _toast('Pick or create a job search first'); return; }
      btn.disabled = true;
      btn.textContent = 'Saving…';
      try {
        await _post(`${API}/confirm-criteria`, {
          campaign_id: _activeCampaignId,
          changes: a.detail || {},
        });
        const row = container.querySelector(`.applicant-criteria-action[data-idx="${idx}"]`);
        if (row) {
          btn.remove();
          row.innerHTML += ' <span style="color:var(--success,#3a8a3a);font-size:11px;">saved</span>';
        }
        _toast('Search settings updated');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Confirm';
        _toast(errText(e) || 'Could not save the search update');
      }
    });
  });
}

/**
 * Per-message extension for engine turns: attach the job-action chips
 * (gaps / proposed updates / search-update confirms) to a native assistant
 * bubble. Called by chatRenderer.addMessage's decoration seam on history
 * reload (payload = persisted metadata.applicant) and by the live send path
 * below — one code path for both.
 */
export function decorateEngineMessage(wrap, payload) {
  if (!wrap || !payload) return;
  const b = wrap.querySelector('.body');
  if (!b) return;
  _pruneBubbleActions(wrap);
  const old = wrap.querySelector('.applicant-msg-extras');
  if (old) old.remove();
  const html = _renderGaps(payload.gaps)
    + _renderProposals(payload.proposed_changes)
    + _renderCriteriaActions(payload.control_actions);
  if (!html) return;
  const host = document.createElement('div');
  host.className = 'applicant-msg-extras';
  host.innerHTML = html;
  b.appendChild(host);
  _wireProposalButtons(host, payload.proposed_changes || []);
  _wireCriteriaButtons(host, payload.control_actions || []);
}

// ── Send path (dispatched from chat.js's handleChatSubmit) ──────────────────

function _setBubbleReply(wrap, replyText) {
  if (!wrap) return;
  const b = wrap.querySelector('.body');
  if (!b) return;
  const text = markdownModule.squashOutsideCode(String(replyText == null ? '' : replyText));
  b.innerHTML = markdownModule.processWithThinking(text);
  wrap.dataset.raw = String(replyText == null ? '' : replyText);
  if (window.hljs) {
    b.querySelectorAll('pre code:not(.hljs)').forEach((el) => window.hljs.highlightElement(el));
  }
}

// Does the actual POST + response/error rendering into an existing "thinking"
// bubble, WITHOUT appending a new user bubble. Shared by the initial send and
// by Retry, so retrying never duplicates the user's message in the thread.
async function _sendToBubble(message, rawComposerValue, thinking) {
  _sending = true;
  const input = document.getElementById('message');
  try {
    const res = await _post(`${API}/message`, {
      campaign_id: _activeCampaignId,
      message,
      session_id: _sessionId || getCurrentSessionId(),
    }, { timeoutMs: MESSAGE_TIMEOUT_MS });
    const reply = res.message || "I didn't get a reply — please try sending that again.";
    _setBubbleReply(thinking, reply);
    decorateEngineMessage(thinking, {
      gaps: res.gaps || [],
      proposed_changes: res.proposed_changes || [],
      control_actions: res.control_actions || [],
    });
    // Only clear the composer once the request actually succeeded — on
    // failure the typed text must survive so the user isn't forced to retype.
    if (input && input.value === rawComposerValue) {
      input.value = '';
      try { if (uiModule.autoResize) uiModule.autoResize(input); } catch { /* no-op */ }
    }
    _loadPending();
    try { uiModule.scrollHistory(); } catch { /* no-op */ }
  } catch (e) {
    if (thinking) {
      const b = thinking.querySelector('.body');
      if (b) {
        b.innerHTML = `<span style="opacity:0.8;">${esc(errText(e))}</span> `
          + '<button type="button" class="cal-btn applicant-chat-retry" '
          + 'style="margin-left:6px;">Retry</button>';
        const retry = b.querySelector('.applicant-chat-retry');
        if (retry) retry.addEventListener('click', () => {
          // Resend the same message against the SAME bubble — do not append
          // another user bubble, and reset it back to "thinking" first.
          b.innerHTML = loadingHTML('Thinking…');
          _sendToBubble(message, rawComposerValue, thinking);
        });
      }
    }
  } finally {
    _sending = false;
    if (input) input.focus();
  }
}

/**
 * Send one Job Assistant turn through the engine proxy, rendering into the
 * NATIVE chat thread. Called by chat.js's dispatch seam with the composer's
 * raw value; returns false when nothing was sent (busy / empty / no job
 * search yet) so the composer keeps the typed text.
 */
export async function sendEngineMessage(rawText) {
  const rawComposerValue = rawText == null ? '' : String(rawText);
  const message = rawComposerValue.trim();
  if (!message || _sending) return false;
  if (!_activeCampaignId) {
    // Lazy load (deep-link straight into the session before the bar resolved).
    try { await _loadCampaigns(); } catch { /* fall through to the guard below */ }
  }
  if (!_activeCampaignId) {
    // Tell the user the right next step: "create a job search" only applies
    // when the engine is actually reachable — otherwise the missing piece is
    // the model connection, and the bar renders that gate with its CTA.
    _toast(_engineAvailable === false
      ? 'Connect a model first — the bar above will walk you through it'
      : 'Pick or create a job search first');
    _refreshBar();
    return false;
  }
  // micro-interactions audit #84: starter prompts are an invitation for a
  // blank thread — once the conversation actually starts they just eat
  // vertical space, so hide them the first time a message goes out.
  const startersHost = document.getElementById('applicant-starters');
  if (startersHost) startersHost.style.display = 'none';
  const userWrap = chatRenderer.addMessage('user', message);
  _pruneBubbleActions(userWrap);
  // A calm "thinking" pill instead of a bare word, so the wait reads as work,
  // not a hang (quick-wins #16 / delight #38). loadingHTML renders trusted markup.
  const thinking = chatRenderer.addMessage('assistant', '', ASSISTANT_LABEL);
  _pruneBubbleActions(thinking);
  const tBody = thinking && thinking.querySelector('.body');
  if (tBody) tBody.innerHTML = loadingHTML('Thinking…');
  try { uiModule.scrollHistory(); } catch { /* no-op */ }
  await _sendToBubble(message, rawComposerValue, thinking);
  return true;
}

// ── ONE-chat unification (New Chat opens the Applicant assistant) ───────────
//
// There is a single user-facing chat: the engine-backed Applicant assistant.
// Every generic "start a chat" affordance — the sidebar brand, the New Chat
// list item, the icon-rail new-session button, the mobile new-chat button —
// opens THIS conversation instead of spinning up a bare workspace-LLM
// session. The raw-LLM path stays reachable only through a deliberate model
// pick (the model picker / models list), which other workspace features
// (document chat, agent runs, Compare) still rely on.
//
// The interception is document-capture so it wins regardless of module load
// order, and it engages only after the boot probe confirms this account owns
// the engine chat (`GET /api/applicant/chat/session` is gated by
// require_engine_owner — a second, non-owner workspace account keeps the
// native behavior since the engine is single-tenant).

const NEW_CHAT_LAUNCHER_IDS = [
  'sidebar-new-chat-btn', 'chat-new-btn',
  'rail-new-session', 'mobile-new-chat-btn',
];

// The wordmark is HOME, not a chat launcher — clicking "Applicant" returns you
// to Today (the Pending/Portal home base), it does NOT spin up a new chat.
const HOME_LAUNCHER_ID = 'sidebar-brand-btn';

let _unifiedPrimary = false;

function _relabelNewChatLaunchers() {
  // The affordances now open the one Applicant chat — say so. (Runtime-only;
  // the static markup keeps its generic labels for non-owner accounts.)
  const title = 'Chat — your Applicant assistant';
  for (const id of NEW_CHAT_LAUNCHER_IDS) {
    const el = document.getElementById(id);
    if (!el) continue;
    el.title = title;
    if (el.getAttribute('aria-label')) el.setAttribute('aria-label', title);
  }
  const newChatItem = document.getElementById('sidebar-new-chat-btn');
  const label = newChatItem && newChatItem.querySelector('.grow');
  if (label && /new chat/i.test(label.textContent || '')) label.textContent = 'Chat';
  // The wordmark is Home now — retitle it away from the static "New chat".
  const brand = document.getElementById(HOME_LAUNCHER_ID);
  if (brand) {
    const homeTitle = 'Applicant — back to Today';
    brand.title = homeTitle;
    if (brand.getAttribute('aria-label')) brand.setAttribute('aria-label', homeTitle);
  }
}

async function _probeUnifiedPrimary() {
  try {
    const info = await _fetchJSON(`${API}/session`);
    if (info && info.session_id) {
      _sessionId = info.session_id;
      _unifiedPrimary = true;
      _relabelNewChatLaunchers();
    }
  } catch { /* not the engine owner (or engine chat down) — native behavior stays */ }
}

function _interceptNewChatClick(e) {
  if (!_unifiedPrimary) return;
  const target = e.target;
  if (!target || typeof target.closest !== 'function') return;
  const hit = target.closest(
    [HOME_LAUNCHER_ID, ...NEW_CHAT_LAUNCHER_IDS].map((id) => `#${id}`).join(', '),
  );
  if (!hit) return;
  // Capture phase on document: stop the event before app.js's own handlers
  // (which would set up a pending direct-LLM chat) ever see it.
  e.preventDefault();
  e.stopPropagation();
  // The wordmark goes HOME (Today/Portal); every other launcher opens the chat.
  if (hit.id === HOME_LAUNCHER_ID) {
    const home = document.getElementById('tool-portal-btn')
      || document.getElementById('rail-portal');
    if (home) home.click();
    return;
  }
  openApplicantChat();
}

// ── Launchers / boot ─────────────────────────────────────────────────────────

function _wireLauncher() {
  // Two launchers: the desktop sidebar item (#tool-assistant-btn) and the compact
  // icon-rail button (#rail-assistant, used on mobile). Wire whichever are present.
  for (const id of ['tool-assistant-btn', 'rail-assistant']) {
    const btn = document.getElementById(id);
    if (!btn || btn._applicantWired) continue;
    btn._applicantWired = true;
    btn.addEventListener('click', () => {
      // Respect the feature-activation lock — if app.js greyed the launcher
      // (engine/model not ready) its capture-phase guard already stopped this
      // handler; reaching here means the section is active.
      openApplicantChat();
    });
  }
}

function _boot() {
  _wireLauncher();
  // ONE chat: claim the generic new-chat affordances for the assistant (the
  // probe flips the switch only for the engine-owner account).
  document.addEventListener('click', _interceptNewChatClick, true);
  _probeUnifiedPrimary();
  // The launchers may be (re)rendered after boot; retry briefly so they always
  // get wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('tool-assistant-btn')?._applicantWired || tries > 20) {
      clearInterval(iv);
    }
  }, 500);
  // Mount/unmount the per-session extras as the active chat changes: the
  // sessions.js dispatch seam covers every selectSession() path, and a cheap
  // visibility-aware poll catches the few that bypass it (e.g. New Chat).
  document.addEventListener('applicant:session-selected', _syncExtras);
  pollVisible(_syncExtras, 2500);
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

// Hash routing (audit #7): '#chat' deep-links straight into the Job
// Assistant — openApplicantChat resolves the unified session and hands the
// hash over to the native '#<sessionId>' form, so old links keep working.
// Registered at module-eval time (runs as soon as the dynamic import
// resolves, well before app.js calls hashRouter.initHashRouting()).
registerRoute('chat', { open: openApplicantChat, close: _close });

// Boot deep-link catch-up: this module loads lazily (assistant.js's dynamic
// import), so the router's boot-time hash application can run BEFORE the
// 'chat' registration above exists — leaving a '#chat' page load dead. If
// the page is sitting on our token and nothing has opened it, honor it now
// (the _openInFlight guard makes a double invocation harmless).
try {
  if (typeof window !== 'undefined' && (window.location.hash || '') === '#chat'
      && !isEngineSessionActive()) {
    openApplicantChat();
  }
} catch { /* no-op */ }

const applicantChatModule = {
  openApplicantChat,
  closeApplicantChat,
  isEngineSession,
  isEngineSessionActive,
  sendEngineMessage,
  decorateEngineMessage,
};

// Expose for the send dispatch in chat.js, the model-picker visibility check,
// and deep-links / other modules — without creating import coupling.
try { window.applicantChatModule = applicantChatModule; } catch { /* no-op */ }

export default applicantChatModule;
