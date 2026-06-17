// Applicant decision guardrail (C20 / audit U1+U2) — confirm-on-binding, per ADR 0003.
//
// NOT a decision-card dashboard: play stays in conversation. This is the light guardrail on
// the COMMITMENT — when the engine pauses the loop on a pending player decision, a small card
// presents the engine's own prompt + LEGAL options, enforces the pick count, and requires one
// explicit Confirm. The confirmed selection posts ENGINE-DIRECT (POST /api/applicant/decision →
// submitDecision), so a hedge in prose can never bind through this surface; the engine still
// validates legality and stays idempotent. Dismissing the card (×) is always allowed — the
// player may instead talk it out with the game master, which drives the same validated seam.
//
// Input: chat.js dispatches `applicant:pending` with {pending} parsed from advanceGame /
// submitDecision tool results (Vault-free PendingDecisionView: kind, prompt, options[],
// appeals?, juror?, pick). Vault-free by construction; fail-open everywhere.
(function () {
  "use strict";

  const CARD_ID = "applicant-decision-card";

  // PendingDecisionView.kind → the SubmitDecisionReq wire field carrying the pick.
  // Mirrors GameSessionAdapter.toDecisionInput: `vote` carries every single-pick kind
  // except `replacement`; `choice` carries the nominations pair.
  const SINGLE_PICK_FIELD = {
    "houseguests-choice": "vote",
    "eviction-vote": "vote",
    "tie-break": "vote",
    "final-eviction": "vote",
    "juror-vote": "vote",
    "goodbye-message": "vote", // E34: the chosen tone rides `vote` (options are the tones)
    "replacement": "replacement",
  };
  const COMP_INTENTS = ["compete", "throw", "play-safe"];

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function removeCard() {
    const old = document.getElementById(CARD_ID);
    if (old) old.remove();
  }

  function ensureStyles() {
    if (document.getElementById("applicant-decision-css")) return;
    const st = document.createElement("style");
    st.id = "applicant-decision-css";
    st.textContent = `
      #${CARD_ID} {
        margin: .6rem auto; max-width: 640px; border-radius: 12px; padding: .8rem .9rem;
        background: var(--panel, #111); color: var(--fg, #9cdef2);
        border: 1px solid var(--accent, var(--red, #e06c75));
        font-size: .85rem; line-height: 1.5;
      }
      #${CARD_ID} .odec-head { display: flex; align-items: baseline; gap: .5rem; }
      #${CARD_ID} .odec-title { font-weight: 700; letter-spacing: .03em; flex: 1; }
      #${CARD_ID} .odec-x { cursor: pointer; border: none; background: none; color: inherit; opacity: .55; font-size: 1rem; }
      #${CARD_ID} .odec-x:hover { opacity: .9; }
      #${CARD_ID} .odec-prompt { margin: .35rem 0 .55rem; opacity: .9; }
      #${CARD_ID} .odec-opts { display: flex; flex-wrap: wrap; gap: .4rem; }
      #${CARD_ID} .odec-opt {
        cursor: pointer; border-radius: 999px; padding: .3rem .8rem;
        border: 1px solid var(--border, #355a66); background: rgba(255,255,255,.05); color: inherit;
        font: inherit;
      }
      #${CARD_ID} .odec-opt[aria-pressed="true"] { border-color: var(--accent, #e06c75); background: var(--accent, #e06c75); color: #fff; }
      #${CARD_ID} textarea {
        width: 100%; min-height: 72px; box-sizing: border-box; margin-top: .2rem;
        background: rgba(255,255,255,.05); color: inherit; border: 1px solid var(--border, #355a66);
        border-radius: 8px; padding: .5rem; font: inherit;
      }
      #${CARD_ID} .odec-row { display: flex; align-items: center; gap: .6rem; margin-top: .65rem; }
      #${CARD_ID} .odec-confirm {
        cursor: pointer; border: none; border-radius: 8px; padding: .42rem .95rem; font-weight: 700;
        background: var(--accent, #e06c75); color: #fff; font: inherit;
      }
      #${CARD_ID} .odec-confirm:disabled { opacity: .4; cursor: not-allowed; }
      #${CARD_ID} .odec-note { opacity: .65; font-size: .78em; flex: 1; }
      #${CARD_ID} .odec-err { color: var(--red, #e06c75); margin-top: .4rem; }
      #${CARD_ID}.odec-done { border-color: var(--border, #355a66); opacity: .8; }
    `;
    document.head.appendChild(st);
  }

  // Build the wire payload from the current selection; null = selection incomplete.
  function buildPayload(kind, sel, freeText, useVeto) {
    if (kind === "nominations") return sel.length === 2 ? { kind, choice: sel } : null;
    if (kind === "finale-statement") return { kind, statement: freeText || "" };
    if (kind === "juror-question") return { kind, statement: freeText || "" }; // E37: scoreless free text
    if (kind === "goodbye-message") {
      // E34: a tone is required; the optional message text rides `statement`.
      return sel.length === 1 ? { kind, vote: sel[0], statement: freeText || "" } : null;
    }
    if (kind === "finale-answer") return sel.length === 1 ? { kind, appeal: sel[0] } : null;
    if (kind === "comp-intent") return sel.length === 1 ? { kind, intent: sel[0] } : null;
    if (kind === "veto-decision") {
      if (useVeto === false) return { kind, use: false };
      return sel.length === 1 ? { kind, use: true, save: sel[0] } : null;
    }
    const field = SINGLE_PICK_FIELD[kind];
    if (field) return sel.length === 1 ? { kind, [field]: sel[0] } : null;
    return null;
  }

  function titleFor(kind) {
    return {
      "nominations": "Nomination ceremony — your nominations",
      "veto-decision": "Power of Veto — your call",
      "comp-intent": "Competition — set your approach",
      "houseguests-choice": "Houseguest's Choice — pick the sixth player",
      "replacement": "Veto ceremony — name the replacement",
      "eviction-vote": "Eviction — cast your vote",
      "tie-break": "Tied vote — as HOH, you decide",
      "final-eviction": "Final 3 — you evict, personally",
      "goodbye-message": "Goodbye message — your tone, your words",
      "finale-statement": "Finale — your statement to the jury",
      "finale-answer": "Jury question — choose your appeal",
      "juror-question": "Your jury question — ask the finalist",
      "juror-vote": "Your jury vote — crown a winner",
    }[kind] || "Your decision";
  }

  function render(pending) {
    removeCard();
    if (!pending || !pending.kind) return;
    ensureStyles();
    const chatBox = document.getElementById("chat-history");
    if (!chatBox) return;

    const kind = pending.kind;
    const pick = kind === "nominations" ? 2 : (typeof pending.pick === "number" ? Math.max(1, pending.pick) : 1);
    const multi = pick > 1;
    let sel = [];
    let useVeto = null; // veto-decision only: null=unchosen, true=use (pick save), false=don't

    const card = document.createElement("div");
    card.id = CARD_ID;
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", titleFor(kind));
    // Focused-context-first: while focus is in the card, Escape belongs to the
    // card's own dismiss-only handler (the global arbiter stands down on this marker).
    card.setAttribute("data-ow-escape-scope", "");

    const head = document.createElement("div");
    head.className = "odec-head";
    head.innerHTML = `<span class="odec-title">${esc(titleFor(kind))}</span>`;
    const x = document.createElement("button");
    x.className = "odec-x"; x.type = "button"; x.textContent = "×";
    x.title = "Dismiss — you can decide in conversation instead";
    x.setAttribute("aria-label", "Dismiss");
    x.addEventListener("click", removeCard);
    head.appendChild(x);
    card.appendChild(head);
    // F11 (DWE audit): Escape while the card holds focus = the × path — dismiss
    // only, NEVER a submit (the prose path stays open; #233's "Escape is the
    // keyboard way out" applied to the non-binding dismissal). Card-scoped so
    // the global arbiter and composer Escape behaviors are untouched.
    card.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      removeCard();
    });

    if (pending.prompt) {
      const p = document.createElement("div");
      p.className = "odec-prompt";
      p.textContent = pending.prompt + (pending.juror && pending.juror.name ? ` (asked by ${pending.juror.name})` : "");
      card.appendChild(p);
    }

    const opts = document.createElement("div");
    opts.className = "odec-opts";
    card.appendChild(opts);

    let textarea = null;
    const confirm = document.createElement("button");
    confirm.className = "odec-confirm"; confirm.type = "button";
    confirm.textContent = "Confirm — this is binding";
    confirm.disabled = true;

    const sync = () => { confirm.disabled = buildPayload(kind, sel, textarea && textarea.value.trim(), useVeto) == null; };

    const addChip = (label, value) => {
      const b = document.createElement("button");
      b.className = "odec-opt"; b.type = "button";
      b.setAttribute("aria-pressed", "false");
      b.textContent = label;
      b.addEventListener("click", () => {
        const on = b.getAttribute("aria-pressed") === "true";
        if (on) {
          sel = sel.filter((v) => v !== value);
          b.setAttribute("aria-pressed", "false");
        } else {
          if (!multi) {
            sel = [];
            opts.querySelectorAll('.odec-opt[aria-pressed="true"]').forEach((n) => n.setAttribute("aria-pressed", "false"));
          } else if (sel.length >= pick) {
            return; // pick-count enforced: deselect something first
          }
          sel.push(value);
          b.setAttribute("aria-pressed", "true");
        }
        sync();
      });
      opts.appendChild(b);
      return b;
    };

    if (kind === "finale-statement") {
      textarea = document.createElement("textarea");
      textarea.placeholder = "Your opening statement to the jury…";
      textarea.addEventListener("input", sync);
      card.appendChild(textarea);
      confirm.disabled = false; // a statement may be short; engine treats it as flavor
    } else if (kind === "juror-question") {
      // E37: scoreless free text — the player-juror's own question to the finalist.
      textarea = document.createElement("textarea");
      textarea.placeholder = "Your question to the finalist…";
      textarea.addEventListener("input", sync);
      card.appendChild(textarea);
      confirm.disabled = false; // free text; the engine scores nothing here
    } else if (kind === "goodbye-message") {
      // E34: pick a tone (the binding part) + optional message text (the model voices it).
      (pending.options || []).forEach((o) => addChip(o.name || String(o.id), o.id));
      textarea = document.createElement("textarea");
      textarea.placeholder = "Your goodbye message (optional — the tone is what binds)…";
      textarea.addEventListener("input", sync);
      card.appendChild(textarea);
    } else if (kind === "finale-answer") {
      (Array.isArray(pending.appeals) && pending.appeals.length ? pending.appeals : []).forEach((a) => addChip(String(a), String(a)));
    } else if (kind === "comp-intent") {
      COMP_INTENTS.forEach((i) => addChip(i, i));
    } else if (kind === "veto-decision") {
      const dont = addChip("Don't use the veto", "__dont__");
      dont.addEventListener("click", () => {
        useVeto = useVeto === false ? null : false;
        sel = [];
        opts.querySelectorAll('.odec-opt[aria-pressed="true"]').forEach((n) => n.setAttribute("aria-pressed", "false"));
        dont.setAttribute("aria-pressed", useVeto === false ? "true" : "false");
        sync();
      });
      (pending.options || []).forEach((o) => {
        const chip = addChip("Save " + (o.name || o.id), o.id);
        chip.addEventListener("click", () => {
          useVeto = sel.length === 1 ? true : null;
          dont.setAttribute("aria-pressed", "false");
          sync();
        });
      });
    } else {
      (pending.options || []).forEach((o) => addChip(o.name || String(o.id), o.id));
    }

    const row = document.createElement("div");
    row.className = "odec-row";
    const note = document.createElement("span");
    note.className = "odec-note";
    note.textContent = multi ? `Select ${pick}. The engine validates legality.` : "Your selection only — never read from prose.";
    row.appendChild(note);
    row.appendChild(confirm);
    card.appendChild(row);

    confirm.addEventListener("click", async () => {
      const payload = buildPayload(kind, sel, textarea && textarea.value.trim(), useVeto);
      if (!payload) return;
      confirm.disabled = true;
      confirm.textContent = "Locking in…";
      try {
        const r = await fetch("/api/applicant/decision", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error("HTTP " + r.status);
        // G15: a bound decision mutates the game — nudge every panel through the
        // shared debounced dispatcher NOW, not at the next 20–30s poll.
        if (window.applicantGameChanged) window.applicantGameChanged("decision:" + kind);
        card.classList.add("odec-done");
        card.innerHTML = `<div class="odec-head"><span class="odec-title">✓ Locked in.</span></div>`;
        // The play continues in conversation: prefill (never auto-send) so the model
        // narrates the ceremony from FRESH engine state on the player's next turn.
        const box = document.getElementById("message");
        if (box && !box.value.trim()) {
          box.value = "I've made my decision — let's see how the house takes it.";
          box.dispatchEvent(new Event("input", { bubbles: true }));
          box.focus();
        }
        setTimeout(removeCard, 4000);
      } catch (_) {
        if (window.ApplicantReport) window.ApplicantReport.fail("decision", "submit-post", _); // G11: fail open, never silent
        confirm.disabled = false;
        confirm.textContent = "Confirm — this is binding";
        let err = card.querySelector(".odec-err");
        if (!err) {
          err = document.createElement("div");
          err.className = "odec-err";
          card.appendChild(err);
        }
        err.textContent = "That didn't go through (illegal pick or the feed glitched). Adjust and try again, or decide in conversation.";
      }
    });

    chatBox.appendChild(card);
    card.scrollIntoView({ block: "nearest" });
  }

  // chat.js dispatches this from advanceGame/submitDecision tool results.
  // D3/E66: a pending decision must survive a reload. The card is event-mounted
  // on live turns; on boot (and on a game change) we re-arm it from the status
  // route's cached `pending` — the engine's own legal-options view. Without this,
  // refreshing mid-decision left the player with no card and no signal.
  async function rearmFromStatus() {
    try {
      const r = await fetch("/api/applicant/status", { credentials: "same-origin" });
      if (!r.ok) return;
      const st = await r.json();
      if (st && st.pending && st.pending.kind) {
        window.dispatchEvent(new CustomEvent("applicant:pending", { detail: { pending: st.pending } }));
      }
    } catch (_) { /* fail open */ }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", rearmFromStatus, { once: true });
  } else { rearmFromStatus(); }
  window.addEventListener("applicant:gamechanged", rearmFromStatus);

  window.addEventListener("applicant:pending", (e) => {
    try {
      render(e.detail && e.detail.pending);
    } catch (_) { /* fail open — the conversation path always remains */ }
  });
})();
