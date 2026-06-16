// Orwell engine-status banner — VISIBLE error reporting when the game engine has a problem.
// The in-character "live feeds are down" chat line keeps players in the show, but the operator (and
// a confused player) needs an honest, out-of-character signal that something is actually broken. This
// is that signal: a small fixed banner driven by /api/orwell/health with two severities:
//   • RED   — the engine is unreachable (connection refused / timeout / wrong URL);
//   • AMBER — the engine is up but a recent tool call FAILED (`lastError`: a technical problem like a
//     corrupt-save 500 or a failing action), naming the tool + reason so it's actionable.
// Self-contained, fail-open (if its own fetch fails, it shows the warning), no deps.
(function () {
  "use strict";

  const POLL_MS = 15000;
  const ID = "orwell-engine-status";
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  let timer = null;
  let dismissedKey = null; // the exact message the user dismissed — reshow only if it changes

  function ensureBanner() {
    let el = document.getElementById(ID);
    if (el) return el;
    el = document.createElement("div");
    el.id = ID;
    el.setAttribute("role", "alert");
    el.innerHTML = `
      <style>
        #${ID} {
          position: fixed; top: 0; left: 0; right: 0; z-index: 11000; display: none;
          color: #fff; font-family: 'Fira Code', ui-monospace, monospace;
          font-size: .76rem; line-height: 1.4; padding: .5rem .8rem; text-align: center;
          box-shadow: 0 2px 10px rgba(0,0,0,.4);
        }
        #${ID}.oes-down { background: #7f1d1d; }
        #${ID}.oes-degraded { background: #92400e; }
        #${ID} b { letter-spacing: .03em; }
        #${ID} .oes-reason { opacity: .85; }
        /* F6 tail: the dismiss is the shared .ow-dismiss affordance (kit CSS),
           positioned for the banner. */
        #${ID} .oes-x { position: absolute; right: .5rem; top: .15rem; }
      </style>
      <span><b class="oes-title"></b> <span class="oes-reason"></span></span>
      <button type="button" class="oes-x ow-dismiss" title="Dismiss" aria-label="Dismiss">×</button>`;
    document.body.appendChild(el);
    el.querySelector(".oes-x").addEventListener("click", () => {
      dismissedKey = el.querySelector(".oes-reason").textContent || "";
      el.style.display = "none";
    });
    return el;
  }

  function show(kind, title, reason) {
    const el = ensureBanner();
    if (dismissedKey && dismissedKey === reason) return; // already waved off this exact problem
    el.classList.toggle("oes-down", kind === "down");
    el.classList.toggle("oes-degraded", kind === "degraded");
    el.querySelector(".oes-title").textContent = title;
    el.querySelector(".oes-reason").textContent = reason;
    el.style.display = "block";
  }
  function hide() {
    dismissedKey = null; // healthy again — a future problem should always reshow
    const el = document.getElementById(ID);
    if (el) el.style.display = "none";
  }

  // G8: while createCharacter is in flight (health reports busy:"creating"), a slow or even
  // timed-out engine probe is casting being finalized — NOT an outage. Hold in-fiction (amber),
  // never the red "engine unavailable" banner.
  function showHolding() {
    show("degraded", "🎬 Production is building the house…", "Casting is being finalized — the live feeds return in a moment.");
  }

  async function refresh() {
    try {
      const r = await fetch("/api/orwell/health", { credentials: "same-origin" });
      if (!r.ok) { show("down", "⚠ Big Brother engine unavailable.", "The app couldn't reach the game service. The show can't load until it's back."); return; }
      const d = await r.json();
      const busy = !!(d && d.busy === "creating"); // G8: createCharacter in flight
      if (!d || !d.engine) {
        if (busy) { showHolding(); return; } // a probe timeout DURING creation is not an outage
        const reason = (d && d.error ? "Reason: " + d.error + " " : "") + (d && d.engineUrl ? "(" + d.engineUrl + ") " : "");
        show("down", "⚠ Big Brother engine unavailable.", reason + "The show can't load until it's back.");
      } else if (d.lastError && d.lastError.error) {
        if (busy) { showHolding(); return; } // mid-creation hiccups hold in-fiction too
        // Engine reachable, but a recent call failed — a technical problem worth reporting honestly.
        const le = d.lastError;
        show("degraded", "⚠ Big Brother engine reported a problem.", (le.tool ? le.tool + ": " : "") + le.error);
      } else {
        hide();
      }
    } catch (_) {
      // The FE route itself failed — surface the most likely truth rather than going silent.
      if (window.OrwellReport) window.OrwellReport.fail("engine-status", "health-fetch", _); // G11: fail open, never silent
      show("down", "⚠ Big Brother engine unavailable.", "The app couldn't reach the game service.");
    }
  }

  function start() {
    refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, POLL_MS);
  }

  window.orwellRefreshEngineStatus = refresh;
  window.addEventListener("orwell:gamechanged", refresh);
  ready(start);
})();
