// Orwell social surface (feature 0036 / C10, refit by H5/G7) — NPC approaches as
// SIDEBAR CHROME, over the engine's Vault-free routes (the Diary Room lives in the
// sidebar too — orwellDiaryRoom.js). Built as a self-contained, fail-open sibling to
// orwellStatusPanel.js: it only shows while a game is in progress AND a houseguest
// actually wants the player, renders ONLY what the routes return, and never disturbs
// the chat if the engine is down.
//
//   • GET  /api/orwell/state        → gate on an active game (started)
//   • GET  /api/orwell/initiatives  → houseguests who want to approach (name + motive)
//
// Vault-free by construction (the engine withholds all hidden state); fail-open everywhere.
//
// H5 (the user verdict on "The House", = the long-parked G7): this is NOT a window
// anymore. The floating kit panel read as a useless empty box, so the surface is folded
// into the sidebar on the ruling #3/E64 precedent (the status HUD pattern): a <section>
// injected into #sidebar directly under the game-status section — no drag, no saved
// position, no minimize dock, no z-index, no titlebar. On mobile it lives in the
// sidebar drawer like every other section. And because an approaches surface with no
// approaches is exactly the "empty window" the verdict retired, the section renders
// NOTHING while no approach is pending — it appears when a houseguest wants a word and
// collapses away again once the player has handled them all.
//
// What it keeps (all the real behavior): the approach chips with E60 motive framing,
// the E89 first-ceremony belt, per-user dismissals, the prefill-the-composer action,
// and the C18 poll loop with backoff.

