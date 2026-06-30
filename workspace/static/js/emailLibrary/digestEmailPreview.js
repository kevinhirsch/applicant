// static/js/emailLibrary/digestEmailPreview.js
//
// Digest email preview (#402 / FR-DIG-2): fetch the engine-rendered digest email
// (subject + HTML) through the front-door proxy and show it exactly as it will be
// sent, in a sandboxed iframe. This is the JS consumer that renders the rendered
// digest-email HTML — backed by the existing client method `digest_email` and the
// `/api/applicant/email/digest/{campaign_id}/email` proxy.
//
// The engine escapes every untrusted scraped cell and href-allowlists links in
// render_email, and the iframe is fully sandboxed (no scripts, no same-origin), so
// the previewed email can never touch or script the app DOM.

import { showToast } from '../ui.js';

const API_BASE = window.API_BASE || '';

function _esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Fetch the rendered digest-email payload for a campaign through the email proxy.
// Path: /api/applicant/email/digest/{campaign_id}/email  → { subject, html }.
async function fetchDigestEmail(campaignId) {
  const r = await fetch(
    `${API_BASE}/api/applicant/email/digest/${encodeURIComponent(campaignId)}/email`,
    { credentials: 'same-origin' },
  );
  let payload = null;
  try { payload = await r.json(); } catch (_) { payload = null; }
  if (!r.ok) {
    const detail = (payload && (payload.detail || payload.message)) || `Request failed (${r.status})`;
    const err = new Error(typeof detail === 'string' ? detail : 'Request failed');
    err.status = r.status;
    throw err;
  }
  return payload || {};
}

function _close() {
  const existing = document.getElementById('applicant-digest-email-overlay');
  if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
  document.removeEventListener('keydown', _onKey);
}

function _onKey(e) {
  if (e.key === 'Escape') { e.preventDefault(); _close(); }
}

let _busy = false;

// Render the digest email as it will be sent, in a sandboxed-iframe modal.
export async function showDigestEmailPreview(campaignId) {
  if (_busy) return;
  if (!campaignId) { showToast('Pick a job search first.'); return; }
  _busy = true;
  try {
    const data = await fetchDigestEmail(campaignId);
    const subject = data.subject ? String(data.subject) : 'Your daily digest';
    const emailHtml = data.html ? String(data.html) : '<p>No content yet.</p>';
    _close();

    const overlay = document.createElement('div');
    overlay.id = 'applicant-digest-email-overlay';
    overlay.className = 'modal';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Email preview');
    // Explicit overlay positioning so it shows regardless of the app's modal
    // show/hide class state (the base `.modal` rule can default to display:none).
    overlay.style.cssText =
      'display:flex;align-items:center;justify-content:center;position:fixed;'
      + 'inset:0;z-index:100000;background:rgba(0,0,0,0.55);';
    overlay.innerHTML = `
      <div class="modal-content" style="max-width:680px;width:92%;display:flex;flex-direction:column;max-height:84vh;">
        <div class="modal-header" style="display:flex;align-items:center;">
          <h4 style="margin:0;">Preview email</h4>
          <button type="button" class="memory-toolbar-btn" id="applicant-digest-email-close" style="margin-left:auto;">Close</button>
        </div>
        <div class="modal-body" style="display:flex;flex-direction:column;gap:6px;overflow:auto;">
          <div class="memory-desc" style="padding:8px 4px 4px;font-size:12px;"><strong>Subject:</strong> ${_esc(subject)}</div>
          <iframe title="Email preview" sandbox=""
                  style="flex:1 1 auto;width:100%;min-height:360px;border:1px solid var(--border-color,#444);border-radius:6px;background:#fff;"></iframe>
        </div>
      </div>`;
    // Assign srcdoc via the DOM (not the template string) so the email markup is
    // never parsed in the app document — only inside the sandboxed frame.
    overlay.querySelector('iframe').setAttribute('srcdoc', emailHtml);
    document.body.appendChild(overlay);

    const closeBtn = overlay.querySelector('#applicant-digest-email-close');
    closeBtn.addEventListener('click', _close);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) _close(); });
    document.addEventListener('keydown', _onKey);
    closeBtn.focus();
  } catch (e) {
    showToast(e.message || 'Could not load the email preview right now.');
  } finally {
    _busy = false;
  }
}

export default { showDigestEmailPreview, fetchDigestEmail };
