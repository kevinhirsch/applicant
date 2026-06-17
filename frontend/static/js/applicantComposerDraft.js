// Applicant composer draft (Lane G17 — refresh-persistence audit F3/F5/F7) — the player's
// typed turn survives a refresh.
//
// The G5 audit's literal commission ("text will prefill, I will refresh, and the text
// will not persist") pinned the cause: NO module persisted the composer. This one does —
// ONE session-scoped record per user:
//
//     applicant-composer-draft:<user>  →  { text, drMode, pendingApproachId }
//
//   • text              — the composer's live value (M1/M2/M9/M10/M17: the player's own
//                         words and every prefill ride the same record).
//   • drMode            — F5, THE PRIVACY GATE: a Diary-Room draft re-enters DR mode
//                         BEFORE its text lands back in the composer. A restored
//                         confessional sitting in a house-bound composer would be
//                         sendable to the house — the exact leak the Diary Room's
//                         "no in-game pathway to any NPC" contract forbids. If DR mode
//                         cannot engage, the text is WITHHELD (privacy over convenience)
//                         and the record kept intact for a boot that can.
//   • pendingApproachId — F7: an approach prefill keeps its pending chip accent and its
//                         send-dismisses-the-chip contract (the applicantSocial.js seam).
//
// Written debounced on composer input (immediately when the box empties — a sent turn
// must never be resurrectable by a refresh), and immediately when DR mode or the pending
// approach change (the applicant:drmode / applicant:approachpending hooks). Cleared on send
// (chat.js calls _applicantComposerDraftClear where the send path empties the composer).
// sessionStorage on purpose (the M21 retro-dismissal precedent): a session draft for the
// tab the player is playing in, never a forever draft.
(function () {
  "use strict";

  // E71 pattern: scoped per user, so one account's draft never bleeds into another's.
  const KEY = "applicant-composer-draft:" +
    ((document.body && document.body.dataset.user) || "");
  const DEBOUNCE_MS = 250;

  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  function box() { return document.getElementById("message"); }

  // --- the one record -------------------------------------------------------------

  function liveRecord() {
    const b = box();
    let pending = null;
    try { pending = window._applicantPendingApproach ? window._applicantPendingApproach.get() : null; } catch (_) {}
    return {
      text: b ? b.value : "",
      drMode: !!(window._applicantDiaryRoomActive && window._applicantDiaryRoomActive()),
      pendingApproachId: pending == null ? null : pending,
    };
  }

  let _timer = null;
  let _restoring = false; // restore() must never clobber the record it is reading back

  function save() {
    if (_restoring) return;
    const rec = liveRecord();
    try {
      if (!rec.text && !rec.drMode && rec.pendingApproachId === null) {
        sessionStorage.removeItem(KEY); // nothing transient left — drop the record
      } else {
        sessionStorage.setItem(KEY, JSON.stringify(rec));
      }
    } catch (_) { /* storage unavailable: a draft is a courtesy, never a blocker */ }
  }
  function saveSoon() { clearTimeout(_timer); _timer = setTimeout(save, DEBOUNCE_MS); }
  function saveNow() { clearTimeout(_timer); save(); }

  function clearDraft() {
    clearTimeout(_timer);
    try { sessionStorage.removeItem(KEY); } catch (_) {}
  }

  function load() {
    try {
      const raw = sessionStorage.getItem(KEY);
      const rec = raw ? JSON.parse(raw) : null;
      return rec && typeof rec === "object" ? rec : null;
    } catch (_) { return null; }
  }

  // --- restore on boot --------------------------------------------------------------

  function restore() {
    const rec = load();
    if (!rec) return;
    const b = box();
    if (!b || b.value.trim()) return; // live composer content always wins over the record
    _restoring = true; // the hooks below fire DURING restore — none may overwrite the record mid-read
    let restored = false;
    try {
      // F5 — THE ORDER IS THE CONTRACT: a Diary-Room draft re-enters DR mode FIRST,
      // and only then may its text land. If DR mode cannot engage (module missing or
      // failed), the confessional text is withheld entirely — it must never sit in a
      // composer whose send goes to the house. The record stays for a safer boot.
      if (rec.drMode) {
        let entered = false;
        try { entered = !!(window._applicantOpenDiaryRoom && window._applicantOpenDiaryRoom()); } catch (_) {}
        if (!entered || !(window._applicantDiaryRoomActive && window._applicantDiaryRoomActive())) return;
      }
      if (typeof rec.text === "string" && rec.text) {
        b.value = rec.text;
        b.dispatchEvent(new Event("input", { bubbles: true })); // autoresize + listeners hear it
      }
      // F7: the approach chip's pending accent + its send-dismisses contract survive too.
      if (rec.pendingApproachId != null && window._applicantPendingApproach &&
          window._applicantPendingApproach.restore) {
        window._applicantPendingApproach.restore(rec.pendingApproachId);
      }
      restored = true;
    } finally {
      _restoring = false;
      if (restored) saveNow(); // normalize the record to what actually landed
    }
  }

  // The inherited boot path fights a naive restore twice over:
  //   • init.js's clearFreshComposerRestore wipes a value-carrying composer on
  //     pageshow when no session target exists (it defeats the BROWSER's own form
  //     restoration) — and its wipe dispatches input, which would drop the record.
  //     So the first restore waits for pageshow and runs AFTER it (its listener is
  //     registered at module eval; ours at DOMContentLoaded — earlier in the order).
  //   • sessions.js empties #message when it re-selects the last-open session —
  //     with no input event, so the record survives. Restore is therefore re-attempted
  //     on a short boot schedule; every attempt is a no-op unless the record still
  //     exists AND the box is still empty (the player's own typing/sending updates or
  //     drops the record, which disarms the remaining attempts by itself).
  const BOOT_RETRY_MS = [300, 700, 1300, 2200];

  // --- wiring -------------------------------------------------------------------------

  function wire() {
    const b = box();
    if (b && !b._applicantDraftWired) {
      b._applicantDraftWired = true;
      b.addEventListener("input", (e) => {
        if (b.value) { saveSoon(); return; } // typing (and restored/prefilled text) debounces
        // An empty box: only the PLAYER's own clear (a trusted event) writes through —
        // the inherited boot wipes the composer programmatically (chatRenderer's
        // showWelcomeScreen reset, init.js's fresh-workspace wipe) and those must not
        // eat a draft awaiting its restore. The real send paths clear through the
        // explicit seam instead (chat.js calls _applicantComposerDraftClear; the Diary
        // Room's send normalizes via its applicant:drmode exit notify).
        if (e.isTrusted) saveNow();
      });
    }
    const form = document.getElementById("chat-form") || (b && b.form);
    if (form && !form._applicantDraftWired) {
      form._applicantDraftWired = true;
      // Flush AFTER the submit handlers ran: a real send leaves an empty box (the
      // record drops); a stop-click leaves the typed draft in place (it survives).
      form.addEventListener("submit", () => { setTimeout(saveNow, 0); });
    }
    // The two non-input legs of the record write through immediately on change.
    window.addEventListener("applicant:drmode", saveNow);
    window.addEventListener("applicant:approachpending", saveNow);
    // A new season is a clean slate (the E71/G15 precedent): a dead game's draft must
    // not ride into the next casting interview.
    window.addEventListener("applicant:gamechanged", clearDraft);
  }

  // chat.js calls this where the send path empties the composer (clear on send).
  window._applicantComposerDraftClear = clearDraft;
  // Test seam (the headless browser gate): read the stored record.
  window._applicantComposerDraftPeek = load;

  ready(() => {
    wire();
    window.addEventListener("pageshow", () => {
      restore();
      for (const ms of BOOT_RETRY_MS) setTimeout(restore, ms);
    });
  });
})();
