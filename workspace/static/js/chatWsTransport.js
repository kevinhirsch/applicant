// static/js/chatWsTransport.js
//
// Workspace-native chat streaming transport: a WebSocket that carries the SAME
// stream the SSE chat path serves, with SSE kept as the automatic fallback.
//
// Today chat.js POSTs /api/chat_stream (which starts a DETACHED agent_runs run
// and returns an SSE StreamingResponse) and reads res.body.getReader() in a big
// line-splitting loop. This module lets that EXACT loop stay byte-for-byte
// unchanged: openChatStreamReader() returns a reader whose read() yields the
// SAME `data: {...}\n\n` SSE event strings (as Uint8Array chunks) — sourced from
// EITHER the /api/chat/ws WebSocket (preferred) or, when the socket can't
// (re)connect, res.body (the SSE fallback). The WS only changes transport; it is
// pure read-transport and adds no send authority (SEND stays on the POST).
//
// Durability: the WS relays agent_runs' per-session replay buffer. A mid-stream
// socket drop reconnects with a `resume` offset (events already delivered) so it
// replays the buffered tail then goes live — gap-free, dupe-free — exactly like
// the SSE /api/chat/resume reconnect, because both read the same buffer. If the
// socket ultimately won't re-establish, the reader ends without a [DONE] and the
// caller's existing recovery path takes over (never a silent dead UI).

// ── pure helpers (unit-tested headlessly by the JS suite via source slicing) ──

// Build the chat-WS URL from a location-like object. https→wss, http→ws.
// Carries the session id and the replay `resume` offset (events already seen).
function chatWsUrl(loc, sessionId, resume) {
  const scheme = (loc && loc.protocol === 'https:') ? 'wss:' : 'ws:';
  const host = (loc && loc.host) || '';
  let url = `${scheme}//${host}/api/chat/ws`;
  const q = [];
  if (sessionId) q.push(`session=${encodeURIComponent(sessionId)}`);
  if (typeof resume === 'number' && resume > 0) q.push(`resume=${resume}`);
  if (q.length) url += `?${q.join('&')}`;
  return url;
}

// The single upstream verb: subscribe to a session's run at a replay offset.
// PURE TRANSPORT — it selects what to READ; it never sends a chat message (that
// stays on POST /api/chat_stream), so the socket adds no authority.
function buildChatSubscribeFrame(sessionId, resume) {
  const r = (typeof resume === 'number' && resume > 0) ? resume : 0;
  return { type: 'subscribe', session: String(sessionId || ''), resume: r };
}

// Classify a server WS message into a normalized shape the reader acts on:
//   { kind: 'chunk', data: '<sse string>' }  — one buffered/live SSE event
//   { kind: 'end' }                           — run finished (terminal sentinel)
//   { kind: 'error', error }                  — server rejected the subscribe
//   { kind: 'ignore' }                        — unparseable / unknown
function parseChatWsMessage(raw) {
  let obj;
  try {
    obj = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  } catch (_) {
    return { kind: 'ignore' };
  }
  if (!obj || typeof obj !== 'object') return { kind: 'ignore' };
  if (obj.type === 'chunk' && typeof obj.data === 'string') {
    return { kind: 'chunk', data: obj.data };
  }
  if (obj.type === 'end') return { kind: 'end' };
  if (obj.type === 'error') return { kind: 'error', error: obj.error || 'error' };
  return { kind: 'ignore' };
}

// Does an SSE event string carry the terminal [DONE] sentinel? The chat loop
// breaks on `data: [DONE]`, so once we've relayed one the run is complete and a
// subsequent socket close is NORMAL — the transport must not try to reconnect.
function chatChunkIsDone(sse) {
  return typeof sse === 'string' && sse.indexOf('data: [DONE]') !== -1;
}

// Exponential backoff (ms) for chat-WS reconnect attempts, capped. attempt 0 →
// base. Mirrors applicantRealtime.nextBackoffMs so reconnect timing is uniform.
function chatWsBackoffMs(attempt) {
  const base = 500;
  const max = 8000;
  const ms = base * Math.pow(2, Math.max(0, attempt));
  return Math.min(max, ms);
}

// ── browser transport (the JS suite slices only the pure helpers above) ───────

const CHAT_WS_CONNECT_TIMEOUT_MS = 4000;
const CHAT_WS_MAX_RECONNECTS = 5;

// A reader that presents the res.body.getReader() interface (read()/cancel())
// but is fed by the chat-WS socket. Each read() resolves with a Uint8Array of
// the next SSE event string, or { done: true } at end/terminal failure. Handles
// its own reconnect+replay so the caller's loop is unchanged.
class _ChatWsReader {
  constructor({ loc, sessionId, WebSocketImpl, onStatus }) {
    this._loc = loc;
    this._sessionId = sessionId;
    this._WS = WebSocketImpl;
    this._onStatus = typeof onStatus === 'function' ? onStatus : () => {};
    this._enc = new TextEncoder();
    this._queue = [];          // pending decoded SSE strings
    this._waiters = [];        // pending read() resolvers
    this._delivered = 0;       // events handed to the caller (resume offset)
    this._done = false;        // terminal (saw end / [DONE] / gave up)
    this._sawDone = false;     // relayed a [DONE] chunk — close is now normal
    this._ws = null;
    this._attempts = 0;
    this._reconnectTimer = null;
  }

