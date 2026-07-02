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

/**
 * Fetch JSON from a URL with same-origin credentials, a timeout, and error handling.
 * Timeout defaults to 15000ms (override via opts.timeoutMs; stripped before fetch).
 * Thrown errors carry .status + .kind ('auth'|'http'|'timeout'|'network') and .body.
 */
export async function _fetchJSON(url, opts = {}) {
  const { timeoutMs = 15000, ...fetchOpts } = opts;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(url, { credentials: 'same-origin', signal: controller.signal, ...fetchOpts });
  } catch (e) {
    const aborted = e && (e.name === 'AbortError' || controller.signal.aborted);
    const err = new Error(aborted
      ? `${url} → timed out`
      : (e && e.message ? e.message : `${url} → network error`));
    err.status = 0;
    err.kind = aborted ? 'timeout' : 'network';
    throw err;
  } finally {
    clearTimeout(timer);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty / non-JSON body */ }
  if (!res.ok) {
    const detail = (data && (data.detail || data.message)) || `${url} → ${res.status}`;
    const err = new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    err.status = res.status;
    err.body = data;
    err.kind = (res.status === 401 || res.status === 403) ? 'auth' : 'http';
    throw err;
  }
  return data || {};
}

/**
 * POST JSON convenience wrapper. `opts` is optional and merges into the
 * underlying _fetchJSON call (e.g. `{ timeoutMs }` to override the 15s
 * default for a call known to legitimately run longer, such as an
 * LLM-backed turn — see applicantChat.js's `/message` send).
 */
export function _post(url, body, opts = {}) {
  return _fetchJSON(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
    ...opts,
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

/** Map a thrown _fetchJSON error to a calm, user-facing message. */
export function errText(err) {
  const kind = err && err.kind;
  const status = err && err.status;
  if (kind === 'auth') return 'Your session expired — please sign in again.';
  if (kind === 'timeout') return 'This is taking a moment — the assistant is still working. Try again shortly.';
  if (kind === 'network' || status === 0) return 'Can’t reach the assistant right now.';
  return (err && err.message) ? err.message : 'Something went wrong.';
}

/**
 * Loading-state HTML string (spinner + label) for innerHTML. Reuses the app's
 * .hwfit-loading row and .spinner look; motion is CSS-driven so it honours
 * prefers-reduced-motion without any JS animation.
 */
export function loadingHTML(label = 'Loading…') {
  return `<div class="hwfit-loading" style="gap:8px;">`
    + `<span class="spinner" style="width:16px;height:16px;margin:0;border-width:2px;" aria-hidden="true"></span>`
    + `<span>${esc(label)}</span>`
    + `</div>`;
}

/** Calm empty-state HTML string: title + optional sub + optional CTA slot. */
export function emptyHTML(title, sub = '', ctaHTML = '') {
  return `<div class="applicant-empty" style="text-align:center;color:var(--fg-muted);padding:24px 12px;">`
    + `<div style="font-weight:600;color:var(--fg);">${esc(title)}</div>`
    + (sub ? `<div style="margin-top:6px;font-size:12px;">${esc(sub)}</div>` : '')
    + (ctaHTML ? `<div style="margin-top:12px;">${ctaHTML}</div>` : '')
    + `</div>`;
}

/** Error-state HTML string: message + optional retry button ([data-applicant-retry]). */
export function errorHTML(message, { retry = true } = {}) {
  return `<div class="applicant-error" style="text-align:center;color:var(--fg-muted);padding:24px 12px;">`
    + `<div style="color:var(--red);font-weight:600;">${esc(message)}</div>`
    + (retry
      ? `<div style="margin-top:12px;"><button class="cal-btn" type="button" data-applicant-retry>Try again</button></div>`
      : '')
    + `</div>`;
}

/** "Not set up yet" gated-state HTML string: reason + optional CTA slot. */
export function gatedHTML(reason, ctaHTML = '') {
  return `<div class="applicant-gated" style="text-align:center;color:var(--fg-muted);padding:24px 12px;">`
    + `<div style="font-weight:600;color:var(--fg);">Not set up yet</div>`
    + (reason ? `<div style="margin-top:6px;font-size:12px;">${esc(reason)}</div>` : '')
    + (ctaHTML ? `<div style="margin-top:12px;">${ctaHTML}</div>` : '')
    + `</div>`;
}

/** Wire a click on [data-applicant-retry] inside containerEl to fn. No-op if none. */
export function wireRetry(containerEl, fn) {
  if (!containerEl || typeof fn !== 'function') return;
  const btn = containerEl.querySelector('[data-applicant-retry]');
  if (btn) btn.addEventListener('click', () => fn());
}

/**
 * Call fn() now, then every intervalMs — but only while the tab is visible.
 * Pauses when hidden; on regaining visibility fires fn() once and resumes.
 * Returns stop() to clear the interval and remove the listener.
 */
export function pollVisible(fn, intervalMs) {
  let timer = null;
  const safe = () => { try { fn(); } catch { /* keep the loop alive */ } };
  const start = () => { if (timer == null) timer = setInterval(safe, intervalMs); };
  const stopTimer = () => { if (timer != null) { clearInterval(timer); timer = null; } };
  const onVis = () => {
    if (document.visibilityState === 'visible') { safe(); start(); }
    else stopTimer();
  };
  document.addEventListener('visibilitychange', onVis);
  safe();
  if (document.visibilityState === 'visible') start();
  return function stop() {
    stopTimer();
    document.removeEventListener('visibilitychange', onVis);
  };
}
