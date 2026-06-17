// Applicant Diary Room — a standing sidebar button + a COMPOSER MODE (E88, ruling #4).
//
// The Diary Room is not a window. The entry point is a permanent sidebar nav
// button (alongside New Chat / Search) that shows while a game is active;
// clicking it puts the CHAT COMPOSER into Diary-Room mode: a visible
// in-composer indicator, a private placeholder, and the send intercepted to
// POST /api/applicant/diary-room (the player's own OOC knowledge — no in-game
// pathway to any houseguest). Exit on send, Escape, or the indicator's ×.
// Chat-first per ADR 0003: the confessional is typed where everything else is.
(function () {
  "use strict";

  const BTN_ID = "sidebar-diary-room-btn";
  const PILL_ID = "applicant-dr-pill";
  let drMode = false;
  let _returnPlaceholder = null;

  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  function composerBox() { return document.getElementById("message"); }
  function composerForm() { return document.getElementById("chat-form") || (composerBox() && composerBox().form); }

  // --- the sidebar button (standing chrome, game-gated) -------------------------

  function ensureButton() {
    let btn = document.getElementById(BTN_ID);
    if (btn) return btn;
    const search = document.getElementById("sidebar-search-btn");
    if (!search || !search.parentElement) return null;
    btn = document.createElement("div");
    btn.className = "list-item";
    btn.id = BTN_ID;
    btn.setAttribute("role", "button");
    btn.setAttribute("tabindex", "0");
    btn.title = "Diary Room — private & out-of-character";
    btn.style.display = "none"; // shown while a game is active
    btn.innerHTML = `
      <svg class="sidebar-action-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
      <span class="grow">Diary Room</span>`;
    const enter = () => enterDRMode();
    btn.addEventListener("click", enter);
    btn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); enter(); }
    });
    search.parentElement.insertBefore(btn, search.nextSibling);
    return btn;
  }

  async function refreshGate() {
    const btn = ensureButton();
    if (!btn) return;
    try {
      const r = await fetch("/api/applicant/state", { credentials: "same-origin" });
      const st = r.ok ? await r.json() : null;
      btn.style.display = st && st.started ? "" : "none";
      if (!(st && st.started) && drMode) exitDRMode();
    } catch (_) { /* engine hiccup: leave the button as it was (fail-open) */ }
  }

  // --- the composer mode ---------------------------------------------------------

  function ensurePill() {
    let pill = document.getElementById(PILL_ID);
    if (pill) return pill;
    const form = composerForm();
    if (!form) return null;
    pill = document.createElement("div");
    pill.id = PILL_ID;
    pill.setAttribute("role", "status");
    pill.style.cssText = "display:none;align-items:center;gap:6px;margin:0 0 4px;" +
      "padding:3px 10px;border-radius:999px;width:fit-content;" +
      "background:color-mix(in srgb, var(--accent, #e06c75) 18%, transparent);" +
      "border:1px solid var(--accent, #e06c75);font-size:var(--fs-xs);";
    pill.innerHTML = `<span>📔 Diary Room — private &amp; out-of-character; the house never hears this.</span>
      <button type="button" id="applicant-dr-exit" aria-label="Leave the Diary Room" title="Leave the Diary Room"
        style="border:none;background:none;color:inherit;cursor:pointer;font-size:1em;padding:0 2px;">×</button>`;
    form.parentElement.insertBefore(pill, form);
    pill.querySelector("#applicant-dr-exit").addEventListener("click", exitDRMode);
    return pill;
  }

  // G17 (refresh-persistence audit F5): the composer-draft module persists the DR flag
  // WITH the draft — it must hear every mode change the moment it happens, so a
  // confessional-in-progress can never be stored as (or restored into) house-bound text.
  function notifyModeChange() {
    try { window.dispatchEvent(new CustomEvent("applicant:drmode", { detail: { active: drMode } })); } catch (_) {}
  }

  function enterDRMode() {
    const box = composerBox();
    const pill = ensurePill();
    if (!box || !pill) return;
    drMode = true;
    pill.style.display = "flex";
    document.body.classList.add("applicant-dr-mode");
    _returnPlaceholder = box.placeholder;
    box.placeholder = "Tell the producers what you're really thinking…";
    box.focus();
    notifyModeChange();
  }

  function exitDRMode() {
    const box = composerBox();
    const pill = document.getElementById(PILL_ID);
    drMode = false;
    if (pill) pill.style.display = "none";
    document.body.classList.remove("applicant-dr-mode");
    if (box && _returnPlaceholder !== null) { box.placeholder = _returnPlaceholder; _returnPlaceholder = null; }
    notifyModeChange();
  }

  async function submitDR(entry) {
    const r = await fetch("/api/applicant/diary-room", {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ entry }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
  }

  // Capture-phase interception: in DR mode the send is a confessional, never a chat
  // turn — the chat pipeline (and the agent) must not see it.
  function wireComposer() {
    const form = composerForm();
    const box = composerBox();
    if (!form || form._applicantDRWired || !box) return;
    form._applicantDRWired = true;
    form.addEventListener("submit", async (e) => {
      if (!drMode) return;
      e.preventDefault();
      e.stopImmediatePropagation();
      const entry = (box.value || "").trim();
      if (!entry) { box.focus(); return; }
      const pill = document.getElementById(PILL_ID);
      try {
        await submitDR(entry);
        box.value = "";
        box.dispatchEvent(new Event("input", { bubbles: true }));
        if (pill) {
          pill.firstElementChild.textContent = "📔 Recorded ✓ — between you and the producers.";
          setTimeout(exitDRMode, 900);
        } else { exitDRMode(); }
      } catch (_) {
        if (pill) pill.firstElementChild.textContent = "📔 The Diary Room camera glitched — try again.";
      }
    }, true);
    box.addEventListener("keydown", (e) => {
      if (drMode && e.key === "Escape") { e.preventDefault(); exitDRMode(); }
    });
  }

  // The one seam every flow uses (smoke gate, future prompts): enter the composer mode.
  window._applicantOpenDiaryRoom = () => { ensureButton(); wireComposer(); enterDRMode(); return true; };
  window._applicantDiaryRoomActive = () => drMode;

  function start() {
    ensureButton();
    wireComposer();
    refreshGate();
    window.addEventListener("applicant:gamechanged", refreshGate);
    setInterval(() => { if (!document.hidden) refreshGate(); }, 30000);
  }

  ready(start);
})();