  _status(s) { try { this._onStatus(s); } catch (_) { /* no-op */ } }

  _pushChunk(sse) {
    if (chatChunkIsDone(sse)) this._sawDone = true;
    if (this._waiters.length) {
      const w = this._waiters.shift();
      this._delivered += 1;
      w({ done: false, value: this._enc.encode(sse) });
    } else {
      this._queue.push(sse);
    }
  }

  _finish() {
    if (this._done) return;
    this._done = true;
    if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
    while (this._waiters.length) this._waiters.shift()({ done: true, value: undefined });
  }

  // The server resume offset on reconnect: every event we've RECEIVED, not just
  // the ones drained by read(). `_delivered` advances only on drain, so a chunk
  // buffered in `_queue` (received but not yet read) would otherwise be replayed
  // by the server AND re-emitted from the queue — a duplicate. Counting the
  // buffered tail here makes the resume gap-free and dupe-free. The sum is
  // invariant under a concurrent drain (delivered +1, queue -1), so it is stable
  // between the URL and the subscribe frame.
  _resumeOffset() {
    return this._delivered + this._queue.length;
  }

  // read() — drains queued events first, then awaits the next socket message.
  read() {
    if (this._queue.length) {
      const sse = this._queue.shift();
      this._delivered += 1;
      return Promise.resolve({ done: false, value: this._enc.encode(sse) });
    }
    if (this._done) return Promise.resolve({ done: true, value: undefined });
    return new Promise((resolve) => { this._waiters.push(resolve); });
  }

  cancel() {
    this._finish();
    this._closeSocket();
    return Promise.resolve();
  }

  _closeSocket() {
    if (this._ws) {
      try { this._ws.onopen = this._ws.onmessage = this._ws.onclose = this._ws.onerror = null; } catch (_) { /* no-op */ }
      try { this._ws.close(); } catch (_) { /* no-op */ }
      this._ws = null;
    }
  }

  _onSocketClose() {
    this._ws = null;
    if (this._done || this._sawDone) { this._finish(); return; }
    // Unexpected drop before the run finished — reconnect + replay the tail.
    this._attempts += 1;
    if (this._attempts > CHAT_WS_MAX_RECONNECTS) {
      // Give up on the socket: end the reader WITHOUT a [DONE] so the caller's
      // existing "stream closed before completion" recovery path takes over.
      this._status('fallback');
      this._finish();
      return;
    }
    this._status('reconnecting');
    const delay = chatWsBackoffMs(this._attempts - 1);
    this._reconnectTimer = setTimeout(() => this._open(), delay);
  }

  // Open (or reopen) the socket, resuming from what we've already delivered.
  _open() {
    if (this._done) return;
    let ws;
    try {
      ws = new this._WS(chatWsUrl(this._loc, this._sessionId, this._resumeOffset()));
    } catch (_) {
      this._onSocketClose();
      return;
    }
    this._ws = ws;
    ws.onopen = () => {
      // NOTE: do NOT reset _attempts here. A proxy/server can accept the socket
      // (fire onopen) then drop it before any payload; resetting the budget on
      // bare open would let that accept-then-drop cycle reconnect forever and
      // never reach the CHAT_WS_MAX_RECONNECTS fallback. The budget is only
      // cleared once a REAL frame arrives (onmessage), which proves the stream works.
      this._status('live');
      try { ws.send(JSON.stringify(buildChatSubscribeFrame(this._sessionId, this._resumeOffset()))); } catch (_) { /* onclose handles it */ }
    };
    ws.onmessage = (ev) => {
      const msg = parseChatWsMessage(ev && ev.data);
      // A real server frame arrived — the stream is genuinely alive, so reset the
      // reconnect budget (a later drop gets its own fresh set of attempts).
      if (msg.kind === 'chunk' || msg.kind === 'end' || msg.kind === 'error') this._attempts = 0;
      if (msg.kind === 'chunk') this._pushChunk(msg.data);
      else if (msg.kind === 'end') { this._sawDone = true; this._finish(); this._closeSocket(); }
      else if (msg.kind === 'error') { this._finish(); this._closeSocket(); }
    };
    ws.onerror = () => { try { ws.close(); } catch (_) { /* no-op */ } };
    ws.onclose = () => this._onSocketClose();
  }

