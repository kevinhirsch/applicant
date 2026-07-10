// static/js/shellWsTransport.js
//
// Cookbook shell/download progress transport: a WebSocket that runs the SAME
// command-stream the SSE path serves, with SSE kept as the automatic fallback.
//
// Today cookbookDownload.js POSTs /api/shell/stream and reads res.body.getReader()
// in a line-splitting loop. This module lets that EXACT loop stay unchanged:
// openShellStreamReader() returns a reader whose read() yields the SAME
// `data: {...}\n\n` SSE event strings (as Uint8Array chunks) — sourced from
// EITHER the /api/shell/ws WebSocket (preferred) or, when the socket can't
// connect, the SSE fallback (the deferred POST). It changes transport only.
//
// Durability: unlike chat, the shell stream has NO durable replay buffer — each
// run is a fresh subprocess bound to the live connection. So there is nothing to
// resume to: the WS is chosen at CONNECT time and, on a mid-stream drop, the
// reader simply ends (like a dropped SSE body) — it NEVER reconnects and NEVER
// re-runs the command. The command is executed by whichever transport wins: the
// WS `run` frame, or the deferred SSE POST — never both (no double-run).

// ── pure helpers (unit-tested headlessly by the JS suite via source slicing) ──

// Build the shell-WS URL from a location-like object. https→wss, http→ws.
function shellWsUrl(loc) {
  const scheme = (loc && loc.protocol === 'https:') ? 'wss:' : 'ws:';
  const host = (loc && loc.host) || '';
  return `${scheme}//${host}/api/shell/ws`;
}

// The single upstream verb: a `run` frame carrying the SAME payload the SSE POST
// body carries (command + optional timeout / use_pty / use_tmux). It is gated by
// the same admin check server-side, so the socket adds no authority beyond the
// existing /api/shell/stream POST.
function buildShellRunFrame(payload) {
  const p = (payload && typeof payload === 'object') ? payload : {};
  const frame = { type: 'run', command: String(p.command || '') };
  if (p.timeout !== undefined) frame.timeout = p.timeout;
  if (p.use_pty) frame.use_pty = true;
  if (p.use_tmux) frame.use_tmux = true;
  return frame;
}

// Classify a server WS message into a normalized shape the reader acts on:
//   { kind: 'chunk', data: '<sse string>' }  — one live SSE event
//   { kind: 'end' }                           — run finished (terminal sentinel)
//   { kind: 'error', error }                  — server rejected the run frame
//   { kind: 'ignore' }                        — unparseable / unknown
function parseShellWsMessage(raw) {
  let obj;
  try {
    obj = (typeof raw === 'string') ? JSON.parse(raw) : raw;
  } catch (_) {
    return { kind: 'ignore' };
  }
  if (!obj || typeof obj !== 'object') return { kind: 'ignore' };
  // The server's "run accepted, about to execute" ack — the FE commits to the WS
  // on this so a quiet command never lets the connect-timeout fire an SSE fallback
  // that would run the command twice. It carries no output.
  if (obj.type === 'ack') return { kind: 'ack' };
  if (obj.type === 'chunk' && typeof obj.data === 'string') {
    return { kind: 'chunk', data: obj.data };
  }
  if (obj.type === 'end') return { kind: 'end' };
  if (obj.type === 'error') return { kind: 'error', error: obj.error || 'error' };
  return { kind: 'ignore' };
}

// Does an SSE event string carry the terminal exit-code marker? The shell stream
// ends with `{"exit_code": N}`, after which the run is complete and a subsequent
// socket close is NORMAL — the reader must not treat it as a failure.
function shellChunkIsExit(sse) {
  return typeof sse === 'string' && /"exit_code"\s*:/.test(sse);
}

// ── browser transport (the JS suite slices only the pure helpers above) ───────

const SHELL_WS_CONNECT_TIMEOUT_MS = 4000;

// A reader that presents the res.body.getReader() interface (read()/cancel())
// but is fed by the shell-WS socket. Each read() resolves with a Uint8Array of
// the next SSE event string, or { done: true } at end/terminal failure. Unlike
// the chat reader there is NO reconnect — no durable buffer to resume — so a
// dropped socket ends the reader (the caller's loop then finishes normally).
class _ShellWsReader {
  constructor({ loc, payload, WebSocketImpl, onStatus, onActivity }) {
    this._loc = loc;
    this._payload = payload;
    this._WS = WebSocketImpl;
    this._onStatus = typeof onStatus === 'function' ? onStatus : () => {};
    this._onActivity = typeof onActivity === 'function' ? onActivity : () => {};
    this._enc = new TextEncoder();
    this._queue = [];          // pending decoded SSE strings
    this._waiters = [];        // pending read() resolvers
    this._done = false;        // terminal (saw end / exit / socket closed)
    this._sawExit = false;     // relayed an exit_code chunk — close is now normal
    this._ws = null;
  }

  _status(s) { try { this._onStatus(s); } catch (_) { /* no-op */ } }
  _activity() { try { this._onActivity(); } catch (_) { /* no-op */ } }

  _pushChunk(sse) {
    if (shellChunkIsExit(sse)) this._sawExit = true;
    this._activity();  // a live frame arrived — the WS is the authoritative feed
    if (this._waiters.length) {
      this._waiters.shift()({ done: false, value: this._enc.encode(sse) });
    } else {
      this._queue.push(sse);
    }
  }

  _finish() {
    if (this._done) return;
    this._done = true;
    while (this._waiters.length) this._waiters.shift()({ done: true, value: undefined });
  }

