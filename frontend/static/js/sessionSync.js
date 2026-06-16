// Cross-device live sync for the chat.
//
// Every device that is viewing a session opens an SSE connection to
// /api/chat/events/{session}. When any device starts a run or saves a message,
// the server broadcasts a lightweight event and this listener reconciles the
// view (load the new message from history, attach to the live reply) WITHOUT
// disturbing the local draft or an in-flight local stream.
//
// Purely additive: it reuses chatModule.softReloadHistory / resumeStream /
// hasActiveStream and sessionModule.getCurrentSessionId. If those aren't present
// it simply does nothing, so it can never break normal chat.
(function () {
  'use strict';

  var API_BASE = (typeof window !== 'undefined' && window.API_BASE) || '';
  var es = null;
  var boundSession = null;
  var retry = 0;

  function chat() { return window.chatModule || null; }
  function currentSession() {
    var sm = window.sessionModule;
    return sm && sm.getCurrentSessionId ? sm.getCurrentSessionId() : null;
  }

  function parse(e) { try { return JSON.parse(e.data); } catch (_) { return {}; } }

  function handle(type, data) {
    var id = data && data.session;
    if (!id || id !== currentSession()) return;       // not the session we're viewing
    var cm = chat();
    if (!cm) return;
    if (cm.hasActiveStream && cm.hasActiveStream(id)) return; // our own activity — ignore the echo

    if (type === 'run-started') {
      // Another device sent a message: show it, then attach to the live reply.
      Promise.resolve(cm.softReloadHistory && cm.softReloadHistory(id)).then(function () {
        if (id === currentSession() && cm.resumeStream && !(cm.hasActiveStream && cm.hasActiveStream(id))) {
          cm.resumeStream(id);
        }
      });
    } else if (type === 'message-added') {
      if (cm.softReloadHistory) cm.softReloadHistory(id);
    }
  }

  function disconnect() {
    if (es) { try { es.close(); } catch (_) {} es = null; }
    boundSession = null;
  }

  function connect(id) {
    disconnect();
    if (!id) return;
    boundSession = id;
    try {
      es = new EventSource(API_BASE + '/api/chat/events/' + encodeURIComponent(id));
    } catch (_) { es = null; return; }
    es.addEventListener('connected', function () { retry = 0; });
    es.addEventListener('run-started', function (e) { handle('run-started', parse(e)); });
    es.addEventListener('message-added', function (e) { handle('message-added', parse(e)); });
    es.onerror = function () {
      // EventSource auto-reconnects on transient drops. Only if it hard-closes
      // (readyState CLOSED) do we re-establish, with capped backoff.
      if (es && es.readyState === 2) {
        var wait = Math.min(30000, 1000 * Math.pow(2, retry++));
        var target = id;
        setTimeout(function () {
          if (currentSession() === target && (!es || es.readyState === 2)) connect(target);
        }, wait);
      }
    };
  }

  // Follow the open session: (re)bind the stream whenever it changes.
  function tick() {
    var id = currentSession();
    if (id !== boundSession) {
      if (id) connect(id); else disconnect();
    }
  }

  function start() {
    setInterval(tick, 1500);
    tick();
    window.addEventListener('beforeunload', disconnect);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
