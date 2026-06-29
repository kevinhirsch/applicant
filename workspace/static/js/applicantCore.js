// static/js/applicantCore.js
//
// Shared helpers for applicant browser modules.
// Import this once instead of copy-pasting esc / _toast / _fetchJSON / _post / _put.
//
// Usage:
//   import { esc, _toast, _fetchJSON, _post, _put } from './applicantCore.js';

import uiModule from './ui.js';

/** HTML-escape a string. Delegates to uiModule.esc when available. */
export function esc(s) {
  try {
    if (typeof uiModule.esc === 'function') return uiModule.esc(s);
  } catch { /* fall through */ }
  return (s == null ? '' : String(s)).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

/** Show a transient toast. Delegates to uiModule.showToast when available. */
export function _toast(msg) {
  try { uiModule.showToast(msg); } catch { /* no-op */ }
}

/** Fetch JSON from a URL with same-origin credentials and error handling. */
export async function _fetchJSON(url, opts = {}) {
  const res = await fetch(url, { credentials: 'same-origin', ...opts });
  let data = null;
  try { data = await res.json(); } catch { /* empty / non-JSON body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `${url} → ${res.status}`;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data || {};
}

/** POST JSON convenience wrapper. */
export function _post(url, body) {
  return _fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

/** PUT JSON convenience wrapper. */
export function _put(url, body) {
  return _fetchJSON(url, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}
