// static/js/applicantChat.js
//
// Job Assistant — the workspace Chat/Agent surface wired to the Applicant
// engine. This is ADDITIVE and self-contained: it does NOT touch the native
// chat engine (chat.js) or the personal-assistant CrewMember (assistant.js). It
// opens its own modal panel, talks to the engine through the workspace proxy at
// /api/applicant/chat/*, and surfaces job actions inline so the user can act on
// them without leaving the conversation.
//
// Activation: the launcher (rail-assistant) is greyed + click-guarded by the
// feature-activation layer in app.js until the engine reports a model is
// connected (the `chat` section, gated on `llm_configured`). We don't fight
// that — we just render a graceful "connect a model" state if opened while the
// engine is unreachable.

import uiModule from './ui.js';
import markdownModule from './markdown.js';
import {
  esc, _toast, _fetchJSON, _post, errText, loadingHTML, gatedHTML,
} from './applicantCore.js';
// Chat Hint kit (FR-UIKIT-2): the ONE above-composer guidance affordance. The
// assistant's "ask me what needs your attention" guardrail tip is routed through
// the kit instead of being hand-rolled, so it shares the kit's chrome/anchor and
// per-user dismiss persistence. It mounts above the composer's `.chat-input-bar`
// (the composer carries that hook class) via the AppkitNotice kit.
import appkitChatHint from './appkitChatHint.js';

const API = '/api/applicant/chat';

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
      "I'll keep them up to date. I never submit an application without your OK.",
    gameBuildOnly: false,
  });
  _chatHintRegistered = true;
}

let _modalEl = null;
let _renderSeq = 0; // monotonic - guards stale async renders on fast campaign switches
let _modalA11yCleanup = null;
let _campaigns = [];
let _activeCampaignId = null;
let _sending = false;

// Item #46: once the panel is docked to the bottom of the content plane (see
// the CSS notes at "#applicant-chat-modal" in style.css), it sits directly
// over the REAL page composer's band. Mirror Portal's own composer-dimming
// (`_setComposerDimmed` in applicantPortal.js, audit #32) here rather than
// importing it — this module is deliberately additive/self-contained (see
// the file banner) — so the two composers don't visually double up while
// this panel is open. Scoped to the real page composer only: `#chat-container
// > .chat-input-bar` is that element's exact position in index.html, which
// does NOT match this modal's own composer (`#applicant-composer`, appended
// to `document.body`, not `#chat-container`).
let _composerDimmed = false;
let _composerPrevStyle = null;
function _setComposerDimmed(on) {
  let bar;
  try { bar = document.querySelector('#chat-container > .chat-input-bar'); } catch { bar = null; }
  if (!bar) return;
  if (on) {
    if (_composerDimmed) return; // already dimmed — don't clobber the saved prior style
    _composerDimmed = true;
    _composerPrevStyle = bar.getAttribute('style');
    bar.style.transition = 'opacity 0.15s ease';
    bar.style.opacity = '0.35';
    bar.style.pointerEvents = 'none';
  } else if (_composerDimmed) {
    _composerDimmed = false;
    if (_composerPrevStyle === null) bar.removeAttribute('style');
    else bar.setAttribute('style', _composerPrevStyle);
    _composerPrevStyle = null;
  }
}





// NOTE: campaign steering controls (start/pause/resume/run-now) were removed —
// they were never wired into the conversation render and pointed at chat-proxy
// endpoints (`/api/applicant/chat/campaigns/{id}/status|start|pause|resume|
// run-now`) that do not exist (the engine exposes those only under
// `/api/agent-runs/*`, which the chat proxy does not forward), so the controls
// would only ever have 404'd. Removed as dead code.