  // Resolves once the socket is open (WS chosen) or rejects on failure so the
  // caller can fall back to SSE. Only the FIRST connect gates the choice; later
  // drops reconnect transparently.
  waitForOpen(timeoutMs) {
    return new Promise((resolve, reject) => {
      if (typeof this._WS === 'undefined' || this._WS === null) { reject(new Error('no WebSocket')); return; }
      let settled = false;
      let ws;
      try {
        ws = new this._WS(chatWsUrl(this._loc, this._sessionId, 0));
      } catch (e) { reject(e); return; }
      this._ws = ws;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try { ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null; } catch (_) { /* no-op */ }
        try { ws.close(); } catch (_) { /* no-op */ }
        this._ws = null;
        reject(new Error('chat ws connect timeout'));
      }, timeoutMs);
      ws.onopen = () => {
        this._attempts = 0;
        this._status('live');
        try { ws.send(JSON.stringify(buildChatSubscribeFrame(this._sessionId, 0))); } catch (_) { /* onclose handles it */ }
      };
      ws.onmessage = (ev) => {
        // First real payload proves the subscribe was accepted — commit to WS.
        const msg = parseChatWsMessage(ev && ev.data);
        if (msg.kind === 'error') {
          if (!settled) { settled = true; clearTimeout(timer); try { ws.close(); } catch (_) { /* no-op */ } this._ws = null; reject(new Error(msg.error)); }
          return;
        }
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          // Rewire the live handlers now that we own the socket.
          ws.onmessage = (e2) => {
            const m = parseChatWsMessage(e2 && e2.data);
            if (m.kind === 'chunk') this._pushChunk(m.data);
            else if (m.kind === 'end') { this._sawDone = true; this._finish(); this._closeSocket(); }
            else if (m.kind === 'error') { this._finish(); this._closeSocket(); }
          };
          ws.onclose = () => this._onSocketClose();
          ws.onerror = () => { try { ws.close(); } catch (_) { /* no-op */ } };
          resolve(this);
        }
        // Deliver this first message too (don't drop it).
        if (msg.kind === 'chunk') this._pushChunk(msg.data);
        else if (msg.kind === 'end') { this._sawDone = true; this._finish(); this._closeSocket(); }
      };
      ws.onclose = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this._ws = null;
        reject(new Error('chat ws closed before open'));
      };
      ws.onerror = () => { try { ws.close(); } catch (_) { /* no-op */ } };
    });
  }
}

// Choose the stream transport for a just-started chat run. Tries the chat WS
// first; on success returns a WS-backed reader (and drops the redundant SSE
// subscriber by cancelling res.body). If the socket can't connect in time,
// returns res.body.getReader() (the SSE fallback), leaving res.body intact.
//
// The returned object always exposes read()/cancel() with the SAME contract as
// res.body.getReader(), so the caller's streaming loop is unchanged.
async function openChatStreamReader(opts) {
  const {
    res, loc, sessionId,
    WebSocketImpl = (typeof WebSocket !== 'undefined' ? WebSocket : null),
    connectTimeoutMs = CHAT_WS_CONNECT_TIMEOUT_MS,
    abortSignal = null,
    onStatus = () => {},
  } = opts || {};

  // No socket support (or no session to subscribe to) → SSE straight away.
  if (!WebSocketImpl || !sessionId) {
    try { onStatus('fallback'); } catch (_) { /* no-op */ }
    return res.body.getReader();
  }

  const reader = new _ChatWsReader({ loc, sessionId, WebSocketImpl, onStatus });
  // Wire abort → close the socket + end the reader (the HTTP Stop separately
  // cancels the detached server run via /api/chat/stop).
  if (abortSignal) {
    const onAbort = () => { try { reader.cancel(); } catch (_) { /* no-op */ } };
    if (abortSignal.aborted) onAbort();
    else abortSignal.addEventListener('abort', onAbort, { once: true });
  }

  try {
    await reader.waitForOpen(connectTimeoutMs);
    // WS is live — drop the SSE subscriber we no longer need. The detached run
    // and its buffer are untouched; the WS replays from the buffer's start.
    try { if (res.body && res.body.cancel) res.body.cancel(); } catch (_) { /* no-op */ }
    return reader;
  } catch (_) {
    // Couldn't establish the socket in time — fall back to the SSE body we
    // already hold (never a silent dead UI).
    try { reader.cancel(); } catch (_) { /* no-op */ }
    try { onStatus('fallback'); } catch (_) { /* no-op */ }
    return res.body.getReader();
  }
}

const chatWsTransport = {
  chatWsUrl,
  buildChatSubscribeFrame,
  parseChatWsMessage,
  chatChunkIsDone,
  chatWsBackoffMs,
  openChatStreamReader,
  CHAT_WS_CONNECT_TIMEOUT_MS,
  CHAT_WS_MAX_RECONNECTS,
};

export {
  chatWsUrl,
  buildChatSubscribeFrame,
  parseChatWsMessage,
  chatChunkIsDone,
  chatWsBackoffMs,
  openChatStreamReader,
};

export default chatWsTransport;

try { window.chatWsTransport = chatWsTransport; } catch (_) { /* no-op */ }
