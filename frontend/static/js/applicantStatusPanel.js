// Applicant status panel — the game's standing readout, docked in the sidebar (E64).
//
// Polls the engine's public ceremony status (week / phase / HOH / nominees / veto)
// via GET /api/applicant/status and renders a permanent section inside #sidebar
// whenever a game is in progress. It shows ONLY ceremony-level public facts the
// engine projects — no stats, souls, or hidden state ever reach it (the Vault
// Wall holds on the engine side). It FAILS OPEN: if the engine is unreachable or
// no game is running, the section simply hides and never disturbs the chat.
//
// RULING (#3 / E64): this is not a window. No drag, no saved position, no
// minimize dock, no z-index — it is sidebar chrome, full sidebar width, below
// the session list; on mobile it lives in the sidebar drawer like everything
// else. Collapsible in place; the collapsed state persists per user+game (E71).
import { onNarrowChange } from './platform.js';

(function () {
  "use strict";

  const POLL_MS = 20000;
  const ID = "applicant-status";
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  let timer = null;

  async function fetchStatus() {
    const r = await fetch("/api/applicant/status", { credentials: "same-origin" });
    if (!r.ok) throw new Error("status " + r.status);
    return r.json();
  }

  // The roster (C21): names + status only — Vault-free, exactly what a houseguest sees on
  // the memory wall. Best-effort: if /state fails the panel still shows the ceremony rows.
  async function fetchState() {
    try {
      const r = await fetch("/api/applicant/state", { credentials: "same-origin" });
      if (!r.ok) return null;
      return await r.json();
    } catch (_) { return null; }
  }

  // E71: panel client state is keyed per user + game (the player's name is the
  // closest stable public game discriminator the FE holds), so one account's
  // collapse/dismiss state never leaks into another's, or into season 2.
  let _gameKey = "";
  function storageKey(base) {
    return base + ":" + _gameKey;
  }

  // F1 (G5 refresh-persistence audit / Lane G16): the collapse used to be
  // WRITTEN under the full per-user+game key but RESTORED under a half-built
  // one — _gameKey was only assigned mid-render (renderRoster), AFTER
  // ensurePanel()'s one-time boot read, so the persisted value was unreachable
  // forever and the E71 "persists per user+game" promise was silently broken.
  // The key is now derived from the payloads in hand BEFORE the panel build
  // (render() assigns it ahead of ensurePanel()), and the persisted collapse
  // re-applies whenever the key changes (game change / season 2) — E71
  // scoping intact.
  function computeGameKey(state) {
    return ((state && state.player && state.player.name) || "") + ":" +
           ((document.body && document.body.dataset.user) || "");
  }
  let _applyCollapsed = null;     // ensurePanel's setCollapsed, exposed for re-application
  let _collapseKeyApplied = null; // the _gameKey whose persisted collapse was last applied
  function reapplyPersistedCollapse() {
    if (!_applyCollapsed || _collapseKeyApplied === _gameKey) return;
    _collapseKeyApplied = _gameKey;
    try {
      _applyCollapsed(localStorage.getItem(storageKey("applicant-status-collapsed")) === "1");
    } catch (_) {}
  }

  // The player's OWN ceremony role from PUBLIC facts (HOH / on the block / veto) — derived by
  // id-comparison, never a "safe/target" read (0020). Returns "" when the player is just a
  // houseguest, or their out-of-game seat ("Evicted" / "Jury") when they're out.
  function selfBadge(status, state) {
    const me = state && state.player && state.player.id;
    const seat = state && state.player && state.player.status;
    if (seat === "evicted") return "EVICTED";
    if (seat === "jury") return "JURY";
    if (!me || !status) return "";
    const idOf = (c) => (c && typeof c === "object" ? c.id : c);
    if (idOf(status.hoh) === me) return "HOH";
    const noms = Array.isArray(status.nominees) ? status.nominees.map(idOf) : [];
    if (noms.includes(me)) return "ON THE BLOCK";
    const veto = status.veto || {};
    if (idOf(veto.holder) === me) return "VETO";
    return "";
  }

  function ensurePanel() {
    let el = document.getElementById(ID);
    if (el) return el;
    el = document.createElement("section");
    el.id = ID;
    el.setAttribute("aria-label", "Game status");
    // A3: announcements happen via the dedicated delta announcer below — a live region
    // on a root that toggles display:none and swaps every field per poll announces
    // nothing useful (either silence or a full re-read with no sense of what changed).
    el.innerHTML = `
      <style>
        /* E64: sidebar chrome, not a window — static flow, full sidebar width. */
        #applicant-status {
          display: none;
          margin: var(--space-2) var(--space-2) 0;
          padding: var(--space-2) var(--space-3);
          background: color-mix(in srgb, var(--panel, #111) 70%, transparent);
          color: var(--fg, #9cdef2);
          border: 1px solid var(--border, #355a66); border-radius: 10px;
          font-family: 'Fira Code', ui-monospace, monospace;
          font-size: var(--fs-xs); line-height: 1.5;
        }
        #applicant-status .os-hdr {
          display: flex; align-items: baseline; gap: .4rem;
          margin-bottom: .3rem; font-weight: 600; letter-spacing: .03em;
          cursor: pointer; user-select: none;
        }
        #applicant-status .os-ttl { display: flex; align-items: baseline; gap: .4rem; flex: 1; min-width: 0; flex-wrap: wrap; }
        #applicant-status .os-hdr .os-phase { opacity: .65; font-weight: 400; text-transform: capitalize; }
        #applicant-status .os-chev { opacity: .55; margin-left: auto; transition: transform .15s; }
        #applicant-status.os-collapsed .os-chev { transform: rotate(-90deg); }
        #applicant-status.os-collapsed .os-body { display: none; }
        #applicant-status .os-row { display: flex; gap: .4rem; }
        #applicant-status .os-row .os-k { color: color-mix(in srgb, var(--fg, #9cdef2) 78%, var(--panel, #111)); min-width: 4.2em; }
        #applicant-status .os-row .os-v { flex: 1; }
        #applicant-status .os-noms { color: var(--red, #e06c75); }
        /* Offline dot (U5): the feed reconnecting, not gone — last-known stays visible. */
        #applicant-status .os-stale { color: #e0a500; margin-left: .35rem; font-size: .7em; vertical-align: middle; }
        /* Memory wall (C21): the roster a real houseguest can see. Public facts only. */
        #applicant-status .os-you { margin: .35rem 0 .1rem; font-weight: 600; }
        #applicant-status .os-you .os-badge {
          display: inline-block; margin-left: .4rem; padding: 0 .4em; border-radius: .5em;
          font-size: .72em; font-weight: 700; letter-spacing: .02em;
          background: var(--accent, var(--red, #e06c75)); color: #fff;
        }
        #applicant-status .os-roster-h { opacity: .55; font-size: .8em; margin: .4rem 0 .15rem; }
        #applicant-status .os-roster { display: flex; flex-direction: column; gap: .05rem; max-height: 30vh; overflow: auto; }
        #applicant-status .os-hg { display: flex; justify-content: space-between; gap: .5rem; }
        #applicant-status .os-hg.os-out { color: color-mix(in srgb, var(--fg, #9cdef2) 62%, var(--panel, #111)); text-decoration: line-through; }
        #applicant-status .os-hg .os-seat { opacity: .6; font-size: .78em; text-decoration: none; }
      </style>
      <div class="os-hdr" role="button" tabindex="0" aria-expanded="true" title="Collapse">
        <span class="os-ttl"><span id="os-week">Week —</span><span class="os-phase" id="os-phase"></span><span class="os-stale" id="os-stale" hidden title="Reconnecting to the feed…" aria-label="feed offline">●</span></span>
        <span class="os-chev" aria-hidden="true">▾</span>
      </div>
      <div class="os-body">
        <div class="os-you" id="os-you">You<span class="os-badge" id="os-you-badge" hidden></span></div>
        <div class="os-row"><span class="os-k">HOH</span><span class="os-v" id="os-hoh">—</span></div>
        <div class="os-row"><span class="os-k">Noms</span><span class="os-v os-noms" id="os-noms">—</span></div>
        <div class="os-row"><span class="os-k">Veto</span><span class="os-v" id="os-veto">—</span></div>
        <div class="os-roster-h" id="os-roster-h">The house</div>
        <div class="os-roster" id="os-roster"></div>
      </div>
      <div id="os-announce" aria-live="polite" style="position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);"></div>`;

    // E64: mount INSIDE the sidebar, below the session list — never document.body.
    const sidebar = document.getElementById("sidebar");
    const sessions = document.getElementById("sessions-section");
    if (sessions && sessions.parentElement) {
      sessions.parentElement.insertBefore(el, sessions.nextSibling);
    } else if (sidebar) {
      sidebar.appendChild(el);
    } else {
      document.body.appendChild(el); // headless/degraded DOM — still functional
    }

    // Collapse in place (sidebar chrome, not a dock park) — persisted per user+game.
    const hdr = el.querySelector(".os-hdr");
    const setCollapsed = (on) => {
      el.classList.toggle("os-collapsed", !!on);
      hdr.setAttribute("aria-expanded", on ? "false" : "true");
      try { localStorage.setItem(storageKey("applicant-status-collapsed"), on ? "1" : ""); } catch (_) {}
    };
    const toggle = () => setCollapsed(!el.classList.contains("os-collapsed"));
    hdr.addEventListener("click", toggle);
    hdr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
    });
    try {
      if (localStorage.getItem(storageKey("applicant-status-collapsed")) === "1") setCollapsed(true);
    } catch (_) {}
    // F1: the read above ran under the key render() computed BEFORE this build;
    // expose the setter + record the key so a later key change re-applies.
    _applyCollapsed = setCollapsed;
    _collapseKeyApplied = _gameKey;
    return el;
  }

  function hidePanel() {
    const el = document.getElementById(ID);
    if (el) el.style.display = "none";
  }

  // V3: engine phase enums are internal vocabulary — the HUD speaks the show's.
  const PHASE_LABELS = {
    "setup": "Move-in day", "premiere": "Premiere", "hoh-competition": "HOH competition",
    "nominations": "Nominations", "veto-competition": "Veto competition",
    "veto-ceremony": "Veto ceremony", "eviction": "Eviction night",
    "final-eviction": "Final eviction", "finale": "The finale", "jury": "Jury",
    "social": "A day in the house",
  };
  const phaseLabel = (p) => PHASE_LABELS[p] || String(p || "").replace(/-/g, " ");

  // E69: a correct English ordinal — 11/12/13 (and 111/112/113…) take "th".
  function ordinal(n) {
    const mod100 = n % 100;
    if (mod100 >= 11 && mod100 <= 13) return n + "th";
    return n + (["th", "st", "nd", "rd"][n % 10] || "th");
  }

  // A3: announce only what CHANGED, in show terms — never a full re-read per poll.
  let _last = { phase: null, hoh: null, noms: null, veto: null };
  function announceDeltas(el, st, names) {
    const a = el.querySelector("#os-announce");
    if (!a) return;
    const msgs = [];
    const cur = {
      phase: phaseLabel(st.phase),
      hoh: names.hoh, noms: names.noms, veto: names.veto,
    };
    if (_last.phase !== null) {
      if (cur.phase !== _last.phase) msgs.push(cur.phase + ".");
      if (cur.hoh !== _last.hoh && cur.hoh !== "—") msgs.push("Head of Household: " + cur.hoh + ".");
      if (cur.noms !== _last.noms && cur.noms !== "—") msgs.push("On the block: " + cur.noms + ".");
      if (cur.veto !== _last.veto && cur.veto !== "—") msgs.push("Veto: " + cur.veto + ".");
    }
    _last = cur;
    if (msgs.length) a.textContent = msgs.join(" ");
  }

  function render(st) {
    if (st && st._state !== undefined) _gameKey = computeGameKey(st._state); // F1: key before the build
    const el = ensurePanel();
    reapplyPersistedCollapse();
    // No active game (engine reports week 0 / setup) → genuinely hide (not a hiccup).
    if (!st || typeof st.week !== "number" || st.week < 1) {
      _shown = false;
      _failures = 0;
      markStale(false);
      try { document.body.dataset.gameActive = ""; } catch (_) {} // E93: pre-game is OOC
      hidePanel();
      return;
    }
    _shown = true;
    try { document.body.dataset.gameActive = "1"; } catch (_) {} // E93: the record is live
    const name = (c) => (c && c.name) || "—";
    el.querySelector("#os-week").textContent = "Week " + st.week;
    el.querySelector("#os-phase").textContent = phaseLabel(st.phase);
    el.querySelector("#os-hoh").textContent = name(st.hoh);
    const noms = Array.isArray(st.nominees) ? st.nominees.map((n) => n.name).filter(Boolean) : [];
    el.querySelector("#os-noms").textContent = noms.length ? noms.join(", ") : "—";
    const veto = st.veto || {};
    const vetoText = veto.used
      ? "used" + (veto.holder ? " · " + veto.holder.name : "")
      : (veto.holder ? veto.holder.name : "—");
    el.querySelector("#os-veto").textContent = vetoText;
    announceDeltas(el, st, {
      hoh: name(st.hoh),
      noms: noms.length ? noms.join(", ") : "—",
      veto: vetoText,
    });
    if (st._state !== undefined) renderRoster(el, st, st._state);
    el.style.display = "block";
  }

  // The memory wall: who's still in, who's gone, the attrition count, and the player's own
  // public role badge. All from getGameState().house[] + the ceremony status. No numbers.
  function renderRoster(el, st, state) {
    const badgeEl = el.querySelector("#os-you-badge");
    const badge = selfBadge(st, state);
    if (badge) { badgeEl.textContent = badge; badgeEl.hidden = false; }
    else { badgeEl.hidden = true; }

    // E71: key panel state to this user's game (same derivation as render()'s
    // pre-build assignment — computeGameKey is the single source, F1).
    _gameKey = computeGameKey(state);

    const rosterEl = el.querySelector("#os-roster");
    const headEl = el.querySelector("#os-roster-h");
    const house = state && Array.isArray(state.house) ? state.house : null;
    if (!house) { rosterEl.innerHTML = ""; headEl.style.display = "none"; return; }
    headEl.style.display = "";

    // player (if still active) + NPCs, active first then evicted in eviction order.
    const playerActive = state.player && state.player.status === "active";
    const total = house.length + 1; // player + NPCs
    const activeCount = house.filter((h) => h.status === "active").length + (playerActive ? 1 : 0);
    headEl.textContent = "The house · " + activeCount + "/" + total;

    const out = house.filter((h) => h.status !== "active");
    const rows = [];
    house.filter((h) => h.status === "active").forEach((h) => {
      rows.push('<div class="os-hg"><span>' + esc(h.name) + "</span></div>");
    });
    out.forEach((h, i) => {
      const seat = h.status === "jury" ? "jury" : ordinal(i + 1) + " out";
      rows.push('<div class="os-hg os-out"><span>' + esc(h.name) +
        '</span><span class="os-seat">' + esc(seat) + "</span></div>");
    });
    rosterEl.innerHTML = rows.join("");
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // True once we've shown a real game at least once this session. Lets a transient engine
  // hiccup keep the last-known panel up (U5) instead of vanishing the player's only readout.
  let _shown = false;

  // C18: a hidden tab polls nothing; consecutive failures back the poll off (max 2 min).
  // E68: a SUCCESS resets the backoff — one blip must not degrade a live game to 2-minute polls.
  let _failures = 0;
  function _pollDelay() { return Math.min(POLL_MS * Math.pow(2, _failures), 120000); }

  function markStale(on) {
    const el = document.getElementById(ID);
    const dot = el && el.querySelector("#os-stale");
    if (dot) dot.hidden = !on;
  }

  async function refresh() {
    let st;
    try {
      st = await fetchStatus();
    } catch (_) {
      // ENGINE HICCUP (not "no game"): if we've shown the panel, keep the last-known
      // values up and flag the feed as reconnecting — don't blink the readout out.
      if (window.ApplicantReport) window.ApplicantReport.fail("status-panel", "status-poll", _); // G11: fail open, never silent
      _failures += 1;
      if (_shown) markStale(true);
      else hidePanel();
      return;
    }
    _failures = 0; // E68: recovered — poll at full cadence again
    markStale(false);
    // Fold the roster in (best-effort, never blocks the ceremony rows on /state).
    st._state = (await fetchState()) || null;
    render(st);
  }

  // Seam for the headless browser gate: build + show the panel on demand.
  window._applicantStatusEnsure = () => { const el = ensurePanel(); el.style.display = "block"; return true; };

  function start() {
    refresh();
    if (timer) clearInterval(timer);
    const tick = async () => {
      if (!document.hidden) await refresh();  // C18: no polling in a hidden tab
      timer = setTimeout(tick, _pollDelay());
    };
    timer = setTimeout(tick, _pollDelay());
  }

  // Let onboarding (or any flow that changes the game) trigger an immediate refresh.
  window.applicantRefreshStatus = refresh;
  window.addEventListener("applicant:gamechanged", refresh);
  // The sidebar drawer handles narrow layouts; nothing to repark (E64). Kept as a
  // no-op subscription so a future narrow-specific treatment has its hook.
  onNarrowChange(() => {});

  ready(start);
})();