  // read() — drains queued events first, then awaits the next socket message.
  read() {
    if (this._queue.length) {
      const sse = this._queue.shift();
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

  // Resolves once the socket is open AND the server accepted the run frame (first
  // real payload), or rejects on timeout/close/error so the caller falls back to
  // SSE. Committing on the first frame guarantees the fallback POST is only issued
  // when the WS did NOT run the command — so the command never runs twice.
  waitForOpen(timeoutMs) {
    return new Promise((resolve, reject) => {
      if (typeof this._WS === 'undefined' || this._WS === null) { reject(new Error('no WebSocket')); return; }
      let settled = false;
      let ws;
      try {
        ws = new this._WS(shellWsUrl(this._loc));
      } catch (e) { reject(e); return; }
      this._ws = ws;
      const timer = setTimeout(() => {
        if (settled) return;
        settled = true;
        try { ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null; } catch (_) { /* no-op */ }
        try { ws.close(); } catch (_) { /* no-op */ }
        this._ws = null;
        reject(new Error('shell ws connect timeout'));
      }, timeoutMs);
      ws.onopen = () => {
        this._status('live');
        try { ws.send(JSON.stringify(buildShellRunFrame(this._payload))); } catch (_) { /* onclose handles it */ }
      };
      ws.onmessage = (ev) => {
        const msg = parseShellWsMessage(ev && ev.data);
        if (msg.kind === 'error') {
          if (!settled) { settled = true; clearTimeout(timer); try { ws.close(); } catch (_) { /* no-op */ } this._ws = null; reject(new Error(msg.error)); }
          return;
        }
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          // Rewire the live handlers now that we own the socket.
          ws.onmessage = (e2) => {
            const m = parseShellWsMessage(e2 && e2.data);
            if (m.kind === 'chunk') this._pushChunk(m.data);
            else if (m.kind === 'end') { this._sawExit = true; this._finish(); this._closeSocket(); }
            else if (m.kind === 'error') { this._finish(); this._closeSocket(); }
          };
          ws.onclose = () => this._onSocketClose();
          ws.onerror = () => { try { ws.close(); } catch (_) { /* no-op */ } };
          resolve(this);
        }
        // Deliver this first message too (don't drop it).
        if (msg.kind === 'chunk') this._pushChunk(msg.data);
        else if (msg.kind === 'end') { this._sawExit = true; this._finish(); this._closeSocket(); }
      };
      ws.onclose = () => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        this._ws = null;
        reject(new Error('shell ws closed before run accepted'));
      };
      ws.onerror = () => { try { ws.close(); } catch (_) { /* no-op */ } };
    });
  }

  // A socket close AFTER the run was accepted. There is no buffer to resume, so
  // we simply end the reader — the caller's loop finishes with whatever output
  // arrived (never a silent hang; the poll fallback then resumes via onActivity
  // lapse). A close after the exit-code marker is a normal end.
  _onSocketClose() {
    this._ws = null;
    this._finish();
  }
}

// Choose the stream transport for a Cookbook shell/download run. Tries the WS
// first; on success returns a WS-backed reader (the command runs server-side over
// the socket — the SSE POST is never issued). If the socket can't connect / the
// server rejects the run frame, defers to makeSse() (the SSE fallback POST),
// leaving behavior identical to before. The returned reader always exposes
// read()/cancel() with the SAME contract as res.body.getReader().
async function openShellStreamReader(opts) {
  const {
    loc, payload,
    WebSocketImpl = (typeof WebSocket !== 'undefined' ? WebSocket : null),
    connectTimeoutMs = SHELL_WS_CONNECT_TIMEOUT_MS,
    abortSignal = null,
    onStatus = () => {},
    onActivity = () => {},
    makeSse,
  } = opts || {};

  // No socket support → SSE straight away (the deferred POST runs the command).
  if (!WebSocketImpl) {
    try { onStatus('fallback'); } catch (_) { /* no-op */ }
    return makeSse();
  }

  const reader = new _ShellWsReader({ loc, payload, WebSocketImpl, onStatus, onActivity });
  // Wire abort → close the socket + end the reader. Closing the WS makes the
  // server notice the disconnect and kill the subprocess (same as an SSE abort).
  if (abortSignal) {
    const onAbort = () => { try { reader.cancel(); } catch (_) { /* no-op */ } };
    if (abortSignal.aborted) onAbort();
    else abortSignal.addEventListener('abort', onAbort, { once: true });
  }

  try {
    await reader.waitForOpen(connectTimeoutMs);
    // WS accepted the run — it is executing server-side. Do NOT issue the POST.
    return reader;
  } catch (_) {
    // Couldn't establish the socket (or server rejected) — fall back to the SSE
    // POST, which runs the command over the classic transport (never a double
    // run, because the WS never accepted it). Never a silent dead UI.
    try { reader.cancel(); } catch (_) { /* no-op */ }
    try { onStatus('fallback'); } catch (_) { /* no-op */ }
    return makeSse();
  }
}

const shellWsTransport = {
  shellWsUrl,
  buildShellRunFrame,
  parseShellWsMessage,
  shellChunkIsExit,
  openShellStreamReader,
  SHELL_WS_CONNECT_TIMEOUT_MS,
};

export {
  shellWsUrl,
  buildShellRunFrame,
  parseShellWsMessage,
  shellChunkIsExit,
  openShellStreamReader,
};

export default shellWsTransport;

try { window.shellWsTransport = shellWsTransport; } catch (_) { /* no-op */ }
