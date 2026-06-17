// Applicant cast roster (feature 0051 / C-FE) — a "who is who" reference panel.
//
// A standing sidebar button (alongside New Chat / Search / Diary Room, shown while a game is
// active) opens a roster panel: each houseguest's persisted portrait (or a graceful placeholder
// when none), their name, and their current status (active / jury / evicted). Evicted houseguests
// stay on the roster, visually dimmed.
//
// Vault-free by construction: it renders ONLY what GET /api/applicant/roster returns — name, status,
// and a portrait ref — which the route builds from the engine's Vault-free public projection. No
// stat, relationship, or hidden element ever reaches this surface. ADR 0003: it AUGMENTS the chat
// (a companion reference), never replaces an interaction; the game plays identically with no
// portraits (the placeholder + name + status card). Fail-open everywhere.
//
// G22: portraits STREAM in. Generation is a server-side background job — faces land one by one
// over several seconds — so the panel polls FAST while the roster reports a run in flight and
// upgrades each card IN PLACE (keyed by roster id) the moment its face lands. The old shape
// (a fixed 30s poll + a wholesale grid rebuild every tick) made the window feel dead: finished
// portraits sat unseen for up to half a minute, then all popped at once while every already-
// loaded image re-mounted (flicker).
(function () {
  "use strict";

  const BTN_ID = "sidebar-cast-btn";
  const PANEL_ID = "applicant-cast";
  // G22: adaptive poll cadence — FAST while a generation run is still landing portraits
  // (the roster reports imagesAvailable with portraitsPresent < portraitsTotal), the idle
  // cadence once the set is complete or no image provider is configured.
  const POLL_MS = 30000;
  const FAST_POLL_MS = 3500;

  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  let _open = false;
  let _timer = null;        // the ONE roster poll timer (a self-rescheduling setTimeout — G22)
  let _pollDelay = POLL_MS; // recomputed from the freshest roster counters after every render
  let _imagesAvailable = false;

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  // --- the sidebar button (standing chrome, game-gated) -------------------------

  function ensureButton() {
    let btn = document.getElementById(BTN_ID);
    if (btn) return btn;
    // Anchor next to the Diary Room button if present, else Search, else New Chat.
    const anchor = document.getElementById("sidebar-diary-room-btn")
      || document.getElementById("sidebar-search-btn")
      || document.getElementById("sidebar-new-chat-btn");
    if (!anchor || !anchor.parentElement) return null;
    btn = document.createElement("div");
    btn.className = "list-item";
    btn.id = BTN_ID;
    btn.setAttribute("role", "button");
    btn.setAttribute("tabindex", "0");
    btn.title = "Cast — the houseguests";
    btn.style.display = "none"; // shown while a game is active
    btn.innerHTML = `
      <svg class="sidebar-action-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
      <span class="grow">Cast</span>`;
    const open = () => togglePanel(true);
    btn.addEventListener("click", open);
    btn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
    });
    anchor.parentElement.insertBefore(btn, anchor.nextSibling);
    return btn;
  }

  async function refreshGate() {
    const btn = ensureButton();
    if (!btn) return;
    try {
      const r = await fetch("/api/applicant/state", { credentials: "same-origin" });
      const st = r.ok ? await r.json() : null;
      const live = !!(st && st.started);
      btn.style.display = live ? "" : "none";
      if (!live && _open) togglePanel(false);
    } catch (_) { /* engine hiccup: leave the button as it was (fail-open) */ }
  }

  // --- the panel ----------------------------------------------------------------

  // G10 (DWE / Lane G): the roster COMPOSES the window kit — it is a companion
  // reference (its own doc-comment), so it is a normal non-modal window: kit
  // titlebar (close + minimize), drag, slot placement, Escape-parks, dock chip,
  // and the one visual language. The old bespoke full-screen modal scrim and
  // hidden-attribute toggling are gone (an author display:flex rule silently
  // defeated that attribute — the close button never worked; root cause
  // recorded in the Lane G ledger).
  let _win = null;
  function ensurePanel() {
    let el = document.getElementById(PANEL_ID);
    if (el) return el;
    const content = document.createElement("div");
    content.innerHTML = `
      <style>
        #applicant-cast {
          width: min(560px, 92vw);
          font-family: 'Fira Code', ui-monospace, monospace;
        }
        #applicant-cast .oc-grid {
          display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
          gap: .7rem;
        }
        #applicant-cast .oc-hg { text-align: center; }
        #applicant-cast .oc-portrait {
          width: 100%; aspect-ratio: 1 / 1; border-radius: 10px; overflow: hidden;
          background: rgba(255,255,255,.05); border: 1px solid var(--border, #355a66);
          display: flex; align-items: center; justify-content: center;
        }
        #applicant-cast .oc-portrait img { width: 100%; height: 100%; object-fit: cover; }
        /* G22: a just-landed face fades in gently… */
        @keyframes ocFadeIn { from { opacity: 0; } to { opacity: 1; } }
        #applicant-cast .oc-portrait img.oc-justin { animation: ocFadeIn .35s ease; }
        /* …unless the player prefers reduced motion. */
        @media (prefers-reduced-motion: reduce) {
          #applicant-cast .oc-portrait img.oc-justin { animation: none; }
        }
        #applicant-cast .oc-ph { font-size: 1.6rem; opacity: .45; }
        #applicant-cast .oc-name { margin-top: .35rem; font-size: .78rem; line-height: 1.25; word-break: break-word; }
        #applicant-cast .oc-name b { color: var(--fg, #9cdef2); }
        #applicant-cast .oc-status {
          margin-top: .15rem; font-size: .66rem; letter-spacing: .04em; opacity: .65; text-transform: uppercase;
        }
        #applicant-cast .oc-hg.oc-out { opacity: .5; }
        #applicant-cast .oc-hg.oc-out .oc-portrait img { filter: grayscale(1); }
        #applicant-cast .oc-empty { opacity: .65; font-size: .8rem; line-height: 1.5; padding: .4rem 0; }
        #applicant-cast .oc-actions { margin-top: .8rem; display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; }
        #applicant-cast .oc-backfill {
          cursor: pointer; font: inherit; font-size: .74rem; letter-spacing: .03em;
          color: inherit; background: rgba(255,255,255,.06);
          border: 1px solid var(--border, #355a66); border-radius: 8px;
          padding: .4rem .7rem; min-height: 32px;
        }
        #applicant-cast .oc-backfill:hover:not(:disabled) { background: rgba(255,255,255,.12); }
        #applicant-cast .oc-backfill:disabled { opacity: .5; cursor: default; }
        #applicant-cast .oc-backfill-note { font-size: .72rem; opacity: .65; line-height: 1.4; }
        /* Narrow: the slot engine's sheet host owns the position; just fit. */
        @media (max-width: 768px) {
          #applicant-cast { width: auto !important; max-width: none !important; }
        }
      </style>
      <div class="oc-grid" id="oc-grid"></div>
      <div class="oc-empty" id="oc-empty" style="display:none"></div>
      <div class="oc-actions" id="oc-actions" style="display:none">
        <button type="button" class="oc-backfill" id="oc-backfill">Generate cast portraits</button>
        <span class="oc-backfill-note" id="oc-backfill-note"></span>
      </div>`;
    _win = window.ApplicantWindowKit.create({
      id: PANEL_ID, title: "🎬 The Cast",
      icon: "<svg width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2'><circle cx='9' cy='7' r='4'/><path d='M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'/></svg>",
      slot: "top-left", slotKey: "cast", role: "complementary",
      minimizable: true, closable: true, draggable: true,
      content,
      onClose: () => {
        _win = null; _open = false;
        if (_timer) { clearTimeout(_timer); _timer = null; }
        _cards.clear(); // the kit tore the panel DOM down — drop the detached card nodes
      },
    });
    _win.open(document.getElementById(BTN_ID) || undefined);
    const el2 = document.getElementById(PANEL_ID);
    el2.querySelector("#oc-backfill").addEventListener("click", requestBackfill);
    return el2;
  }

  function statusLabel(s) {
    if (s === "jury") return "Jury";
    if (s === "evicted") return "Evicted";
    return "In the house";
  }

  // --- the G9 manual lever: backfill missing portraits -------------------------
  // Shown only when a provider is configured (imagesAvailable) AND active houseguests
  // still show placeholders — e.g. a season created before 0051 shipped, or a prior
  // generation run that failed. POSTs the debounced backfill route; never blocks.

  async function requestBackfill() {
    const el = ensurePanel();
    const btn = el.querySelector("#oc-backfill");
    const note = el.querySelector("#oc-backfill-note");
    btn.disabled = true;
    note.textContent = "Requesting…";
    try {
      const r = await fetch("/api/applicant/portraits/backfill", {
        method: "POST", credentials: "same-origin",
      });
      const data = r.ok ? await r.json() : null;
      if (data && data.kicked) {
        const n = Array.isArray(data.missing) ? data.missing.length : 0;
        note.textContent = "Generating " + n + " portrait" + (n === 1 ? "" : "s") +
          " in the background — they'll appear here as they land.";
      } else if (data && !data.available) {
        note.textContent = "No image model is configured — the game plays on without portraits.";
      } else if (data && !(data.missing || []).length) {
        note.textContent = "Nothing missing — every active houseguest has a portrait.";
      } else {
        note.textContent = "A generation run started recently — give it a few minutes, then try again.";
      }
    } catch (_) {
      if (window.ApplicantReport) window.ApplicantReport.fail("cast", "backfill-post", _); // G11: fail open, never silent
      note.textContent = "The portrait service is offline right now.";
    }
    // Re-enable after a beat (the server debounces regardless — this just avoids mashing).
    setTimeout(() => { btn.disabled = false; }, 5000);
  }

  // --- G22: keyed, incremental render -------------------------------------------
  // One card element per roster id, upserted in place across polls: a face that just
  // landed fades into its OWN card and nothing else is touched — untouched cards (and
  // their loaded <img> nodes) are never rebuilt, so nothing flickers or refetches.

  const _cards = new Map(); // roster id → { el, holder, nameB, statusEl, name, status, portrait }

  function cardKey(hg) {
    // The roster route always sets a stable `id` (player → engine id or "player";
    // NPC → engine id or name); the name fallback here is purely defensive.
    const id = hg && hg.id != null && hg.id !== "" ? hg.id : (hg && hg.name);
    return id == null ? "" : String(id);
  }

  function setPortrait(entry, url, justLanded) {
    // Called ONLY on a real transition (placeholder→url, a changed url, url→gone):
    // the same src is never re-assigned, so a loaded face never reloads.
    entry.portrait = url || null;
    entry.holder.textContent = "";
    if (!url) {
      const ph = document.createElement("span");
      ph.className = "oc-ph";
      ph.textContent = "👤";
      entry.holder.appendChild(ph);
      return;
    }
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = entry.name;
    if (justLanded) {
      // The G22 arrival fade (reduced-motion guarded in the CSS above); drop the
      // class once played so a later grid re-order can't replay it.
      img.className = "oc-justin";
      img.addEventListener("animationend", () => img.classList.remove("oc-justin"), { once: true });
    }
    // The placeholder fallback, as ever — and the entry forgets the url, so a
    // transient miss (the file landing a beat after the manifest) heals next poll.
    img.onerror = () => setPortrait(entry, null, false);
    img.src = url;
    entry.holder.appendChild(img);
  }

  function makeCard(hg) {
    const out = hg.status && hg.status !== "active";
    const card = document.createElement("div");
    card.className = "oc-hg" + (out ? " oc-out" : "");
    const holder = document.createElement("div");
    holder.className = "oc-portrait";
    const nameEl = document.createElement("div");
    nameEl.className = "oc-name";
    const nameB = document.createElement("b");
    nameB.textContent = hg.name == null ? "" : String(hg.name);
    nameEl.appendChild(nameB);
    if (hg.isPlayer) nameEl.appendChild(document.createTextNode(" (you)"));
    const statusEl = document.createElement("div");
    statusEl.className = "oc-status";
    statusEl.textContent = statusLabel(hg.status);
    card.appendChild(holder);
    card.appendChild(nameEl);
    card.appendChild(statusEl);
    const entry = {
      el: card, holder, nameB, statusEl,
      name: hg.name == null ? "" : String(hg.name),
      status: hg.status || "active",
      portrait: null,
    };
    // First paint of a brand-new card: no fade — the fade marks a portrait ARRIVING
    // on a card the player is already looking at.
    setPortrait(entry, hg.portrait || null, false);
    return entry;
  }

  function updateCard(entry, hg) {
    const status = hg.status || "active";
    if (status !== entry.status) {
      entry.status = status;
      entry.el.classList.toggle("oc-out", !!(hg.status && hg.status !== "active"));
      entry.statusEl.textContent = statusLabel(hg.status);
    }
    const name = hg.name == null ? "" : String(hg.name);
    if (name !== entry.name) { entry.name = name; entry.nameB.textContent = name; }
    const url = hg.portrait || null;
    if (url !== entry.portrait) setPortrait(entry, url, !!url); // the stream moment
  }

  function render(data) {
    const el = ensurePanel();
    const grid = el.querySelector("#oc-grid");
    const empty = el.querySelector("#oc-empty");
    const roster = (data && Array.isArray(data.roster)) ? data.roster : [];
    _imagesAvailable = !!(data && data.imagesAvailable);

    // G22: the adaptive cadence reads the G20 counters — while a generation run is
    // still landing portraits (provider configured + total > present), the next poll
    // comes fast so each face shows up within a few seconds of being written.
    const total = (data && typeof data.portraitsTotal === "number") ? data.portraitsTotal : null;
    const present = (data && typeof data.portraitsPresent === "number") ? data.portraitsPresent : null;
    const generating = _imagesAvailable && total != null && present != null && total > present;
    _pollDelay = generating ? FAST_POLL_MS : POLL_MS;

    const actions = el.querySelector("#oc-actions");
    if (!roster.length) {
      // The empty state (pre-season / a reset) — the ONLY path that empties the
      // grid; a populated roster only ever upserts cards in place.
      for (const entry of _cards.values()) entry.el.remove();
      _cards.clear();
      empty.style.display = "";
      empty.textContent = "The cast hasn't moved in yet.";
      if (actions) actions.style.display = "none";
      return;
    }
    empty.style.display = "none";

    // G9: offer the retry lever when a provider is configured but active houseguests
    // still show placeholders (pre-0051 seasons / failed generation runs).
    const missing = roster.filter(
      (hg) => (!hg.status || hg.status === "active") && !hg.portrait
    );
    if (actions) {
      actions.style.display = (_imagesAvailable && missing.length) ? "" : "none";
      // G20: standing completeness copy — the background reconciler verifies and
      // retries the set; this row reports the live remainder (server counters when
      // present, the rendered roster otherwise).
      if (_imagesAvailable && missing.length) {
        const note = el.querySelector("#oc-backfill-note");
        if (note) note.textContent = "Generating " + missing.length + " remaining…" +
          (total != null && present != null ? " (" + present + "/" + total + " done)" : "");
      }
    }

    // Active first (player flagged), then jury, then evicted — keeps the live house
    // on top. sort() is stable, so within a tier the server's order (player first)
    // holds across polls: the grid order is keyed and deterministic.
    const order = { active: 0, jury: 1, evicted: 2 };
    const sorted = roster.slice().sort((a, b) =>
      (order[a.status] ?? 3) - (order[b.status] ?? 3));

    // The keyed upsert: add new ids, upgrade changed cards in place, drop vanished
    // ids (defensive), and keep the tier order by MOVING live nodes when it drifts —
    // appendChild relocates an element without re-mounting it, so a loaded portrait
    // never reloads.
    const seen = new Set();
    const desired = [];
    for (const hg of sorted) {
      const key = cardKey(hg);
      if (!key || seen.has(key)) continue; // defensive: unkeyable / duplicate rows
      seen.add(key);
      let entry = _cards.get(key);
      if (entry) updateCard(entry, hg);
      else { entry = makeCard(hg); _cards.set(key, entry); }
      desired.push(entry.el);
    }
    for (const [key, entry] of Array.from(_cards)) {
      if (!seen.has(key)) { entry.el.remove(); _cards.delete(key); }
    }
    const current = Array.from(grid.children);
    if (current.length !== desired.length || desired.some((node, i) => current[i] !== node)) {
      for (const node of desired) grid.appendChild(node);
    }
  }

  async function refreshRoster() {
    try {
      const data = await getJSON("/api/applicant/roster");
      render(data);
    } catch (_) {
      // Fail open: keep whatever's shown; an empty first load shows the empty-state copy.
      if (window.ApplicantReport) window.ApplicantReport.fail("cast", "roster-fetch", _); // G11: fail open, never silent
      const el = document.getElementById(PANEL_ID);
      if (el && !el.querySelector("#oc-grid").children.length) {
        el.querySelector("#oc-empty").style.display = "";
        el.querySelector("#oc-empty").textContent = "The cast list is offline right now.";
      }
    }
  }

  // G22: ONE self-rescheduling poll timer. The next delay is recomputed from the
  // freshest roster (render() above) after each refresh — fast while portraits are
  // landing, the idle cadence once the set is complete — and the timer is always
  // cleared before it is re-armed, so cadence flips and re-entrant arms can never
  // stack pollers. A hidden tab skips the fetch but keeps the loop alive for when
  // the player returns; closing the panel stops it (onClose clears, and a cleared
  // panel never re-arms).
  function scheduleNextPoll() {
    if (_timer) { clearTimeout(_timer); _timer = null; }
    if (!_open) return;
    _timer = setTimeout(async () => {
      _timer = null;
      if (_open && !document.hidden) await refreshRoster();
      scheduleNextPoll();
    }, _pollDelay);
  }

  function togglePanel(open) {
    if (open) {
      const existed = !!document.getElementById(PANEL_ID);
      const el = ensurePanel();
      _open = true;
      // G16/F2 (refresh-persistence audit): when ensurePanel() just MOUNTED the
      // window and the kit honored a persisted parked flag (the player parked it
      // last page-life), it lives in the dock — leave it parked; its dock chip
      // restores it. An explicit toggle on an ALREADY-LIVE minimized window
      // still restores, exactly as before. (The display write matters too:
      // modalManager's launcher-agnostic observer treats any un-hide of a
      // minimized window as a restore, which would silently un-park it.)
      const bootParked = !existed && _win && _win.isMinimized && _win.isMinimized();
      if (!bootParked) {
        el.style.display = "block";
        if (_win) { _win.restore(); _win.raise(); }
      }
      // G22: refresh now, then poll on the adaptive cadence that refresh computed.
      refreshRoster().then(scheduleNextPoll);
    } else if (_win) {
      _win.close(); // kit close: fly-away, teardown, focus-return (onClose resets state)
    }
  }

  // Seam for the headless gate (mirrors the other panels).
  window._applicantCastEnsure = () => { togglePanel(true); return true; };

  // Public hooks (mirrors the other applicant panels): refresh on a game change — and
  // re-arm the poll so a cadence change (say, a fresh season that is generating its
  // portraits) takes effect NOW, not at the old timer's next tick.
  window.applicantRefreshCast = () => { if (_open) refreshRoster().then(scheduleNextPoll); };
  window.addEventListener("applicant:gamechanged", () => {
    refreshGate();
    if (_open) refreshRoster().then(scheduleNextPoll);
  });

  ready(() => {
    refreshGate();
    setInterval(refreshGate, 20000);
  });
})();
