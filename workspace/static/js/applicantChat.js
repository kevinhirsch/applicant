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

const API = '/api/applicant/chat';

let _modalEl = null;
let _campaigns = [];
let _activeCampaignId = null;
let _sending = false;

function esc(s) {
  // Prefer the shared helper; fall back to a local escape so this module never
  // throws if ui.js changes shape.
  try {
    if (typeof uiModule.esc === 'function') return uiModule.esc(s);
  } catch { /* fall through */ }
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function _toast(msg) {
  try { uiModule.showToast(msg); } catch { /* no-op */ }
}

async function _fetchJSON(url, opts = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...opts });
  let data = null;
  try { data = await res.json(); } catch { /* empty / non-JSON body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `${url} → ${res.status}`;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    throw err;
  }
  return data || {};
}

function _post(url, body) {
  return _fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

// ── Modal scaffold ──────────────────────────────────────────────────────────

function _ensureModalEl() {
  if (_modalEl) return _modalEl;
  const modal = document.createElement('div');
  modal.id = 'applicant-chat-modal';
  modal.className = 'modal hidden';
  modal.innerHTML = `
    <div class="modal-content" style="max-width:720px;width:96%;display:flex;flex-direction:column;max-height:86vh;">
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
  modal.querySelector('#applicant-chat-close').addEventListener('click', _close);
  modal.addEventListener('click', (e) => { if (e.target === modal) _close(); });
  _modalEl = modal;
  return modal;
}

function _close() {
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
        <input type="text" id="applicant-new-campaign" placeholder="e.g. Backend roles 2026"
               style="flex:1;padding:7px 9px;border:1px solid var(--border);border-radius:4px;background:var(--bg);color:var(--fg);" />
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
      <span style="font-size:11px;opacity:0.7;">Job search</span>
      <select id="applicant-campaign-pick" style="width:100%;">${opts}</select>
    </label>`;
}

function _renderConversation() {
  const body = _modalEl.querySelector('#applicant-chat-body');
  body.innerHTML = `
    ${_campaignPicker()}
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
      ? `<button type="button" class="cal-btn cal-btn-primary applicant-confirm-btn" data-idx="${i}" style="font-size:11px;padding:2px 10px;">Confirm</button>`
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
      _setBubbleBody(thinking, reply, _renderGaps(res.gaps) + _renderProposals(res.proposed_changes));
      _wireProposalButtons(thinking, res.proposed_changes || []);
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
        <button type="button" class="cal-btn cal-btn-primary" id="applicant-open-portal" style="font-size:11px;padding:2px 10px;flex-shrink:0;">Open Pending</button>
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
  const btn = document.getElementById('rail-assistant');
  if (!btn || btn._applicantWired) return;
  btn._applicantWired = true;
  btn.addEventListener('click', () => {
    // Respect the feature-activation lock — if app.js greyed the launcher
    // (engine/model not ready) its capture-phase guard already stopped this
    // handler; reaching here means the section is active.
    openApplicantChat();
  });
}

function _boot() {
  _wireLauncher();
  // The rail button may be (re)rendered after boot; retry briefly so the
  // launcher always gets wired without a hard dependency on load order.
  let tries = 0;
  const iv = setInterval(() => {
    tries += 1;
    _wireLauncher();
    if (document.getElementById('rail-assistant')?._applicantWired || tries > 20) {
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
