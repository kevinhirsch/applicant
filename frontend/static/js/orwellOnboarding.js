// Orwell onboarding — the casting interview lives in the CHAT (feature 0050).
//
// There is NO data-entry modal: character creation is the game's first scene. Pre-game,
// the server frames every chat turn as the producer's casting interview (the engine's
// character-creation moment prompt), the producer asks, the player answers, and the model
// records each answer with updateCasting — the ENGINE tracks what's captured and what the
// next step is, so the interview can be none, half, or fully done and always resumes.
//
// This module's remaining jobs:
//   • J4 (model gate): no chat model configured → a game-framed holding card ("Production
//     needs a feed source") — the interview literally cannot speak without one.
//   • F5 (engine down): the dark-house holding card instead of a generic workspace welcome.
//   • F7 (fresh season): the FIRST seat-taking of a new interview opens a fresh chat
//     session so a dead season's transcript never rides along as narrator context.
//   • Hand-off: pre-game with everything ready, PREFILL the composer (never auto-send —
//     ADR 0003: the player owns the first keypress) and let the chat do the rest.
//
// On a non-game build an unreachable engine never blocks the normal chat (fail open).
(function () {
  "use strict";

  const SEAT_TAKEN_KEY = "orwell-interview-open"; // sessionStorage: one fresh-session+prefill per interview

  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  async function fetchState() {
    const r = await fetch("/api/orwell/state", { credentials: "same-origin" });
    if (!r.ok) throw new Error("state " + r.status);
    return r.json();
  }

  function buildOverlay() {
    const el = document.createElement("div");
    el.id = "orwell-onboarding";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-modal", "true");
    el.setAttribute("aria-label", "Big Brother production notice");
    el.innerHTML = `
      <style>
        #orwell-onboarding {
          position: fixed; inset: 0; z-index: 99999;
          display: flex; align-items: center; justify-content: center;
          background: color-mix(in srgb, var(--bg, #282c34) 88%, black);
          font-family: 'Fira Code', ui-monospace, monospace;
        }
        #orwell-onboarding .ob-card {
          width: 420px; max-width: 92vw; max-height: 90vh; overflow: auto;
          background: var(--panel, #111); color: var(--fg, #9cdef2);
          border: 1px solid var(--border, #355a66); border-radius: 12px;
          padding: 1.6rem 1.6rem 1.4rem; box-shadow: 0 20px 60px rgba(0,0,0,.45);
        }
        #orwell-onboarding h1 {
          font-size: 1.5rem; font-weight: 600; letter-spacing: .04em; margin: 0 0 .25rem;
          background: linear-gradient(135deg, var(--brand-color, var(--red, #e06c75)),
            color-mix(in srgb, var(--brand-color, var(--red, #e06c75)) 60%, var(--fg, #fff)));
          -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
        }
        #orwell-onboarding .ob-hold { text-align: center; padding: .4rem 0 .2rem; }
        #orwell-onboarding .ob-hold .ob-hold-sub { opacity: .7; font-size: .82rem; margin: .5rem 0 0; line-height: 1.5; }
        #orwell-onboarding .ob-hold-actions { display: flex; gap: .6rem; justify-content: center; margin-top: 1.1rem; flex-wrap: wrap; }
        #orwell-onboarding .ob-btn {
          font: inherit; font-size: .82rem; padding: .45rem .9rem; border-radius: 8px; cursor: pointer;
          background: transparent; color: var(--fg, #9cdef2);
          border: 1px solid var(--border, #355a66);
        }
        #orwell-onboarding .ob-btn:hover { border-color: var(--fg, #9cdef2); }
        #orwell-onboarding .ob-btn-primary {
          background: var(--brand-color, var(--red, #e06c75)); color: var(--bg, #111);
          border-color: transparent; font-weight: 600;
        }
      </style>
      <div class="ob-card"></div>`;
    return el;
  }

  // A11Y-1: aria-modal is a PROMISE to assistive tech that the rest of the page is
  // inert — enforce it. Tab stays inside the card; everything behind the scrim is
  // inert (unfocusable, unclickable) until the overlay resolves.
  let _inerted = [];
  function inertBackground(except) {
    _inerted = [];
    Array.from(document.body.children).forEach((n) => {
      if (n === except || n.tagName === "SCRIPT" || n.tagName === "STYLE") return;
      if (!n.inert) { n.inert = true; _inerted.push(n); }
    });
  }
  function uninertBackground() {
    _inerted.forEach((n) => { try { n.inert = false; } catch (_) {} });
    _inerted = [];
  }
  function trapFocus(el) {
    el.addEventListener("keydown", (e) => {
      if (e.key !== "Tab") return;
      const f = el.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (!f.length) { e.preventDefault(); return; } // nothing focusable → focus stays on the card
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    });
  }

  // F5/J4: a blocking production notice — the only modal left in onboarding (it carries
  // no data entry; it blocks because the game genuinely cannot proceed). Re-probes
  // quietly and dissolves back into the flow the moment the blocker clears.
  //
  // A blocking notice must never be a TRAP: the page behind it is inert, so any remedy the
  // card's copy names must be operable FROM the card, and there is always an explicit way
  // out (a dismiss button + Escape). The J4 card once told the admin "Open Settings" while
  // inerting the Settings button — a real operator was deadlocked on a fresh install with
  // no model configured. The way out is one-shot per mount: dismissing stops the re-probe
  // and stays dismissed until the next page load (route() runs on load only), so an
  // operator mid-configuration is never re-blocked by the poller.
  function mountHolding(title, sub, readyAgain, actions) {
    if (document.getElementById("orwell-onboarding")) return;
    const el = buildOverlay();
    const card = el.querySelector(".ob-card");
    card.setAttribute("tabindex", "-1");
    card.innerHTML = `
      <div class="ob-hold">
        <h1>${title}</h1>
        <p class="ob-hold-sub">${sub}</p>
        <div class="ob-hold-actions"></div>
      </div>`;
    let timer = null;
    const dismiss = () => {
      if (timer) clearInterval(timer);
      uninertBackground();
      el.remove();
    };
    const row = card.querySelector(".ob-hold-actions");
    (actions || []).forEach((a) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ob-btn" + (a.primary ? " ob-btn-primary" : "");
      b.textContent = a.label;
      // Dismiss FIRST: the action's target (e.g. the Settings modal) must not open behind
      // the overlay's inert wall.
      b.addEventListener("click", () => { dismiss(); try { a.onClick && a.onClick(); } catch (_) {} });
      row.appendChild(b);
    });
    const d = document.createElement("button");
    d.type = "button";
    d.className = "ob-btn";
    d.setAttribute("data-ob-dismiss", "");
    d.textContent = "Continue anyway";
    d.addEventListener("click", dismiss);
    row.appendChild(d);
    el.addEventListener("keydown", (e) => { if (e.key === "Escape") dismiss(); });
    document.body.appendChild(el);
    inertBackground(el);
    trapFocus(el);
    try { card.focus(); } catch (_) {}
    timer = setInterval(async () => {
      try {
        if (await readyAgain()) {
          dismiss();
          route();
        }
      } catch (_) { /* still blocked */ }
    }, 5000);
  }

  // The remedy the J4 card names: the workspace's own settings trigger (rail first, user
  // bar as fallback). Called AFTER dismiss so the modal never opens behind the inert wall.
  function openSettings() {
    const btn = document.getElementById("rail-settings") || document.getElementById("user-bar-settings");
    if (btn) btn.click();
  }

  // Seam for the headless browser gate: mount the dark-house holding card on demand.
  window._orwellOnboardingMount = function () {
    mountHolding("The house is dark",
      "Big Brother will return. The game engine isn't reachable right now — this screen will clear the moment the feeds come back.",
      async () => { try { return !!(await fetchState()); } catch (_) { return false; } });
  };

  // J4: "is any chat model configured?" — the interview cannot speak without one, and the
  // old flow let the player author a houseguest then dead-end at "No model selected".
  async function anyModelConfigured() {
    try {
      const r = await fetch("/api/models", { credentials: "same-origin" });
      if (!r.ok) return true; // can't tell → don't block the flow on a probe
      const d = await r.json();
      // /api/models shape: { items: [{ models: [...] , offline }] } per endpoint group.
      const items = (d && Array.isArray(d.items)) ? d.items : [];
      return items.some((it) => Array.isArray(it.models) && it.models.length > 0 && !it.offline);
    } catch (_) { return true; }
  }

  // The casting-seat line is ONE constant: takeASeat prefills it, and the G17/F4
  // re-arm re-offers it after a refresh.
  const SEAT_LINE = "I take my seat for the casting interview.";

  // Hand the player to the producer — in the chat, no modal. Runs ONCE per interview
  // (sessionStorage marker): opens a fresh chat session (F7 — a finished or reset season's
  // transcript must never ride along as narrator context for the new one), then PREFILLS
  // the composer so the player's own Enter starts the interview. Never auto-sends.
  function takeASeat() {
    let seated = false;
    try { seated = sessionStorage.getItem(SEAT_TAKEN_KEY) === "1"; } catch (_) {}
    if (seated) {
      // G17/F4: mid-interview reload — re-offer the seat line if nothing was spoken
      // (the marker used to one-shot at prefill time and strand an empty composer).
      rearmSeatPrefill();
      return;
    }
    try { sessionStorage.setItem(SEAT_TAKEN_KEY, "1"); } catch (_) {}
    try {
      const nb = document.getElementById("sidebar-new-chat-btn") || document.getElementById("rail-new-session");
      if (nb) nb.click();
    } catch (_) {}
    setTimeout(() => {
      const box = document.getElementById("message");
      if (box && !box.value.trim()) {
        box.value = SEAT_LINE;
        box.dispatchEvent(new Event("input", { bubbles: true }));
        box.focus();
      }
    }, 400); // after the fresh-session click settles
  }

  // F4: re-run the PREFILL ONLY — never the fresh-session click (the F7 fence stays
  // one-per-interview, so a reload can never spawn extra sessions). Guards: an
  // F3-restored draft or the player's own typing always wins (composer non-empty), and
  // once the interview has spoken (a player message exists in the transcript) the
  // conversation is the cue, not the prefill.
  function rearmSeatPrefill() {
    setTimeout(() => {
      const box = document.getElementById("message");
      if (!box || box.value.trim()) return;                            // a draft/typing wins
      if (document.querySelector("#chat-history .msg-user")) return;   // already speaking
      box.value = SEAT_LINE;
      box.dispatchEvent(new Event("input", { bubbles: true }));
      box.focus();
    }, 700); // after boot settles: the F3 draft restore + the session transcript render
  }

  // E65: a season restart (createCharacter success mid-session) opens a FRESH chat
  // session so the dead season's transcript never rides as narrator context (F7's
  // page-load-only fence, now event-driven too). The seat marker resets so a future
  // pre-game state runs the casting flow again.
  window._orwellFreshSession = () => {
    try { sessionStorage.removeItem(SEAT_TAKEN_KEY); } catch (_) {}
    try {
      const nb = document.getElementById("sidebar-new-chat-btn") || document.getElementById("rail-new-session");
      if (nb) nb.click();
    } catch (_) {}
  };

  async function route() {
    const gameBuild = document.body && document.body.hasAttribute("data-game-build");
    try {
      const st = await fetchState();
      if (!st || st.started !== false) {
        // A season is running (or the state is unreadable): the NEXT reset begins a new
        // interview, so clear the seat marker.
        try { sessionStorage.removeItem(SEAT_TAKEN_KEY); } catch (_) {}
        return;
      }
      if (!(await anyModelConfigured())) {
        // Sequence the prerequisite (J4): production needs a feed source first. Admins get
        // pointed at setup — and a BUTTON that actually goes there (the copy's remedy must
        // be operable from the card; the page behind it is inert). Re-probe and continue.
        mountHolding("Production needs a feed source",
          "No chat model is configured yet, so the house can't speak. " +
          (window._isAdmin ? "Open Settings → Add Models (or type /setup) to connect one — casting begins the moment a feed is live."
                           : "Ask your administrator to connect a model — casting begins the moment a feed is live."),
          anyModelConfigured,
          window._isAdmin ? [{ label: "Open Settings", primary: true, onClick: openSettings }] : []);
        return;
      }
      takeASeat();
    } catch (_) {
      // Engine unreachable: on the game build that's a dark house, not a silent skip (F5).
      if (gameBuild) window._orwellOnboardingMount();
    }
  }

  ready(route);
})();