(function () {
  "use strict";

  const POLL_MS = 20000;
  const ID = "orwell-social";
  const MAX_APPROACHES = 3;            // a few houseguests may want you at once — a living house (U7)
  // E71: dismissals are scoped per user (and cleared per game via orwell:gamechanged),
  // so one account's waved-off approaches never bleed into another's session.
  const DISMISS_KEY = "orwell-social-dismissed:" +
    ((document.body && document.body.dataset.user) || "");
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  // E60: the engine ships a coarse categorical MOTIVE (bond | probe) — never the number, never a
  // canned pretext line — and the chip varies its framing by that enum: a "bond" approach reads as
  // a warm overture, a "probe" reads as someone sizing the player up. The GM voices the real scene
  // in the chat; this is just how the chip carries the difference. Unknown/absent motive falls back
  // to the neutral copy. Copy lives here (one place), not scattered inline.
  const MOTIVE_FRAMING = {
    bond:  { pretext: "wants to talk game with you",   cls: "osoc-motive-bond",  hint: "A friendly overture" },
    probe: { pretext: "has been sizing up your game",  cls: "osoc-motive-probe", hint: "They're feeling you out" },
  };
  const MOTIVE_FALLBACK = { pretext: "wants a word with you", cls: "osoc-motive-neutral", hint: "Hear them out" };

  // E89 belt: NO approach renders before the house has actually started PLAYING — the first
  // ceremony (the week-1 HOH result) must have resolved. The engine's E89 gate already returns an
  // empty list pre-first-ceremony; this is the FE's own belt, so even if the engine FAILS OPEN and
  // ships approaches early (a "wants a word with you" at the premiere), the UI still shows nothing.
  // Derived from /api/orwell/state alone: pre-ceremony beats are setup/premiere/character-creation
  // and the week-1 HOH competition itself; once noms (or any later beat / a later week) is reached,
  // the first ceremony has resolved.
  function firstCeremonyResolved(st) {
    if (!st || !st.started) return false;
    const week = typeof st.week === "number" ? st.week : 1;
    if (week > 1) return true; // a second HOH week ⇒ the first ceremony is long resolved
    const phase = String(st.phase || st.moment || "").toLowerCase();
    const preCeremony =
      phase === "" ||
      phase.indexOf("setup") >= 0 ||
      phase.indexOf("premiere") >= 0 ||
      phase.indexOf("character-creation") >= 0 ||
      phase.indexOf("casting") >= 0 ||
      phase.indexOf("hoh") >= 0; // the opening HOH COMPETITION is still pre-first-ceremony
    return !preCeremony;
  }
  let _ceremonyResolved = false; // last-known belt state, refreshed each poll from /state

  let timer = null;
  // C18: a hidden tab polls nothing; consecutive failures back the poll off (max 2 min).
  let _failures = 0;
  function _pollDelay() { return Math.min(POLL_MS * Math.pow(2, _failures), 120000); }
  let pendingApproachId = null;  // approach prefilled but not yet sent
  // G17 (refresh-persistence audit F7): the pending approach rides the persisted
  // composer-draft record, so every change must be observable. setPendingApproach is
  // the ONE live mutation door (it notifies the draft module); the boot restore comes
  // back through the seam below without re-notifying.
  function setPendingApproach(id) {
    pendingApproachId = id;
    try { window.dispatchEvent(new CustomEvent("orwell:approachpending", { detail: { id } })); } catch (_) {}
  }
  window._orwellPendingApproach = {
    get: () => pendingApproachId,
    restore: (id) => { pendingApproachId = id; }, // G17 boot restore: silent on purpose
  };
  let _shown = false;  // shown a real game this session (U5: keep last-known on a hiccup)

  // Approaches the player has acted on or waved off. Persisted so a refresh (or a sent
  // scene) doesn't resurrect a handled approach; cleared when a new game begins.
  function loadDismissed() {
    try { return new Set(JSON.parse(localStorage.getItem(DISMISS_KEY) || "[]")); } catch (_) { return new Set(); }
  }
  let dismissed = loadDismissed();
  function dismiss(id) {
    dismissed.add(id);
    try { localStorage.setItem(DISMISS_KEY, JSON.stringify([...dismissed])); } catch (_) {}
  }
  function clearDismissed() {
    dismissed = new Set();
    setPendingApproach(null);
    try { localStorage.removeItem(DISMISS_KEY); } catch (_) {}
  }

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  // Hide the section outright (no active game / engine down before first paint).
  function hidePanel() {
    const el = document.getElementById(ID);
    if (el) el.style.display = "none";
  }

  // H5: the section is sidebar chrome, mirroring orwellStatusPanel.js's ensure/mount
  // pattern (ruling #3/E64) — static flow, full sidebar width, the status panel's
  // visual standard. display is CONTENT-DRIVEN: renderApproaches() shows the section
  // only while it holds at least one live chip, so an empty "The House" box can never
  // sit on the screen again.
  function ensureSection() {
    let el = document.getElementById(ID);
    if (el) return el;
    el = document.createElement("section");
    el.id = ID;
    el.setAttribute("aria-label", "House approaches");
    el.innerHTML = `
      <style>
        /* H5: sidebar chrome, not a window — the orwell-status visual standard. */
        #orwell-social {
          display: none;
          margin: var(--space-2) var(--space-2) 0;
          padding: var(--space-2) var(--space-3);
          background: color-mix(in srgb, var(--panel, #111) 70%, transparent);
          color: var(--fg, #9cdef2);
          border: 1px solid var(--border, #355a66); border-radius: 10px;
          font-family: 'Fira Code', ui-monospace, monospace;
          font-size: var(--fs-xs); line-height: 1.5;
        }
        #orwell-social .osoc-hd {
          color: color-mix(in srgb, var(--fg, #9cdef2) 78%, var(--panel, #111));
          margin: 0 0 .3rem; font-weight: 600; letter-spacing: .03em;
        }
        #orwell-social .osoc-chip {
          display: flex; align-items: center; gap: .35rem; margin: .25rem 0;
          background: rgba(255,255,255,.05); border: 1px solid var(--border, #355a66);
          border-radius: 8px; padding: .25rem .4rem;
        }
        #orwell-social .osoc-chip .osoc-go {
          flex: 1; cursor: pointer; text-align: left; min-height: 24px;
          border: none; background: none; color: inherit; font: inherit; padding: 0;
        }
        #orwell-social .osoc-chip .osoc-go b { color: var(--fg, #9cdef2); }
        #orwell-social .osoc-chip .osoc-x {
          cursor: pointer; opacity: .55; border: none; background: none; color: inherit;
          font-size: .9rem; line-height: 1; padding: .2rem .35rem; min-width: 24px; min-height: 24px;
        }
        /* E60: the chip's framing VARIES by the engine's coarse motive — a warm overture (bond)
           reads differently from someone sizing the player up (probe). A left accent rail carries
           the difference without leaking any number. */
        #orwell-social .osoc-chip.osoc-motive-bond  { border-left: 3px solid color-mix(in srgb, #4caf50 70%, var(--border, #355a66)); }
        #orwell-social .osoc-chip.osoc-motive-probe { border-left: 3px solid color-mix(in srgb, #e0a96c 70%, var(--border, #355a66)); }
        #orwell-social .osoc-chip.osoc-motive-neutral { border-left: 3px solid var(--border, #355a66); }
        #orwell-social .osoc-chip.osoc-chip-pending {
          border-color: var(--accent, #e06c75); opacity: .85;
        }
        #orwell-social .osoc-chip.osoc-chip-pending .osoc-go b {
          color: var(--accent, #e06c75);
        }
      </style>
      <div class="osoc-hd" id="osoc-appr-hd">Wants a word</div>
      <div id="osoc-appr"></div>`;
    // E88 (ruling #4): the Diary Room is NOT here — it is a standing sidebar
    // button + a composer mode (orwellDiaryRoom.js). This section is approaches only.
    //
    // Mount INSIDE the sidebar, directly under the game-status section (or under the
    // session list before the status panel has mounted — the two orderings converge:
    // sessions → status → approaches). Never document.body, never floating.
    const sidebar = document.getElementById("sidebar");
    const anchor = document.getElementById("orwell-status") ||
                   document.getElementById("sessions-section");
    if (anchor && anchor.parentElement) {
      anchor.parentElement.insertBefore(el, anchor.nextSibling);
    } else if (sidebar) {
      sidebar.appendChild(el);
    } else {
      document.body.appendChild(el); // headless/degraded DOM — still functional
    }
    return el;
  }

  // --- Approaches -------------------------------------------------------

  // The NPC INITIATED the approach (socialInitiatives = who wants the player now), so the
  // prefill frames them coming to the player — not the player pulling them aside (U6). Varied
  // so it doesn't read as one canned line; the player still sends it themselves.
  const _APPROACH_LINES = [
    (n) => `${n} catches my eye and drifts over — I turn to hear them out.`,
    (n) => `${n} pulls me aside; I give them my attention.`,
    (n) => `${n} sidles up wanting a word. I bite. "What's up?"`,
    (n) => `${n} flags me down — I stop and see what they want.`,
  ];

  function startScene(name, id) {
    // "Acting" on an approach starts a scene the normal way: prefill the composer and focus it,
    // so the player sends it themselves (we never auto-send or fabricate a turn).
    const box = document.getElementById("message");
    if (!box) return;
    const line = _APPROACH_LINES[Math.floor(Math.random() * _APPROACH_LINES.length)];
    box.value = line(name);
    box.dispatchEvent(new Event("input", { bubbles: true }));
    box.focus();
    setPendingApproach(id);
  }

  // When the player actually sends a message, dismiss the pending approach so
  // the chip clears — the scene has been initiated, no need to keep it.
  function onMessageSend() {
    if (pendingApproachId !== null) {
      dismiss(pendingApproachId);
      setPendingApproach(null);
      // Clear and collapse; the next poll re-renders any approaches still live
      // (H5: an empty section never lingers on screen).
      renderApproaches([]);
    }
  }
  // Hook into the send button and Enter-to-submit on the composer.
  const _wireComposer = () => {
    const form = document.getElementById("chat-form") || document.querySelector("form");
    if (form && !form._orwellSocialWired) {
      form._orwellSocialWired = true;
      form.addEventListener("submit", onMessageSend);
    }
    const btn = document.getElementById("send-btn") || document.querySelector("[id$='-send']");
    if (btn && !btn._orwellSocialWired) {
      btn._orwellSocialWired = true;
      btn.addEventListener("click", onMessageSend);
    }
  };

  function renderApproaches(list) {
    const el = ensureSection();
    const wrap = document.getElementById("osoc-appr");
    const hd = document.getElementById("osoc-appr-hd");
    if (!wrap) return;
    _wireComposer();
    // E89 belt: before the first ceremony resolves, render NOTHING — even if the engine fails open
    // and hands us approaches at the premiere. The belt comes from the last /state poll.
    const allowed = _ceremonyResolved
      ? (Array.isArray(list) ? list : [])
      : [];
    const items = allowed
      .filter((it) => it && it.houseguest && it.houseguest.id && !dismissed.has(it.houseguest.id))
      .slice(0, MAX_APPROACHES); // a few may want you at once (U7)
    wrap.innerHTML = "";
    hd.style.display = items.length ? "block" : "none";
    // H5: content-driven visibility — the section exists on screen ONLY while it
    // holds at least one chip (the verdict: never an empty "The House" box).
    el.style.display = items.length ? "block" : "none";
    for (const it of items) {
      const id = it.houseguest.id;
      const name = it.houseguest.name || "A houseguest";
      // E60: the engine ships a coarse MOTIVE (bond | probe), never a canned pretext line; the chip
      // VARIES its framing (copy + class + tooltip) by that enum — the GM voices the real scene.
      const framing = (it.motive && MOTIVE_FRAMING[it.motive]) || MOTIVE_FALLBACK;
      const pretext = it.pretext || framing.pretext;
      const chip = document.createElement("div");
      chip.className = "osoc-chip " + framing.cls;
      if (it.motive) chip.dataset.motive = it.motive;
      if (id === pendingApproachId) chip.classList.add("osoc-chip-pending");
      const go = document.createElement("button");
      go.type = "button";
      go.className = "osoc-go";
      go.title = framing.hint + " — prefills the composer";
      go.setAttribute("aria-label", "Hear " + name + " out (" + framing.hint + ")");
      go.innerHTML = `<b></b> <span class="osoc-pre"></span>`;
      go.querySelector("b").textContent = name;
      go.querySelector(".osoc-pre").textContent = pretext;
      // Clicking "go" prefills but does NOT dismiss immediately — the chip
      // stays until the player actually sends the message or hits the X.
      // This prevents the frustrating cycle where three quick clicks dismiss
      // all approaches before a single message is written.
      go.addEventListener("click", () => { startScene(name, id); renderApproaches(list); });
      const x = document.createElement("button");
      x.className = "osoc-x"; x.title = "Skip (dismiss)"; x.textContent = "×";
      x.addEventListener("click", () => {
        if (pendingApproachId === id) setPendingApproach(null);
        dismiss(id);
        renderApproaches(list);
      });
      chip.appendChild(go); chip.appendChild(x);
      wrap.appendChild(chip);
    }
  }

  // Seam for the headless browser gate: mount the section on demand (display stays
  // content-driven — H5: an empty section never shows).
  window._orwellSocialEnsure = () => { ensureSection(); return true; };

  // E60/E89 test seam (headless browser keep-set): drive the belt + motive framing WITHOUT a live
  // engine. `resolved` sets the FE belt; `list` is fed to renderApproaches exactly as a (possibly
  // fail-open) initiatives payload would be — so the smoke can prove the belt suppresses chips even
  // when approaches arrive early, and that bond/probe motives render distinct chips once it opens.
  window._orwellSocialDriveApproaches = (resolved, list) => {
    ensureSection();
    _ceremonyResolved = !!resolved;
    dismissed = new Set(); // a clean slate so the smoke isn't suppressed by prior dismissals
    renderApproaches(list || []);
    const wrap = document.getElementById("osoc-appr");
    const chips = wrap ? [...wrap.querySelectorAll(".osoc-chip")] : [];
    return {
      count: chips.length,
      motives: chips.map((c) => c.dataset.motive || null),
      classes: chips.map((c) => (c.className.match(/osoc-motive-\w+/) || [null])[0]),
    };
  };
  window._orwellFirstCeremonyResolved = (st) => firstCeremonyResolved(st);


  // --- Poll loop ----------------------------------------------------------------

  async function refresh() {
    let st;
    try {
      st = await getJSON("/api/orwell/state");
    } catch (_) {
      // ENGINE HICCUP (not "no game"): keep a shown section up (U5) — just don't refresh
      // approaches. Only hide when we've never shown it (nothing to keep).
      if (window.OrwellReport) window.OrwellReport.fail("social", "state-poll", _); // G11: fail open, never silent
      _failures += 1;
      if (!_shown) hidePanel();
      return;
    }
    _failures = 0;
    if (!(st && st.started)) {
      _shown = false;
      _ceremonyResolved = false;
      hidePanel(); // genuinely no game
      return;
    }
    _shown = true;
    // E89 belt: track whether the first ceremony has resolved, from /state alone.
    _ceremonyResolved = firstCeremonyResolved(st);
    ensureSection();
    // H5: no minimize/dock/mobile-park bookkeeping anymore — the section is sidebar
    // chrome, and renderApproaches() owns whether it shows (chips) or collapses (none).
    // E89 belt: don't even ask for approaches before the first ceremony resolves — and if the
    // engine fails open, renderApproaches([]) still suppresses everything against the belt.
    if (!_ceremonyResolved) { renderApproaches([]); return; }
    try {
      const data = await getJSON("/api/orwell/initiatives");
      renderApproaches(data && data.initiatives);
    } catch (_) {
      // initiatives hiccup: leave the existing chips, never blank them on a transient error
      if (window.OrwellReport) window.OrwellReport.fail("social", "initiatives-poll", _); // G11: fail open, never silent
    }
  }

  function start() {
    refresh();
    if (timer) clearInterval(timer);
    const tick = async () => {
      if (!document.hidden) await refresh();  // C18: no polling in a hidden tab
      timer = setTimeout(tick, _pollDelay());
    };
    timer = setTimeout(tick, _pollDelay());
  }

  window.orwellRefreshSocial = refresh;
  // A new game starts a clean slate — forget who we waved off in the last one.
  window.addEventListener("orwell:gamechanged", () => { clearDismissed(); refresh(); });
  ready(start);
})();
