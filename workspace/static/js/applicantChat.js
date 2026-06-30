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
import { esc, _toast, _fetchJSON, _post } from './applicantCore.js';

const API = '/api/applicant/chat';

let _modalEl = null;
let _modalA11yCleanup = null;
let _campaigns = [];
let _activeCampaignId = null;
let _sending = false;





// ── Campaign steering controls (#290,#182) ────────────────────────────
// Bidirectional assistant steering: start/pause/resume/run-now controls.

async function _renderCampaignControls(body) {
  const host = document.getElementById("applicant-controls");
  if (!host) return;
  _fetchJSON(`${API}/campaigns/${_activeCampaignId}/status`).then(data => {
    const running = data && data.running;
    const paused = data && data.paused;
    host.innerHTML = `
      <div class="applicant-controls" style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;padding:6px 0;border-bottom:1px solid var(--border);">
        ${running
          ? `<button type="button" class="cal-btn" id="ac-pause" title="Pause automated work">⏸ Pause</button>
             <button type="button" class="cal-btn" id="ac-run-now" title="Run a tick now">▶ Run now</button>`
          : paused
            ? `<button type="button" class="cal-btn cal-btn-primary" id="ac-resume" title="Resume automated work">▶ Resume</button>`
            : `<button type="button" class="cal-btn cal-btn-primary" id="ac-start" title="Start automated work">▶ Start</button>`}
        <span style="flex:1;"></span>
        <span style="font-size:11px;opacity:0.6;align-self:center;">
          ${running ? "Running" : paused ? "Paused" : "Idle"}
        </span>
      </div>`;
    _wireControlButtons(host, data);
  }).catch(() => { host.innerHTML = ""; });
}

function _wireControlButtons(host, status) {
  const start = host.querySelector("#ac-start");
  if (start) start.addEventListener("click", () => _runCampaignAction("start"));
  const pause = host.querySelector("#ac-pause");
  if (pause) pause.addEventListener("click", () => _runCampaignAction("pause"));
  const resume = host.querySelector("#ac-resume");
  if (resume) resume.addEventListener("click", () => _runCampaignAction("resume"));
  const runNow = host.querySelector("#ac-run-now");
  if (runNow) runNow.addEventListener("click", () => _runCampaignAction("run-now"));
}

async function _runCampaignAction(action) {
  const host = document.getElementById("applicant-controls");
  try {
    await _post(`${API}/campaigns/${_activeCampaignId}/${action}`, {});
    _toast(`Campaign ${action}ed`);
    if (host) _renderCampaignControls(document.body);
  } catch (e) {
    _toast(e.message || `Could not ${action} campaign`);
  }
}

// ── Modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-chat-modal';
  modal.className = 'modal hidden';
  modal.setAttribute('role', 'dialog');
  modal.setAttribute('aria-modal', 'true');
  modal.setAttribute('aria-label', 'Job Assistant');
  modal.innerHTML = `
    <div class="modal-content" style="--window-w:720px;display:flex;flex-direction:column;max-height:86vh;">
      <div class="modal-header">
        <h4>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:6px;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          Job Assistant
        </h4>
        <button class="close-btn" id="applicant-chat-close" title="Close">✖</button>
      </div>
      <div class="modal-body" id="applicant-chat-body" style="flex:1;overflow-y:auto;">
        <div class="hwfit-loading">Loading…</div>
      </div>
    </div>`;
  document.body.appendChild(modal);
  if (_modalA11yCleanup) _modalA11yCleanup();
  _modalA11yCleanup = uiModule.initModalA11y(modal, _close);
  modal.addEventListener('keydown', (e) => { if (e.key === 'Escape') _close(); });
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
}

// ── Empty / offline state ────────────────────────────────────────────────────

function _renderOffline(body) {
  body.innerHTML = `
    <div style="padding:28px 18px;text-align:center;opacity:0.75;">
      <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.5;margin-bottom:10px;"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      <div style="font-size:14px;margin-bottom:6px;">The Job Assistant isn't connected yet</div>
      <div style="font-size:12px;max-width:420px;margin:0 auto;">
        Connect a model in Settings to activate the assistant. Once a model is
        connected it can answer questions about your applications and surface
        anything that needs your input.
      </div>
    </div>`;
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
    <div id="applicant-composer" style="display:flex;gap:8px;align-items:flex-end;border-top:1px solid var(--border);padding-top:10px;position:sticky;bottom:0;background:var(--bg);">
      <textarea id="applicant-input" rows="2" placeholder="Ask about your applications, preferences, or what needs your attention…"
                style="flex:1;resize:vertical;padding:8px 10px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--fg);font-family:inherit;font-size:13px;"></textarea>
      <button type="button" class="cal-btn cal-btn-primary" id="applicant-send" title="Send to the assistant">Send</button>
    </div>`;

  const pick = body.querySelector('#applicant-campaign-pick');
  if (pick) {
    pick.addEventListener('change', () => {
      _activeCampaignId = pick.value;
      _renderThreadIntro();
      _loadPending();
    });
  }

  const input = body.querySelector('#applicant-input');
  const sendBtn = body.querySelector('#applicant-send');
  const send = () => _send(input.value);
  sendBtn.addEventListener('click', send);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); }
  });

  _renderThreadIntro();
  _loadPending();
  input.focus();
}

function _renderThreadIntro() {
  const thread = _modalEl.querySelector('#applicant-thread');
  if (!thread) return;
  thread.innerHTML = '';
  _appendMessage('assistant',
    'Hi — I can help with your job search. Ask me what needs your attention, ' +
    "or tell me about your preferences and I'll keep them up to date.");
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

async function _send(text) {
  const message = (text || '').trim();
  if (!message || _sending) return;
  if (!_activeCampaignId) { _toast('Pick or create a job search first'); return; }
  const input = _modalEl.querySelector('#applicant-input');
  const sendBtn = _modalEl.querySelector('#applicant-send');
  _sending = true;
  if (sendBtn) { sendBtn.disabled = true; sendBtn.textContent = '…'; }
  if (input) input.value = '';
  _appendMessage('user', message);
  const thinking = _appendMessage('assistant', '<span style="opacity:0.6;">thinking…</span>', { markdown: false });
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
  } catch (e) {
    if (thinking) {
      const b = thinking.querySelector('.body');
      if (b) b.innerHTML = `<span style="opacity:0.8;">Couldn't reach the assistant: ${esc(e.message || 'unknown error')}</span>`;
    }
  } finally {
    _sending = false;
    if (sendBtn) { sendBtn.disabled = false; sendBtn.textContent = 'Send'; }
    if (input) input.focus();
  }
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

async function _loadPending() {
  const host = _modalEl && _modalEl.querySelector('#applicant-pending');
  if (!host) return;
  try {
    // Cross-job-search count from the Portal proxy — the same source the rail
    // badge and the Portal home base use, so the number always agrees.
    const data = await _fetchJSON('/api/applicant/portal/pending');
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
  _campaigns = (data && data.campaigns) || [];
  if (!_activeCampaignId && _campaigns.length) _activeCampaignId = _campaigns[0].id;
  return data;
}

export async function openApplicantChat() {
  const modal = _ensureModalEl();
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
  const body = modal.querySelector('#applicant-chat-body');
  body.innerHTML = '<div class="hwfit-loading">Loading…</div>';
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
