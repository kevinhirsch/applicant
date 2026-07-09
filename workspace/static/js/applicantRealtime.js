// static/js/applicantRealtime.js
//
// Front-door realtime WebSocket client — Phase 1 backbone (realtime-websocket.md).
//
// ONE multiplexed duplex socket to the front-door endpoint
//   /api/applicant/realtime/ws
// speaking the frame envelope { chan, type, seq, data }. The server authenticates
// the upgrade by the applicant_session cookie and bridges to the engine; this
// client just multiplexes channels, dedups by per-channel seq, and reconnects
// with replay (resuming from the last seq it saw so there are no gaps or dupes).
//
// Phase 1 wires only the `presence` channel to a tiny "who's connected" indicator
// so the whole round-trip is reachable/operable in the front-door. Later phases
// add notif/agent/takeover handlers onto the SAME socket via onChannel().
//
// FALLBACK SEAM: the push socket is an OPTIMISATION over today's SSE + polling,
// never a hard dependency (honesty invariant: no silent dead UI). When the socket
// can't (re)establish, this shows a visible "reconnecting" state and then flips to
// a `fallback` state, invoking the onFallback hook so a later phase can degrade to
// SSE/polling. Phase 1 has no feature to fall back TO yet — this is just the seam
// plus the visible state.

// ── pure helpers (unit-tested headlessly by the JS suite via source slicing) ──

// Exponential backoff (ms) for reconnect attempts, capped. attempt 0 → base.
function nextBackoffMs(attempt) {
  const base = 500;
  const max = 30000;
  const ms = base * Math.pow(2, Math.max(0, attempt));
  return Math.min(max, ms);
}

// Build the `resume` query value ("chan:seq,chan:seq") from the per-channel
// last-seen seq map, skipping channels with nothing seen yet.
function buildResumeParam(lastSeq) {
  const parts = [];
  const map = lastSeq || {};
  for (const chan of Object.keys(map)) {
    const seq = map[chan];
    if (typeof seq === 'number' && seq >= 0) parts.push(`${chan}:${seq}`);
  }
  return parts.join(',');
}

// Build the WebSocket URL from a location-like object. https→wss, http→ws.
function realtimeWsUrl(loc, lastSeq, tab) {
  const scheme = (loc && loc.protocol === 'https:') ? 'wss:' : 'ws:';
  const host = (loc && loc.host) || '';
  let url = `${scheme}//${host}/api/applicant/realtime/ws`;
  const q = [];
  if (tab) q.push(`tab=${encodeURIComponent(tab)}`);
  const resume = buildResumeParam(lastSeq);
  if (resume) q.push(`resume=${encodeURIComponent(resume)}`);
  if (q.length) url += `?${q.join('&')}`;
  return url;
}

// Decide whether an incoming frame is new, updating the per-channel last-seq.
// Control (sys) frames and any seq < 0 are always accepted and never tracked, so
// a replayed feature frame the client already has (same chan+seq) is dropped —
// exactly-once delivery across a reconnect replay.
function applyIncoming(frame, lastSeq) {
  const map = lastSeq || {};
  if (!frame || typeof frame !== 'object') return { accept: false, lastSeq: map };
  const chan = frame.chan;
  const seq = frame.seq;
  if (chan === 'sys' || typeof seq !== 'number' || seq < 0) {
    return { accept: true, lastSeq: map };
  }
  const seen = (chan in map) ? map[chan] : -1;
  if (seq <= seen) return { accept: false, lastSeq: map };
  const next = Object.assign({}, map);
  next[chan] = seq;
  return { accept: true, lastSeq: next };
}

// Plain-language, white-label presence label for the indicator.
function presenceLabel(count) {
  const n = (typeof count === 'number' && count > 0) ? count : 1;
  if (n <= 1) return 'Just you';
  return `${n} devices connected`;
}

// Human label for a connection state (drives the indicator's title/tooltip).
function connectionStateLabel(state) {
  switch (state) {
    case 'open': return 'Live updates on';
    case 'connecting': return 'Connecting…';
    case 'reconnecting': return 'Reconnecting…';
    case 'fallback': return 'Live updates paused — using periodic refresh';
    default: return 'Offline';
  }
}