// ── Modal scaffold ──────────────────────────────────────────────────────────
//
// Design-audit item #46: this stream used to render as a centered `.modal`
// slab over the live composer/welcome. A full inline re-dock (re-parenting
// the thread/composer out of the modal lifecycle entirely, so they become
// literal siblings of the real composer in the DOM) is still judged too
// risky to attempt in one pass here: it would touch the thinking-indicator,
// send-gating, composer-clear-on-success, and retry-without-duplicate-bubble
// wiring that all assume this modal's current lifecycle — real, working
// behavior that a re-parent could silently break. Instead this panel now
// makes a real, verifiable structural move within its EXISTING lifecycle:
// - it docks to the BOTTOM of the content plane (the real composer's band)
//   instead of floating vertically centered mid-screen over the welcome
//   text (`#applicant-chat-modal { align-items: flex-end; }`, desktop-only,
//   in style.css — the mobile bottom sheet was already bottom-anchored);
// - its width now matches the real composer's own 800px max-width (below,
//   `--window-w:800px`) so the two line up instead of the modal reading as
//   an unrelated, differently-sized card;
// - the real page composer is dimmed for as long as this panel is open
//   (`_setComposerDimmed`, above — mirrors Portal's own composer-dimming)
//   so the two don't visually double up underneath the docked panel.
// The lower-risk half from the prior pass IS done and untouched here: the
// composer bar inside the modal used to carry its own nested frosted-glass
// layer on top of the modal's own glass ("glass-on-glass-on-content");
// style.css flattens that inner layer so the panel reads as one content
// plane (search "item #46" in style.css).
//
// Design-audit item #64: the header now composes the shared AppkitWindow kit
// chrome (`.ow-window` / `.ow-titlebar` / `.ow-controls` / `.ow-close`) so its
// titlebar matches every other window's traffic-light controls, mirroring
// the exact pattern applicantPortal.js adopted (audit #25). The close button
// keeps `.modal-close` + `.tap-exempt` alongside the new `.ow-close`: dropping
// `.modal-close` would break the mobile swipe-to-dismiss handoff (the shared
// mobile-sheet rule hides the desktop close-X via that class), and dropping
// `.tap-exempt` would pull it into the global coarse-pointer 44px tap-target
// floor and blow out the titlebar — the same subtlety Portal's batch found.

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-chat-modal';
  modal.className = 'modal hidden ow-window';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Job Assistant');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:800px;display:flex;flex-direction:column;max-height:86vh;">
      <div class="modal-header ow-titlebar">
        <div class="ow-controls">
          <button type="button" class="ow-close modal-close tap-exempt" id="applicant-chat-close" aria-label="Close" title="Close">&times;</button>
        </div>
        <h4 class="ow-title">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          Job Assistant
        </h4>
      </div>
      <div class="modal-body" id="applicant-chat-body" style="flex:1;overflow-y:auto;">
        ${loadingHTML()}
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  // Escape is handled by initModalA11y above (topmost-modal arbiter,
  // design-audit item #17) — do not add a second local Escape listener here.
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.querySelector('#applicant-chat-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
  if (_modalA11yCleanup) { _modalA11yCleanup(); _modalA11yCleanup = null; }
  if (_modalEl) {
    _modalEl.classList.add('hidden');
    _modalEl.style.display = '';
  }
  _setComposerDimmed(false);
}

// ── Empty / offline state ────────────────────────────────────────────────────

function _renderOffline(body) {
  // Not connected yet is a GATE, not an error — route it through the kit's gated
  // affordance with a clear CTA hint instead of a wall of prose (quick-wins #18).
  // Item #52: the hint used to be inert text ("Open Settings → Connect a model")
  // with no way to act on it — a dead end. Route it through a real primary button
  // wired to the same launcher the rest of the front door uses to reopen setup
  // (window.launchApplicantSetup, exported by applicantOnboarding.js), so there's
  // an actual next step instead of a instruction to go find Settings yourself.
  body.innerHTML = gatedHTML(
    'Connect a model in Settings to activate the Job Assistant. Once a model is '
      + 'connected it can answer questions about your applications and surface '
      + 'anything that needs your input.',
    '<button type="button" class="cal-btn cal-btn-primary" id="applicant-chat-connect-cta">Connect a model</button>',
  );
  const cta = body.querySelector('#applicant-chat-connect-cta');
  if (cta) {
    cta.addEventListener('click', () => {
      try {
        if (typeof window.launchApplicantSetup === 'function') { window.launchApplicantSetup(); _close(); }
      } catch { /* no-op — no launcher available, the button simply stays put */ }
    });
  }
}

