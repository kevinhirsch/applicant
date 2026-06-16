// Orwell presence strip (feature 0049 / C28) — the AMBIENT ground for lingering play.
//
// Renders the engine's Vault-free whereabouts() — the player's room, who is in it, and who is
// one room over — as a light, dismissible strip. It AUGMENTS the chat and never replaces it
// (ADR 0003 §4/§7): there is no click-to-move, no button that starts a scene or advances the
// game — the player still mills, asks "who's here?", and talks in PROSE, and the engine grounds
// the narration. Fail-open everywhere: no strip on empty/error/pre-game.
//
//   • GET /api/orwell/state        → gate on an active game (started)
//   • GET /api/orwell/whereabouts  → { room, present[], nearby[{room, present[]}] } | null
//
// Dismissing hides the strip until the player's ROOM changes (new ground re-surfaces it) —
// ambient information, never a nag.
(function () {
  "use strict";

  const POLL_MS = 25000;
  const ID = "orwell-presence";
  const DISMISS_KEY = "orwell-presence-dismissed-room";
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  let timer = null;
  let _failures = 0;
  function _pollDelay() { return Math.min(POLL_MS * Math.pow(2, _failures), 120000); }

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function roomLabel(room) {
    // "living-room" → "Living room" (the engine's ids are kebab-case room names).
    const words = String(room || "").replace(/-/g, " ");
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  function ensureEl() {
    let el = document.getElementById(ID);
    if (el) return el;
    el = document.createElement("div");
    el.id = ID;
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    el.style.cssText = [
      "position:fixed", /* E91/S11: the bottom-center slot owns the coordinates */
      "max-width:min(720px, calc(100vw - 24px))", "z-index:40",
      "background:var(--surface-2, rgba(24,24,28,0.92))", "color:var(--text-1, #ddd)",
      "border:1px solid var(--border-1, rgba(255,255,255,0.12))", "border-radius:10px",
      "padding:6px 12px", "font-size:12.5px", "line-height:1.45",
      "box-shadow:0 4px 14px rgba(0,0,0,0.35)", "display:none",
      "backdrop-filter:blur(6px)",
    ].join(";");
    el.innerHTML =
      "<span data-role='text'></span>" +
      "<button data-role='dismiss' class='ow-dismiss' aria-label='Hide the presence strip' " +
      "title='Hide (returns when you change rooms)' style='margin-left:10px'>×</button>";
    el.querySelector("[data-role='dismiss']").addEventListener("click", () => {
      try { localStorage.setItem(DISMISS_KEY, el.dataset.room || ""); } catch (_) {}
      el.style.display = "none";
    });
    document.body.appendChild(el);
    if (window.OrwellSlots) window.OrwellSlots.register(el, "bottom-center", { key: "presence" });
    return el;
  }

  function render(w) {
    const el = ensureEl();
    if (!w || !w.room) { el.style.display = "none"; return; }
    let dismissedRoom = null;
    try { dismissedRoom = localStorage.getItem(DISMISS_KEY); } catch (_) {}
    if (dismissedRoom === w.room) { el.style.display = "none"; return; } // hidden until the room changes
    el.dataset.room = w.room;

    const names = (list) => list.map((p) => p.name).join(", ");
    const here = w.present && w.present.length ? "with " + names(w.present) : "alone";
    const nearby = (w.nearby || [])
      .filter((n) => n.present && n.present.length)
      .map((n) => roomLabel(n.room) + " (" + names(n.present) + ")")
      .join(" · ");
    el.querySelector("[data-role='text']").textContent =
      "📍 " + roomLabel(w.room) + " — " + here + (nearby ? "  ·  nearby: " + nearby : "");
    el.style.display = "block";
  }

  async function tick() {
    try {
      if (document.hidden) return; // a hidden tab polls nothing (C18)
      const state = await getJSON("/api/orwell/state");
      if (!state || !state.started) { render(null); return; }
      const data = await getJSON("/api/orwell/whereabouts");
      render(data ? data.whereabouts : null);
      _failures = 0;
    } catch (_) {
      _failures += 1;
      if (window.OrwellReport) window.OrwellReport.fail("presence", "whereabouts-poll", _); // G11: fail open, never silent
      render(null); // fail OPEN: the strip simply isn't there
    } finally {
      timer = setTimeout(tick, _pollDelay());
    }
  }

  ready(() => {
    // Only under the game build (the reduced surface) — the full workspace skips the strip.
    if (document.body && document.body.dataset.gameBuild !== "1") return;
    tick();
    window.addEventListener("beforeunload", () => timer && clearTimeout(timer));
  });
})();
