// Orwell finale surface (feature 0037 / C11) — the player-facing view of the staged jury vote,
// over the engine's Vault-free /api/orwell/finale route. A self-contained, fail-open sibling to
// orwellSocial.js: it shows ONLY while a finale is staging, renders ONLY what the route returns
// (finalists, stage, and the votes revealed SO FAR — never a pre-reveal tally or the winner), and
// never disturbs the chat if the engine is down. The binding finale decisions still flow through the
// chat agent's submitDecision seam; this panel just visualizes the reveal and offers composer-prefill
// shortcuts for the player's turn (mirroring how orwellSocial surfaces approaches).
//
//   • GET /api/orwell/finale → { finale: { stage, finalists[], asking, reveals[] } | null }
//
// Vault-free by construction (the engine withholds leans/tallies/manner/the pre-reveal winner);
// fail-open everywhere. Composes the window kit (Lane F wave 2); modalManager is
// only consulted for the minimized state the poll loop must respect.
import * as modalManager from "./modalManager.js";

(function () {
  "use strict";

  const POLL_FAST_MS = 5000;       // a finale is staging — poll briskly
  const POLL_SLOW_MS = 45000;      // no finale yet — a light heartbeat (E67/C18)
  const ID = "orwell-finale";
  const PLAYER_ID = "player";
  const ICON = "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M6 9H4.5a2.5 2.5 0 0 1 0-5H6'/><path d='M18 9h1.5a2.5 2.5 0 0 0 0-5H18'/><path d='M4 22h16'/><path d='M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22'/><path d='M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22'/><path d='M18 2H6v7a6 6 0 0 0 12 0V2Z'/></svg>";
  const STAGE_LABEL = { statements: "Opening statements", questions: "Jury questions", vote: "The jury votes", reveal: "The votes are read" };
  const APPEALS = [
    { id: "own-game", label: "Own my game" },
    { id: "mend", label: "Mend fences" },
    { id: "connect", label: "Connect personally" },
    { id: "discredit-rival", label: "Question my rival" },
  ];
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  let timer = null;
  let _staging = false;            // a finale is currently live (drives the poll cadence)
  let _failures = 0;               // C18-style backoff on consecutive errors
  function _pollDelay() {
    const base = _staging ? POLL_FAST_MS : POLL_SLOW_MS;
    return Math.min(base * Math.pow(2, _failures), 120000);
  }

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function isMinimized() {
    try { return modalManager.isMinimized && modalManager.isMinimized(ID); } catch (_) { return false; }
  }
  function hidePanel() {
    const el = document.getElementById(ID);
    if (!el) return;
    if (isMinimized()) { try { modalManager.restore(ID); } catch (_) {} }
    el.style.display = "none";
  }

  // F-2 wave 2 (DWE audit): the panel COMPOSES the window kit — chrome, drag,
  // minimize-to-dock, Escape, focus, and persistence come from OrwellWindow.
  // This module keeps only the finale content: stage, finalists, reveals, and
  // the composer-prefill move buttons.
  let _win = null;
  function ensureUI() {
    let el = document.getElementById(ID);
    if (el) return el;
    const content = document.createElement("div");
    content.innerHTML = `
      <style>
        #orwell-finale {
          width: 240px; display: none;
          font-family: 'Fira Code', ui-monospace, monospace; font-size: .74rem;
        }
        #orwell-finale .ofin-stage { opacity: .6; margin: 0 0 .4rem; letter-spacing: .03em; }
        #orwell-finale .ofin-final {
          display: flex; justify-content: space-between; gap: .4rem; margin-bottom: .5rem;
        }
        #orwell-finale .ofin-fin {
          flex: 1; text-align: center; background: rgba(255,255,255,.05);
          border: 1px solid var(--border, #355a66); border-radius: 8px; padding: .3rem .25rem;
        }
        #orwell-finale .ofin-fin b { display: block; color: var(--fg, #9cdef2); }
        #orwell-finale .ofin-fin .ofin-tally { font-size: 1.1rem; opacity: .9; }
        #orwell-finale .ofin-hd { opacity: .6; margin: .5rem 0 .25rem; letter-spacing: .03em; }
        #orwell-finale .ofin-reveal { margin: .2rem 0; opacity: .9; }
        #orwell-finale .ofin-reveal b { color: var(--fg, #9cdef2); }
        #orwell-finale .ofin-move { margin-top: .5rem; }
        #orwell-finale .ofin-btn {
          width: 100%; cursor: pointer; border-radius: 8px; padding: .3rem .5rem; margin: .2rem 0;
          background: rgba(255,255,255,.05); color: inherit; border: 1px solid var(--border, #355a66);
          font-family: inherit; font-size: .74rem; text-align: left;
        }
        #orwell-finale .ofin-btn:hover { border-color: var(--accent, #e06c75); }
        /* E67/C26 + F3: phones — a full-width top sheet whose POSITION the slot
           engine's sheet host owns (no per-panel pins; two visible sheets stack,
           never overlap). */
        @media (max-width: 768px) {
          #orwell-finale {
            width: auto !important; max-width: none !important;
            border-radius: 0 0 12px 12px; border-left: none; border-right: none;
            max-height: 42vh; overflow: auto;
          }
        }
      </style>
      <div class="ofin-stage" id="ofin-stage"></div>
      <div class="ofin-final" id="ofin-final"></div>
      <div class="ofin-hd" id="ofin-reveal-hd" style="display:none">The votes</div>
      <div id="ofin-reveals"></div>
      <div class="ofin-move" id="ofin-move"></div>
      <div id="ofin-announce" aria-live="polite" style="position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);"></div>`;
    // The kit owns chrome, drag, dock, Escape, focus, and the ONE position
    // system (the clamped slot offset "finale" — the F5 dual-persistence era is
    // over; wave 1 shipped the stale-key cleanup, retired here).
    _win = window.OrwellWindowKit.create({
      id: ID, title: "🏆 The Finale", icon: ICON,
      slot: "top-left", slotKey: "finale", role: "complementary",
      // An ambient HUD parks (minimize); the finale exists while one is staging,
      // so it carries no close — a capability of the one kit cluster.
      minimizable: true, closable: false, draggable: true,
      content,
    });
    _win.open();
    return document.getElementById(ID);
  }

  // Prefill the composer (never auto-send) — the chat agent reads it and calls submitDecision.
  function prefill(text) {
    const box = document.getElementById("message");
    if (!box) return;
    box.value = text;
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.focus();
  }

  function nameOf(ref) { return (ref && ref.name) || "A houseguest"; }
  let _lastRevealCount = 0;

  function render(finale) {
    const el = ensureUI();
    if (!isMinimized()) el.style.display = "block";

    const finalists = Array.isArray(finale.finalists) ? finale.finalists : [];
    const reveals = Array.isArray(finale.reveals) ? finale.reveals : [];
    document.getElementById("ofin-stage").textContent = STAGE_LABEL[finale.stage] || "The finale";

    // Finalists + a tally of the REVEALED votes only (never a pre-reveal total or the winner).
    const tally = {};
    for (const r of reveals) { const id = r.votedFor && r.votedFor.id; if (id) tally[id] = (tally[id] || 0) + 1; }
    const finWrap = document.getElementById("ofin-final");
    finWrap.innerHTML = "";
    for (const f of finalists) {
      const card = document.createElement("div");
      card.className = "ofin-fin";
      const b = document.createElement("b"); b.textContent = nameOf(f);
      const t = document.createElement("span"); t.className = "ofin-tally"; t.textContent = String(tally[f.id] || 0);
      card.appendChild(b); card.appendChild(t); finWrap.appendChild(card);
    }

    // The reveal, in the order the engine read it (revealed votes only). New reveals
    // are ANNOUNCED politely (E67): the vote reading is the season's loudest moment.
    const ann = document.getElementById("ofin-announce");
    if (ann && reveals.length > _lastRevealCount) {
      const fresh = reveals.slice(_lastRevealCount)
        .map((r) => nameOf(r.juror) + " votes for " + nameOf(r.votedFor) + ".");
      ann.textContent = fresh.join(" ");
    }
    _lastRevealCount = reveals.length;
    const revWrap = document.getElementById("ofin-reveals");
    document.getElementById("ofin-reveal-hd").style.display = reveals.length ? "block" : "none";
    revWrap.innerHTML = "";
    for (const r of reveals) {
      const line = document.createElement("div");
      line.className = "ofin-reveal";
      line.innerHTML = "<b></b> votes for <b></b>";
      const bs = line.querySelectorAll("b");
      bs[0].textContent = nameOf(r.juror); bs[1].textContent = nameOf(r.votedFor);
      revWrap.appendChild(line);
    }

    // The player's turn (composer-prefill shortcuts; the chat agent submits the binding decision).
    const playerIsFinalist = finalists.some((f) => f && f.id === PLAYER_ID);
    const move = document.getElementById("ofin-move");
    move.innerHTML = "";
    const addBtn = (label, text) => {
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "ofin-btn"; btn.textContent = label;
      btn.addEventListener("click", () => prefill(text));
      move.appendChild(btn);
    };
    if (playerIsFinalist && finale.stage === "statements") {
      addBtn("✍ Give your opening statement", "I give my opening statement to the jury: ");
    } else if (playerIsFinalist && finale.stage === "questions") {
      for (const a of APPEALS) addBtn("→ " + a.label, `I answer the jury by making my "${a.id}" case.`);
    } else if (!playerIsFinalist && finale.stage === "vote") {
      for (const f of finalists) addBtn("🗳 Vote for " + nameOf(f), `I cast my jury vote for ${nameOf(f)}.`);
    }
  }

  async function refresh() {
    let finale = null;
    try {
      const data = await getJSON("/api/orwell/finale");
      finale = data && data.finale;
      _failures = 0;
    } catch (_) {
      _failures += 1; // engine down → fail open (hide) + back the poll off (E67)
      if (window.OrwellReport) window.OrwellReport.fail("finale", "finale-poll", _); // G11: fail open, never silent
      finale = null;
    }
    _staging = !!finale;
    if (!finale) { hidePanel(); return; }
    render(finale);
  }

  function start() {
    refresh();
    if (timer) clearTimeout(timer);
    const tick = async () => {
      if (!document.hidden) await refresh(); // E67/C18: a hidden tab polls nothing
      timer = setTimeout(tick, _pollDelay());
    };
    timer = setTimeout(tick, _pollDelay());
  }

  // Seam for the headless gate (F3 and the finale's own F-2 wave): build + show on demand.
  window._orwellFinaleEnsure = () => { const el = ensureUI(); if (!isMinimized()) el.style.display = "block"; return true; };
  window.orwellRefreshFinale = refresh;
  window.addEventListener("orwell:gamechanged", refresh);
  ready(start);
})();