function _renderNoCampaign(body) {
  body.innerHTML = `
    <div style="padding:24px 18px;text-align:center;">
      <div style="font-size:14px;margin-bottom:10px;">Create a job search to get started</div>
      <div style="font-size:12px;opacity:0.7;max-width:420px;margin:0 auto 14px;">
        A job search groups its preferences, materials, and applications. Name it
        anything you like.
      </div>
      <div style="display:flex;gap:8px;justify-content:center;max-width:360px;margin:0 auto;">
        <input type="text" id="applicant-new-campaign" class="settings-select" placeholder="e.g. Backend roles 2026"
               style="flex:1;" />
        <button type="button" class="cal-btn cal-btn-primary" id="applicant-create-campaign">Create</button>
      </div>
    </div>`;
  const input = body.querySelector('#applicant-new-campaign');
  const btn = body.querySelector('#applicant-create-campaign');
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
      _renderConversation();
    } catch (e) {
      _toast(e.message || 'Could not create the job search');
      btn.disabled = false;
      btn.textContent = 'Create';
    }
  };
  btn.addEventListener('click', create);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') create(); });
  input.focus();
}

// ── Conversation view ────────────────────────────────────────────────────────

function _campaignPicker() {
  if (_campaigns.length <= 1) return '';
  const opts = _campaigns.map((c) =>
    `<option value="${esc(c.id)}"${c.id === _activeCampaignId ? ' selected' : ''}>${esc(c.name || c.id)}</option>`
  ).join('');
  return `
    <label class="assistant-field" style="margin-bottom:10px;">
      <span>Job search</span>
      <select id="applicant-campaign-pick">${opts}</select>
    </label>`;
}

function _renderConversation() {
  const body = _modalEl.querySelector('#applicant-chat-body');
  body.innerHTML = `
    ${_campaignPicker()}
    <div id="applicant-controls"></div>
    <div id="applicant-suggested-card" style="margin-bottom:10px;border:1px solid var(--border);border-radius:6px;padding:8px 10px;display:none;"></div>
    <div id="applicant-pending" style="margin-bottom:12px;"></div>
    <div id="applicant-thread" class="chat-history" style="display:flex;flex-direction:column;margin-bottom:12px;padding-left:0;padding-right:0;"></div>
    <div id="applicant-starters" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;"></div>
    <div id="applicant-composer" class="chat-input-bar" style="display:flex;gap:8px;align-items:flex-end;border-top:1px solid var(--border);padding-top:10px;position:sticky;bottom:0;background:var(--bg);">
      <textarea id="applicant-input" rows="2" placeholder="Ask about your applications, preferences, or what needs your attention…"
                style="flex:1;resize:vertical;padding:8px 10px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-family:inherit;font-size:13px;"></textarea>
      <button type="button" class="cal-btn cal-btn-primary" id="applicant-send" title="Send to the assistant">Send</button>
    </div>`;

  const pick = body.querySelector('#applicant-campaign-pick');
  if (pick) {
    pick.addEventListener('change', () => {
      _activeCampaignId = pick.value;
      const seq = ++_renderSeq;
      _renderThreadIntro(seq);
      _loadPending(seq);
    });
  }

  const input = body.querySelector('#applicant-input');
  const sendBtn = body.querySelector('#applicant-send');
  const send = () => _send(input.value);
  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
  });
  // Gate the Send button on non-empty input (quick-wins #10): dim + disable until
  // there's something to send, and keep it in sync as the user types.
  input.addEventListener('input', _syncSendEnabled);
  _syncSendEnabled();

  _renderStarters();
  _renderThreadIntro();
  _loadPending();
  input.focus();

  // Mount the above-composer guardrail tip through the Chat Hint kit. The kit
  // anchors it above the composer's `.chat-input-bar` and owns its dismiss/
  // persistence; show() is idempotent and a no-op once the user dismissed it.
  _ensureChatHintRegistered();
  try { appkitChatHint.show(CHAT_HINT_KEY); } catch { /* kit unavailable — no-op */ }
}

function _renderThreadIntro(seq) {
  const thread = _modalEl.querySelector('#applicant-thread');
  if (!thread) return;
  thread.innerHTML = '';
  _appendMessage('assistant',
    'Hi — I can help with your job search. Ask me what needs your attention, ' +
    "or tell me about your preferences and I'll keep them up to date.");
}

// Enable/disable the Send button based on whether there's typed content, so an
// empty composer can't fire an empty send (quick-wins #10).
function _syncSendEnabled() {
  if (!_modalEl) return;
  const input = _modalEl.querySelector('#applicant-input');
  const sendBtn = _modalEl.querySelector('#applicant-send');
  if (!input || !sendBtn) return;
  if (_sending) return; // _send owns the button label/state while a request is live
  const hasText = Boolean((input.value || '').trim());
  sendBtn.disabled = !hasText;
  sendBtn.style.opacity = hasText ? '' : '0.55';
  sendBtn.style.cursor = hasText ? '' : 'not-allowed';
}