// The push channel is "live" only when the socket is fully open; every other
// state (connecting/reconnecting/fallback/idle) means the FE must keep — or fall
// back to — polling. The Portal listens for this to retire/restore its badge poll
// so there is never a silent dead UI (realtime-websocket.md Phase 2 fallback).
function realtimeLiveDetail(state) {
  return { live: state === 'open' };
}

// A `notif` frame arrived (a notification was created, or the pending-action set
// changed). Drive the SAME update path the poll used: refresh the Portal's badge +
// in-app notifications (which toasts genuinely-new ones via ui.js showToast and
// fans `applicant:pending-changed` out to the bell + rail through their existing
// listeners). Reuses applicantPortal.js's refreshBadge — it does NOT rebuild the
// Portal render, the bell, or the toast. When the Portal module isn't mounted on a
// given surface, still poke the shared cross-surface contract so bell/rail re-read.
function notifRefresh() {
  try {
    const portal = (typeof window !== 'undefined') && window.applicantPortalModule;
    if (portal && typeof portal.refreshBadge === 'function') {
      portal.refreshBadge();
      return true;
    }
  } catch { /* no-op */ }
  try {
    if (typeof document !== 'undefined' && typeof CustomEvent !== 'undefined') {
      document.dispatchEvent(new CustomEvent('applicant:pending-changed', { detail: {} }));
    }
  } catch { /* no-op */ }
  return false;
}

// ── connection (browser-only; the JS suite slices the pure helpers above) ─────

const WS_PATH = '/api/applicant/realtime';   // the front-door proxy this consumes
const MAX_RECONNECT_ATTEMPTS = 6;

class ApplicantRealtime {
  constructor(opts = {}) {
    this._loc = opts.location || (typeof window !== 'undefined' ? window.location : null);
    this._tab = opts.tab || _randomTab();
    this._lastSeq = {};
    this._handlers = {};          // chan -> fn(frame)
    this._stateCbs = [];          // fn(state)
    this._onFallback = opts.onFallback || null;
    this._ws = null;
    this._state = 'idle';
    this._attempts = 0;
    this._closedByUs = false;
    this._reconnectTimer = null;
  }

  onChannel(chan, fn) { this._handlers[chan] = fn; return this; }
  onState(fn) { this._stateCbs.push(fn); return this; }

  connect() {
    this._closedByUs = false;
    this._open();
    return this;
  }

  close() {
    this._closedByUs = true;
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
    if (this._ws) { try { this._ws.close(); } catch { /* no-op */ } }
  }

  // Send an upstream frame. The SERVER authorizes every upstream command; this is
  // pure transport and adds no authority.
  send(chan, type, data) {
    if (!this._ws || this._ws.readyState !== 1) return false;
    try {
      this._ws.send(JSON.stringify({ chan, type, seq: 0, data: data || {} }));
      return true;
    } catch { return false; }
  }

  _setState(state) {
    this._state = state;
    for (const cb of this._stateCbs) { try { cb(state); } catch { /* no-op */ } }
    // Tell the rest of the shell whether the push channel is live, so the Portal
    // can retire its badge poll while we're pushing and restore it on WS loss
    // (fallback). Never a silent dead UI.
    const detail = realtimeLiveDetail(state);
    // Persist the latest live flag so a listener that registers AFTER this edge
    // fired (e.g. the Portal is dynamically imported / re-mounted on SPA nav once
    // the socket is already `open`) can reconcile the current state on boot and
    // isn't stuck polling until the next transition. Level, not just edge.
    try {
      if (typeof window !== 'undefined') { window.__applicantRealtimeLive = !!detail.live; }
    } catch { /* no-op */ }
    try {
      if (typeof document !== 'undefined' && typeof CustomEvent !== 'undefined') {
        document.dispatchEvent(
          new CustomEvent('applicant:realtime', { detail }),
        );
      }
    } catch { /* no-op */ }
  }

  _open() {
    if (typeof WebSocket === 'undefined') { this._goFallback(); return; }
    this._setState(this._attempts === 0 ? 'connecting' : 'reconnecting');
    const url = realtimeWsUrl(this._loc, this._lastSeq, this._tab);
    let ws;
    try { ws = new WebSocket(url); } catch { this._scheduleReconnect(); return; }
    this._ws = ws;
    ws.onopen = () => { this._attempts = 0; this._setState('open'); };
    ws.onmessage = (ev) => this._onMessage(ev);
    ws.onclose = () => { this._ws = null; if (!this._closedByUs) this._scheduleReconnect(); };
    ws.onerror = () => { try { ws.close(); } catch { /* no-op */ } };
  }