// Prefill the composer with a starter prompt and focus it, leaving the send under
// the user's control (we don't auto-send — they can tweak first).
function _prefillComposer(text) {
  if (!_modalEl) return;
  const input = _modalEl.querySelector('#applicant-input');
  if (!input) return;
  input.value = text;
  input.focus();
  try { input.setSelectionRange(text.length, text.length); } catch { /* no-op */ }
  _syncSendEnabled();
}

// A few tappable starter prompts so a blank composer reads as an invitation, not a
// dead end (delight #10 / quick-wins #18). Tapping one prefills the composer.
const _STARTER_PROMPTS = [
  "Tell me what you're looking for",
  'What have you found so far?',
  'Change my criteria',
];

function _renderStarters() {
  const host = _modalEl && _modalEl.querySelector('#applicant-starters');
  if (!host) return;
  host.innerHTML = _STARTER_PROMPTS.map((p) =>
    `<button type="button" class="cal-btn applicant-starter" style="font-size:12px;">${esc(p)}</button>`
  ).join('');
  host.querySelectorAll('.applicant-starter').forEach((btn) => {
    btn.addEventListener('click', () => _prefillComposer(btn.textContent || ''));
  });
}

// Lifted from chatRenderer.addMessage (workspace/static/js/chatRenderer.js,
// ~line 1864) — its "standard single-bubble" path. addMessage itself is wired to
// the main `#chat-history` (model colors, footers, metrics, TTS, session) and
// can't be called from this modal, so we reuse its bubble markup + classes
// verbatim: a `.msg`/`.msg-user`/`.msg-ai` wrapper with `.role` + `.body`, the
// body rendered through markdownModule exactly like the main chat. This keeps the
// Job Assistant bubbles styled and behaving like the workspace chat.
function _appendMessage(role, content, { markdown = true } = {}) {
  const thread = _modalEl.querySelector('#applicant-thread');
  if (!thread) return null;

  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (role === 'user' ? 'msg-user' : 'msg-ai');

  const r = document.createElement('div');
  r.className = 'role';
  r.textContent = role === 'user' ? 'You' : 'Job Assistant';

  const b = document.createElement('div');
  b.className = 'body';
  if (markdown) {
    const text = markdownModule.squashOutsideCode(String(content == null ? '' : content));
    b.innerHTML = markdownModule.processWithThinking(text);
  } else {
    // Caller supplies trusted HTML (e.g. a "thinking…" placeholder).
    b.innerHTML = content;
  }
  wrap.dataset.raw = String(content == null ? '' : content);

  wrap.appendChild(r);
  wrap.appendChild(b);
  thread.appendChild(wrap);
  if (window.hljs) {
    wrap.querySelectorAll('pre code:not(.hljs)').forEach((el) => window.hljs.highlightElement(el));
  }
  wrap.scrollIntoView({ block: 'nearest' });
  return wrap;
}

// Update an existing AI bubble's body. `html` may include proposal/gap markup
// that must be inserted verbatim after the markdown-rendered reply.
function _setBubbleBody(wrap, replyText, extraHtml = '') {
  if (!wrap) return;
  const b = wrap.querySelector('.body');
  if (!b) return;
  const text = markdownModule.squashOutsideCode(String(replyText == null ? '' : replyText));
  b.innerHTML = markdownModule.processWithThinking(text) + (extraHtml || '');
  wrap.dataset.raw = String(replyText == null ? '' : replyText);
  if (window.hljs) {
    b.querySelectorAll('pre code:not(.hljs)').forEach((el) => window.hljs.highlightElement(el));
  }
}

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
          <div><strong>Criteria change</strong>: ${summary}</div>
          <button type="button" class="cal-btn cal-btn-primary applicant-confirm-criteria-btn"
                  data-idx="${i}">Confirm</button>
        </div>
      </div>`;
  }).join('');
  return `<div class="applicant-criteria-actions" style="margin-top:8px;">
      <div style="font-size:11px;opacity:0.7;margin-bottom:2px;">Proposed criteria update</div>${rows}
    </div>`;
}

// Does the actual POST + response/error rendering into an existing "thinking"
// bubble, WITHOUT appending a new user bubble. Shared by the initial send and
// by Retry, so retrying never duplicates the user's message in the thread.
async function _sendToBubble(message, thinking) {
  const input = _modalEl.querySelector('#applicant-input');
  const sendBtn = _modalEl.querySelector('#applicant-send');
  _sending = true;
  if (sendBtn) { sendBtn.disabled = true; sendBtn.textContent = '…'; }
  try {
    const res = await _post(`${API}/message`, { campaign_id: _activeCampaignId, message });
    const reply = res.message || '(no reply)';
    if (thinking) {
      const controls = res.control_actions || [];
      _setBubbleBody(thinking, reply,
        _renderGaps(res.gaps) +
        _renderProposals(res.proposed_changes) +
        _renderCriteriaActions(controls),
      );
      _wireProposalButtons(thinking, res.proposed_changes || []);
      _wireCriteriaButtons(thinking, controls);
    }
    // Only clear the composer once the request actually succeeded — on
    // failure the typed text must survive so the user isn't forced to retype.
    if (input && input.value === message) input.value = '';
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
          _sendToBubble(message, thinking);
        });
      }
    }
  } finally {
    _sending = false;
    if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = 'Send'; }
    _syncSendEnabled();
    if (input) input.focus();
  }
}

async function _send(text) {
  const message = (text || '').trim();
  if (!message || _sending) return;
  if (!_activeCampaignId) { _toast('Pick or create a job search first'); return; }
  _appendMessage('user', message);
  // A calm "thinking" pill instead of a bare word, so the wait reads as work, not a
  // hang (quick-wins #16 / delight #38). loadingHTML renders trusted markup.
  const thinking = _appendMessage('assistant', loadingHTML('Thinking…'), { markdown: false });
  await _sendToBubble(message, thinking);
}

function _wireProposalButtons(container, proposals) {
  container.querySelectorAll('.applicant-confirm-btn').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const idx = Number(btn.dataset.idx);
      const p = proposals[idx];
      if (!p) return;
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
        _toast(e.message || 'Could not save');
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
        _toast('Criteria updated');
      } catch (e) {
        btn.disabled = false;
        btn.textContent = 'Confirm';
        _toast(e.message || 'Could not save criteria change');
      }
    });
  });
}

// ── Pending job actions ──────────────────────────────────────────────────────
//
// The Pending Portal is the single source of truth for everything awaiting the
// user across all job searches (C4). Rather than re-render a second, divergent
// list here (which let the same item behave differently in two places), the chat
// surfaces a live count and a link that opens the Portal home base. The Portal
// owns the affordances, the rendering, and the resolve/answer wiring.

async function _loadPending(seq) {
  const host = _modalEl && _modalEl.querySelector('#applicant-pending');
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
      <div class="applicant-pending-link" style="border:1px solid var(--border);border-radius:6px;padding:8px 10px;display:flex;justify-content:space-between;gap:8px;align-items:center;">
        <div style="font-size:12px;">
          <strong>${esc(count)} item${count === 1 ? '' : 's'} need your attention</strong>
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

// ── Open / boot ──────────────────────────────────────────────────────────────

async function _loadCampaigns() {
  const data = await _fetchJSON(`${API}/campaigns`);
  _campaigns = Array.isArray(data && data.campaigns) ? data.campaigns : [];
  if (!_activeCampaignId && _campaigns.length) _activeCampaignId = _campaigns[0].id;
  return data;
}

export async function openApplicantChat() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  // Item #46: the panel is now docked over the real composer's band (see the
  // scaffold comments above) — dim the real composer for as long as it's open.
  _setComposerDimmed(true);
  const body = modal.querySelector('#applicant-chat-body');
  // Item #56: reuse the same spinner/pill the "thinking" reply already uses
  // instead of a bare text node, so opening the panel reads as work in
  // progress rather than a possible hang.
  body.innerHTML = loadingHTML();
  try {
    const data = await _loadCampaigns();
    if (data && data.engine_available === false) { _renderOffline(body); return; }
    if (!_campaigns.length) { _renderNoCampaign(body); return; }
    _renderConversation();
  } catch (e) {
    // 401 etc. — but most commonly the engine is unreachable.
    _renderOffline(body);
  }
}

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
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}

const applicantChatModule = { openApplicantChat };

// Expose for deep-links / other modules without creating import coupling.
try { window.applicantChatModule = applicantChatModule; } catch { /* no-op */ }

export default applicantChatModule;