  _onMessage(ev) {
    let frame;
    try { frame = JSON.parse(ev.data); } catch { return; }
    const res = applyIncoming(frame, this._lastSeq);
    this._lastSeq = res.lastSeq;
    if (!res.accept) return;
    if (frame.chan === 'sys') { this._onControl(frame); return; }
    const fn = this._handlers[frame.chan];
    if (fn) { try { fn(frame); } catch { /* no-op */ } }
  }

  _onControl(frame) {
    // Phase 1 control frames: hello (connected), error (rejected cmd / bad frame),
    // degraded (engine bridge unavailable → the FE should fall back).
    if (frame.type === 'degraded') this._goFallback();
  }

  _scheduleReconnect() {
    if (this._closedByUs) return;
    this._attempts += 1;
    if (this._attempts > MAX_RECONNECT_ATTEMPTS) { this._goFallback(); return; }
    this._setState('reconnecting');
    const delay = nextBackoffMs(this._attempts - 1);
    this._reconnectTimer = setTimeout(() => this._open(), delay);
  }

  _goFallback() {
    this._setState('fallback');
    if (typeof this._onFallback === 'function') {
      try { this._onFallback(); } catch { /* no-op */ }
    }
  }
}

function _randomTab() {
  try {
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
      const a = new Uint32Array(2);
      crypto.getRandomValues(a);
      return `${a[0].toString(36)}${a[1].toString(36)}`;
    }
  } catch { /* no-op */ }
  return `tab-${Math.random().toString(36).slice(2, 10)}`;
}

// ── presence indicator mount (reachability: the round-trip is operable) ───────

let _client = null;

function _ensureIndicator() {
  if (typeof document === 'undefined') return null;
  let el = document.getElementById('applicant-presence-indicator');
  if (el) return el;
  el = document.createElement('span');
  el.id = 'applicant-presence-indicator';
  el.className = 'applicant-presence-indicator';
  el.hidden = true;                       // stays hidden until the socket is live
  el.setAttribute('aria-live', 'polite');
  // Prefer sitting next to the notification bell; fall back to <body>.
  const host = document.getElementById('applicant-bell-wrap') || document.body;
  if (host) host.appendChild(el);
  return el;
}

function mountApplicantRealtime(opts = {}) {
  if (_client) return _client;
  const el = _ensureIndicator();
  _client = new ApplicantRealtime(opts);
  _client
    .onState((state) => {
      if (!el) return;
      el.hidden = (state === 'idle');
      el.dataset.state = state;
      el.title = connectionStateLabel(state);
    })
    .onChannel('presence', (frame) => {
      if (!el) return;
      const count = frame && frame.data ? frame.data.count : 1;
      el.hidden = false;
      el.textContent = presenceLabel(count);
    })
    // Phase 2 push: a notification/pending-action changed server-side. Drive the
    // same refresh the poll did — bell/rail/Portal update through their existing
    // listeners; the poll is retired while live and restored on loss (fallback).
    .onChannel('notif', () => { notifRefresh(); })
    .connect();
  return _client;
}

function _boot() {
  try { mountApplicantRealtime(); } catch { /* no-op: never break the shell */ }
}

if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _boot);
  } else {
    _boot();
  }
}

const applicantRealtimeModule = {
  ApplicantRealtime,
  mountApplicantRealtime,
  nextBackoffMs,
  buildResumeParam,
  realtimeWsUrl,
  applyIncoming,
  presenceLabel,
  connectionStateLabel,
  realtimeLiveDetail,
  notifRefresh,
  WS_PATH,
};

export {
  ApplicantRealtime,
  mountApplicantRealtime,
  nextBackoffMs,
  buildResumeParam,
  realtimeWsUrl,
  applyIncoming,
  presenceLabel,
  connectionStateLabel,
  realtimeLiveDetail,
  notifRefresh,
};

try { window.applicantRealtimeModule = applicantRealtimeModule; } catch { /* no-op */ }
try { window.mountApplicantRealtime = mountApplicantRealtime; } catch { /* no-op */ }
