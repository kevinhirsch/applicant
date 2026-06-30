// Decision guardrail (C20 / audit U1+U2) — confirm-on-binding, per ADR 0003.
//
// NOT a decision-card dashboard: play stays in conversation. This is the light guardrail on
// the COMMITMENT — when the engine pauses the loop on a pending player decision, a small card
// presents the engine's own prompt + LEGAL options, enforces the pick count, and requires one
// explicit Confirm. The confirmed selection posts ENGINE-DIRECT (POST /api/appkit/decision →
// submitDecision), so a hedge in prose can never bind through this surface; the engine still
// validates legality and stays idempotent. Dismissing the card (×) is always allowed — the
// player may instead talk it out with the game master, which drives the same validated seam.
//
// #642: the decision card is the CHARTER member of the AppkitNotice kit (the above-composer
// affordance zone). It composes window.AppkitNoticeKit (kind "decision") for the shared
// anchor — it now mounts into the ONE stacked notice zone above the composer, so it STACKS
// deterministically beside the game guide (the decision sits closest to the composer) instead
// of scrolling inside #chat-history and fighting for the slot. It keeps its OWN rich internals
// (legal options, pick-count, the binding Confirm, the J5-20 risk skin, the per-signature
// dismiss + the boot/poll rearm) — the kit owns only the anchor; the decision is a HARD-STOP
// affordance (dismissible, NEVER auto-dismissed). The kit's own corner × is suppressed
// (dismissible:false) — the card renders its OWN .odec-x with the existing dismiss semantics.
//
// Input: chat.js dispatches `appkit:pending` with {pending} parsed from advanceGame /
// submitDecision tool results (Vault-free PendingDecisionView: kind, prompt, options[],
// appeals?, juror?, pick). Vault-free by construction; fail-open everywhere.
(function () {
  "use strict";

  const CARD_ID = "appkit-decision-card";

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

  // J5-20: the genuinely high-stakes, irreversible decision kinds — evicting someone, naming
  // nominees, crowning the winner. These bind a person's fate (theirs or the player's game),
  // so the card must carry a RISK signal that a low-stakes comp-intent/comp-round must NOT —
  // those only set how the player plays a comp, and never end anyone's game. Driven off this
  // single set so "which kinds are weighty" lives in one place (matches SINGLE_PICK_FIELD's
  // role as the canonical kind→behavior map).
  const HIGH_STAKES_KINDS = new Set([
    "eviction-vote",
    "final-eviction",
    "juror-vote",
    "nominations",
    // A veto replacement nominee is permanent (the named houseguest is on the block for
    // eviction day with no further appeal) and a HOH tie-break evicts someone outright — both
    // end a houseguest's game just like the four above, so they get the same risk skin.
    "replacement",
    "tie-break",
  ]);
  const isHighStakes = (kind) => HIGH_STAKES_KINDS.has(kind);

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // J5-06: a confirmed card schedules its own 4s self-removal. Track that timer so a NEW card
  // arming within the window cancels it — otherwise the stale timer fires removeCard() and yanks
  // the freshly-armed (live, unconfirmed) next decision card out from under the player (TRANS-4).
  let _doneTimer = null;
  let _notice = null;   // #642: the AppkitNotice kit instance hosting the card (the zone anchor).
  let _sheet = null;    // #753: the AppkitSheet (anchored, non-blocking action-sheet) hosting the card.
  function removeCard() {
    if (_doneTimer) { clearTimeout(_doneTimer); _doneTimer = null; }
    // #753: prefer the sheet host (the non-blocking action-sheet) when present; fall back to the
    // AppkitNotice host (the pre-#753 anchor) so a card mounted via either path tears down cleanly.
    if (_sheet) { try { _sheet.dismiss("api"); } catch (_) {} _sheet = null; }
    if (_notice) { try { _notice.hide(); } catch (_) {} _notice = null; }
    const old = document.getElementById(CARD_ID);
    if (old) old.remove();
  }

  function ensureStyles() {
    if (document.getElementById("appkit-decision-css")) return;
    const st = document.createElement("style");
    st.id = "appkit-decision-css";
    st.textContent = `
      #${CARD_ID} {
        position: relative; /* J5-21: anchors the absolutely-positioned dismiss × in the corner */
        margin: .6rem auto; max-width: 640px; border-radius: 12px; padding: .8rem .9rem;
        background: var(--panel, #111); color: var(--fg, #9cdef2);
        border: 1px solid var(--accent, var(--red, #e06c75));
        /* Shared type system (#709): sans family + body PRESET. */
        font-family: var(--ow-ui-font); font-size: var(--ow-fs-body, .875rem); line-height: 1.5;
        /* J5-03: figure/ground — the binding card must lift off the chat stream like every
           AppkitWindow does. Reuse the kit's shadow token (it is the only interactive surface
           that was missing it). */
        box-shadow: var(--win-shadow, 0 8px 32px rgba(0, 0, 0, 0.45));
        /* J5-05: a brief entrance + a transition on the done-state dim, so a binding decision
           neither pops in nor flips to "✓ Locked in" as a silent text swap. */
        animation: odec-in .18s ease-out;
        transition: opacity .2s ease, border-color .2s ease;
      }
      @keyframes odec-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
      @media (prefers-reduced-motion: reduce) { #${CARD_ID} { animation: none; transition: none; } }
      /* #642: hosted in the AppkitNotice kit card (.on-card.on-decision owns the lift/border/
         radius/anchor), the decision card goes FLAT — drop its own margin/max-width/shadow/
         border/animation so it fills the kit body (no double chrome, no squeezed note column). */
      .on-card.on-decision #${CARD_ID} {
        margin: 0; max-width: none; box-shadow: none; border: none; padding: 0;
        background: transparent; animation: none;
      }
      /* #753: hosted in the AppkitSheet anchored action-sheet (.ow-sheet-anchored owns the
         grabber/accent-rim/glass/anchor), the decision card goes FLAT exactly as in the notice
         host — drop its own margin/max-width/shadow/border/animation/bg so the sheet provides the
         one chrome (no double frame, no squeezed note column). */
      .ow-sheet.ow-sheet-anchored #${CARD_ID} {
        margin: 0; max-width: none; box-shadow: none; border: none; padding: 0;
        background: transparent; animation: none;
      }
      /* Under the glass theme the inner card must stay transparent (the sheet IS the glass) so it
         never double-glasses — mirrors the .on-card.on-decision frosted rule below. (The .odec-risk
         selector is listed FIRST so the j5_20 token-tint regex never matches this transparent rule.) */
      body.theme-frosted .ow-sheet.ow-sheet-anchored #${CARD_ID}.odec-risk,
      body.theme-frosted .ow-sheet.ow-sheet-anchored #${CARD_ID} {
        background-color: transparent; background-image: none;
        -webkit-backdrop-filter: none; backdrop-filter: none; box-shadow: none;
      }
      #${CARD_ID} .odec-head { display: flex; align-items: baseline; gap: .5rem; }
      #${CARD_ID} .odec-title { font-size: var(--ow-fs-title, .875rem); font-weight: var(--ow-fw-semibold, 600); letter-spacing: -.01em; flex: 1; }
      /* J5-21: the dismiss × stays visually in the top-right corner (absolute), but is moved to the
         END of the card's DOM so it is the LAST thing a keyboard user Tabs to — the decision options
         and Confirm come first (WCAG 2.4.3 focus order: a binding-decision surface must not put
         "skip this" ahead of the actual choice). Visual position is unchanged; only tab order moves.
         The 44×44 tap target + descriptive aria-label are preserved below. */
      #${CARD_ID} .odec-x { position: absolute; top: .35rem; right: .35rem; cursor: pointer; border: none; background: none; color: inherit; opacity: .75; font-size: 1rem; min-width: 44px; min-height: 44px; display: inline-flex; align-items: center; justify-content: center; }
      #${CARD_ID} .odec-x:hover { opacity: .9; }
      /* J5-20: a high-stakes, irreversible decision (eviction/noms/jury vote) wears a risk skin —
         an eviction-red border + a faint red wash so it never reads as a low-stakes comp chip. The
         tint is token-driven (--color-error / --red across the house themes). Color is NEVER the
         only signal: the .odec-risk-badge below carries the same "binding / irreversible" meaning in
         text + an icon for colorblind + SR users (the badge is what AT announces). */
      #${CARD_ID}.odec-risk {
        border-color: var(--color-error, var(--red, #e06c75));
        background:
          linear-gradient(0deg, color-mix(in srgb, var(--color-error, var(--red, #e06c75)) 9%, transparent), color-mix(in srgb, var(--color-error, var(--red, #e06c75)) 9%, transparent)),
          var(--panel, #111);
      }
      /* #775: a SELECTED option on a risk (irreversible) card keeps the eviction-RED fill — the
         stakes signal. !important so it wins over the style.css frosted selected-pill override
         (the kit-migration's neutral selected state) on the glass tiers too. */
      #${CARD_ID}.odec-risk .odec-opt[aria-pressed="true"] { border-color: var(--color-error, var(--red, #e06c75)) !important; background: var(--color-error, var(--red, #e06c75)) !important; color: var(--on-accent, #fff) !important; box-shadow: inset 0 1px 0 rgba(255,255,255,0.25) !important; }
      #${CARD_ID}.odec-risk .odec-confirm { background: var(--color-error, var(--red, #e06c75)); }
      #${CARD_ID} .odec-risk-badge {
        display: inline-flex; align-items: center; gap: .3rem; margin-left: .4rem;
        padding: .08rem .45rem; border-radius: 999px; font-size: .68rem; font-weight: 700;
        letter-spacing: .04em; text-transform: uppercase; white-space: nowrap;
        color: var(--color-error, var(--red, #e06c75));
        border: 1px solid color-mix(in srgb, var(--color-error, var(--red, #e06c75)) 60%, transparent);
        background: color-mix(in srgb, var(--color-error, var(--red, #e06c75)) 12%, transparent);
      }
      #${CARD_ID} .odec-prompt { margin: .35rem 0 .55rem; opacity: .9; }
      /* 0006 staged-rounds: the "still in this round" field — the narrowed roster the player reads to adapt. */
      #${CARD_ID} .odec-stillin { margin: 0 0 .55rem; font-size: .82em; opacity: .92; line-height: 1.45; }
      #${CARD_ID} .odec-stillin strong { letter-spacing: .02em; }
      #${CARD_ID} .odec-opts { display: flex; flex-wrap: wrap; gap: .4rem; }
      /* #775 element-kit migration (owner request): the decision OPTION chips compose the kit's
         .ow-btn .ow-btn-prominent (a liquid-glass PROMINENT CTA). On the GLASS tiers the kit owns
         the chip chrome (background/border/ink) — so the bespoke chip fill is scoped to the NORMAL
         (non-glass) tier here, and a frosted-tier SELECTED override lives in style.css. The
         layout-only bits (capsule radius, padding, tap floor) stay on both tiers. */
      #${CARD_ID} .odec-opt {
        cursor: pointer; border-radius: 999px; padding: .5rem .8rem; min-height: 44px;
        font: inherit;
      }
      /* Normal-tier (non-glass) chip chrome — the glass tiers take the kit prominent instead. */
      body:not(.theme-frosted) #${CARD_ID} .odec-opt {
        /* J5-04: the plain --border (#355a66) on the chip's translucent fill is ~2.25:1 on the
           dark panel — below WCAG 1.4.11's 3:1 for a UI-component boundary. Mix toward --fg so
           the chip edge is visible (the chip is the ONLY way to make the pick). */
        border: 1px solid color-mix(in srgb, var(--border, #355a66) 55%, var(--fg, #9cdef2)); background: rgba(255,255,255,.05); color: inherit;
      }
      body:not(.theme-frosted) #${CARD_ID} .odec-opt[aria-pressed="true"] { border-color: var(--accent, #e06c75); background: var(--accent, #e06c75); color: var(--on-accent, #fff); }
      #${CARD_ID} textarea {
        width: 100%; min-height: 72px; box-sizing: border-box; margin-top: .2rem;
        background: rgba(255,255,255,.05); color: inherit; border: 1px solid var(--border, #355a66);
        border-radius: 8px; padding: .5rem; font: inherit;
      }
      /* flex-wrap so the full-width .odec-hint (flex-basis:100%; order:99) drops to
         its OWN line instead of competing for width and crushing .odec-note (the
         description) into a one-word-per-line column. */
      #${CARD_ID} .odec-row { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; margin-top: .65rem; }
      #${CARD_ID} .odec-confirm {
        cursor: pointer; border: none; border-radius: 8px; padding: .42rem .95rem; font-weight: 700;
        min-height: 44px;
        background: var(--accent, #e06c75); color: var(--on-accent, #fff); font: inherit;
      }
      #${CARD_ID} .odec-confirm:disabled { opacity: .4; cursor: not-allowed; }
      #${CARD_ID} .odec-note { opacity: .80; font-size: var(--ow-fs-body, .875rem); flex: 1; }
      /* J4-20: the disabled-Confirm hint — quiet, italicized, sits beside the button; its hidden
         attribute is toggled in sync() so it shows only while Confirm can't be pressed. */
      #${CARD_ID} .odec-hint { opacity: .7; font-size: var(--ow-fs-caption, .75rem); font-style: italic; flex-basis: 100%; order: 99; margin-top: -.2rem; }
      #${CARD_ID} .odec-hint[hidden] { display: none; }
      #${CARD_ID} .odec-err { color: var(--color-error, var(--red, #e06c75)); margin-top: .4rem; }
      #${CARD_ID}.odec-done { border-color: var(--border, #355a66); opacity: .8; }
      /* Narrow: the note must not squeeze into a thin column beside the button —
         stack it full-width above a full-width Confirm. */
      @media (max-width: 480px) {
        #${CARD_ID} .odec-row { flex-direction: column; align-items: stretch; gap: .5rem; }
        #${CARD_ID} .odec-note { flex: none; order: -1; }
        #${CARD_ID} .odec-confirm { width: 100%; padding: .6rem .95rem; }
      }
      /* ── LIQUID GLASS (body.theme-frosted) ──────────────────────────────────────
         The decision card surface must read as the SAME ONE LIGHT GLASS as the rest of the
         family. The common path hosts #${CARD_ID} INSIDE the AppkitNotice kit card
         (.on-card.on-decision), where it goes FLAT (transparent/no chrome) so the glass comes
         from the kit (.on-card, painted the kube LIGHT glass by style.css). In the FALLBACK
         path (no kit → mounted bare into #chat-history) the card carries its OWN solid
         var(--panel) bg, so we glass IT directly here — with the ONE LIGHT GLASS, not a dark
         veil. Owner ruling: "there should be no old dark glass at all"; "the old dark glass
         shouldn't be the frosted fallback". The inline DARK-veil glass that used to live here
         (and made the FROSTED fallback dark) is RETIRED. We also neutralize the .odec-risk
         skin's SOLID var(--panel) wash (the eviction-red MEANING stays in the BORDER), and we
         DELIBERATELY DO NOT touch .odec-confirm — the primary CONFIRM button keeps its
         sanctioned system-blue CTA fill (the one tinted action per view). Applies to BOTH tiers
         (no :not(.glass-full) — the light fill is uniform; Full adds SVG refraction on top via
         liquidGlass.js). Scoped to prefers-reduced-transparency:no-preference so the fallback
         card honors the a11y opaque preference under reduce. */
      @media (prefers-reduced-transparency: no-preference) {
      /* The ONE LIGHT GLASS for BOTH tiers (Full adds SVG refraction on top). */
      body.theme-frosted #${CARD_ID},
      body.theme-frosted #${CARD_ID}.odec-risk {
        background-color: var(--ow-glass-light-color);
        background-image: var(--ow-glass-light-fill);
        -webkit-backdrop-filter: blur(3px) saturate(180%);
        backdrop-filter: blur(3px) saturate(180%);
        border-radius: var(--ow-glass-radius);
        /* The light-glass rim + soft light shadow (matches style.css's ONE LIGHT GLASS). */
        box-shadow:
          inset 0 1px 0 rgba(255,255,255,0.65),
          inset 0 0 0 0.5px rgba(255,255,255,0.30),
          0 12px 36px rgba(0,0,0,0.10);
        color: #16191f;
        text-shadow: 0 1px 1px rgba(255,255,255,0.45);
      }
      /* When hosted inside the kit card the inner decision card stays flat (the kit IS the
         glass) — keep it transparent under theme-frosted so it never double-glasses. */
      body.theme-frosted .on-card.on-decision #${CARD_ID},
      body.theme-frosted .on-card.on-decision #${CARD_ID}.odec-risk {
        background-color: transparent;
        background-image: none;
        -webkit-backdrop-filter: none;
        backdrop-filter: none;
        box-shadow: none;
      }
      }
      /* SANCTIONED ACCENT — NOTE: the primary Confirm CTA's system-blue fill is owned by
         style.css (body.theme-frosted .odec-confirm → background: var(--ow-ios-blue,#0a84ff)
         !important, the ONE tinted CTA per view). The glass block above scopes to the CARD
         surface only and never names .odec-confirm, so it cannot wash out that CTA — the
         blue stands. We deliberately add NO .odec-confirm rule here (it would only weaken /
         duplicate the static !important system-blue rule). */
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
    // 0006 staged-rounds: the per-round approach rides `intent` exactly like comp-intent (committed for
    // THIS round only). Structured selection only — never read from prose.
    if (kind === "comp-round") return sel.length === 1 ? { kind, intent: sel[0] } : null;
    // 0061 — a confirmed self-eviction needs no pick; ONLY the explicit confirm flag binds it.
    if (kind === "self-evict") return { kind, confirmed: true };
    if (kind === "veto-decision") {
      if (useVeto === false) return { kind, use: false };
      return sel.length === 1 ? { kind, use: true, save: sel[0] } : null;
    }
    const field = SINGLE_PICK_FIELD[kind];
    if (field) return sel.length === 1 ? { kind, [field]: sel[0] } : null;
    return null;
  }

  function titleFor(kind, binding) {
    // J4-17: a binding first comp-round and a non-binding flavor round previously shared one
    // title — only the button label/note differed, so the two looked identical at a glance. The
    // binding round is the one that sets the approach the single outcome roll honors; a later
    // round is color over an already-decided result. Title them distinctly so the stakes read
    // from the heading, not just the fine print. (Copy only — the binding flag comes from the
    // engine's PendingDecisionView; this asserts no board state.)
    if (kind === "comp-round") {
      return binding === false
        ? "Competition round — keep pushing (no stakes)"
        : "Competition round — set your approach";
    }
    return {
      "nominations": "Nomination ceremony — your nominations",
      "veto-decision": "Power of Veto — your call",
      "comp-intent": "Competition — set your approach",
      "comp-round": "Competition round — your approach this round",
      "houseguests-choice": "Houseguest's Choice — pick the sixth player",
      "replacement": "Veto ceremony — name the replacement",
      "eviction-vote": "Eviction — cast your vote",
      "tie-break": "Tied vote — as HOH, you decide",
      "final-eviction": "Final 3 — you evict, personally",
      "goodbye-message": "Goodbye message — your tone, your words",
      "finale-statement": "Opening statement — address the jury",
      "finale-answer": "Jury question — choose your appeal",
      "juror-question": "Your jury question — ask the finalist",
      "juror-vote": "Your jury vote — crown a winner",
      "self-evict": "Self-eviction — leave the game?",
    }[kind] || "Your decision";
  }

  function confirmLabelFor(kind, binding) {
    if (kind === "self-evict") return "Confirm — leave the game (final)";
    if (kind === "comp-round") return binding === false ? "Push through this round" : "Lock in your approach";
    return "Confirm — this is binding";
  }

  // J4-20 (WCAG 3.3.2): the instruction shown — and announced via aria-describedby — while Confirm
  // is disabled, so the player knows what is still needed to enable it. Kind-aware so the hint names
  // the actual missing input (a tone, two nominees, a single pick). Copy only — never a board claim.
  function disabledHintFor(kind, pick, multi) {
    if (kind === "nominations") return "Select 2 houseguests to enable Confirm.";
    if (kind === "goodbye-message") return "Pick a tone to enable Confirm — your written message is optional.";
    if (kind === "veto-decision") return "Choose to use the veto (and who to save) or not, to enable Confirm.";
    if (multi) return `Select ${pick} to enable Confirm.`;
    return "Make your selection above to enable Confirm.";
  }

  // F-NEW-5: a kind-specific (never auto-sent) prefill cue so the dramatic context
  // of the locked-in decision carries into the player's next conversational turn —
  // a single generic line lost the moment. Falls back to the generic cue.
  function prefillCueFor(kind) {
    const cues = {
      nominations: "I've named my nominees — let's see the room when I say it out loud.",
      "veto-decision": "I've decided on the veto — time to make it official at the ceremony.",
      "finale-statement": "I've made my final case to the jury — let's see how it lands.",
      "juror-question": "I've decided what to ask — let's hear their answer.",
      "finale-answer": "I've cast my jury vote — let's see who takes it.",
      "goodbye-message": "I've recorded my goodbye message — let's see how the house reacts.",
      "comp-intent": "I've set my approach for this competition — let's compete.",
      "comp-round": "I'm committing to this round — let's push on.",
      "self-evict": "I've made my choice to walk — let's see how the house takes it.",
    };
    return cues[kind] || "I've made my decision — let's see how the house takes it.";
  }

  function render(pending) {
    removeCard();
    if (!pending || !pending.kind) return;
    ensureStyles();
    // #642: the card mounts into the AppkitNotice kit's above-composer zone (the kit anchors it
    // above .chat-input-bar). Require the kit + the composer anchor; fall back to the in-stream
    // #chat-history host only if the kit is unavailable (fail-open — the card must always reach
    // the player). The chat-history existence is still the boot-readiness signal the rearm uses.
    const chatBox = document.getElementById("chat-history");
    const hasKit = !!(window.AppkitNoticeKit && document.querySelector(".chat-input-bar"));
    if (!chatBox && !hasKit) return;

    const kind = pending.kind;
    const pick = kind === "nominations" ? 2 : (typeof pending.pick === "number" ? Math.max(1, pending.pick) : 1);
    const multi = pick > 1;
    let sel = [];
    let useVeto = null; // veto-decision only: null=unchosen, true=use (pick save), false=don't

    const card = document.createElement("div");
    card.id = CARD_ID;
    // J4-02: role="form" makes this a named form landmark (AT users can reach it
    // via landmark navigation and know a binding decision is required).
    card.setAttribute("role", "form");
    card.setAttribute("aria-label", titleFor(kind, pending.binding));
    // J4-12: link the card to the instruction note so SR users hear the decision
    // context + the "your selection only" / irreversibility instruction before
    // they Tab into options.
    card.setAttribute("aria-describedby", CARD_ID + "-note");
    // Focused-context-first: while focus is in the card, Escape belongs to the
    // card's own dismiss-only handler (the global arbiter stands down on this marker).
    card.setAttribute("data-ow-escape-scope", "");

    // J5-20: a high-stakes kind wears the risk skin (red border/wash) AND a textual "binding /
    // irreversible" badge — never color alone. The badge text rides in the title's aria-label
    // (set via the card's existing aria-label + the visible badge) so colorblind + SR users get
    // the same weight signal sighted users get from the tint.
    const risk = isHighStakes(kind);
    if (risk) card.classList.add("odec-risk");
    // J4-04: expose the binding state as a data attribute so a non-binding staged comp-round
    // (flavor over an already-decided result) is inspectable/testable — not only distinguishable
    // via the confirm label. `pending.binding === false` ⇒ "false"; everything else binds ⇒ "true".
    card.dataset.binding = String(pending.binding !== false);

    const head = document.createElement("div");
    head.className = "odec-head";
    // J5-20: append the risk badge after the title — "⚠ Irreversible" carries the stakes in
    // text + an icon, so the signal survives without color (the SR companion to the red tint).
    head.innerHTML = `<span class="odec-title">${esc(titleFor(kind, pending.binding))}</span>`
      + (risk ? `<span class="odec-risk-badge" role="note">⚠ Irreversible — binding</span>` : "");
    // J5-21: the dismiss × is created here (so the keydown/Escape handler can reference it) but is
    // NOT appended to the head — it is appended to the card LAST (after the row) so it falls last in
    // tab order. CSS positions it absolutely back into the top-right corner.
    const x = document.createElement("button");
    x.className = "odec-x"; x.type = "button"; x.textContent = "×";
    x.title = "Dismiss — you can decide in conversation instead";
    // J4-03: aria-label must be as descriptive as the title so AT users hear the same
    // context as sighted users who hover. "Dismiss" alone gives no intent signal.
    x.setAttribute("aria-label", "Dismiss — decide in conversation instead");
    x.addEventListener("click", () => { _userDismissed = true; _dismissedSig = _sig(pending); removeCard(); });
    card.appendChild(head);
    // F11 (DWE audit): Escape while the card holds focus = the × path — dismiss
    // only, NEVER a submit (the prose path stays open; #233's "Escape is the
    // keyboard way out" applied to the non-binding dismissal). Card-scoped so
    // the global arbiter and composer Escape behaviors are untouched.
    card.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      _userDismissed = true;
      _dismissedSig = _sig(pending);
      removeCard();
    });

    if (pending.prompt) {
      const p = document.createElement("div");
      p.className = "odec-prompt";
      p.textContent = pending.prompt + (pending.juror && pending.juror.name ? ` (asked by ${pending.juror.name})` : "");
      card.appendChild(p);
    }

    // 0006 staged-rounds: show WHO IS STILL IN this elimination round so the player adapts their
    // approach to the narrowed field (e.g. everyone left is an ally → throw; a threat still in → compete).
    if (kind === "comp-round" && Array.isArray(pending.stillIn) && pending.stillIn.length) {
      const still = document.createElement("div");
      still.className = "odec-stillin";
      const names = pending.stillIn.map((r) => esc(r.name || String(r.id))).join(", ");
      const r = (typeof pending.round === "number" && pending.round > 0) ? `Round ${pending.round} — ` : "";
      still.innerHTML = `<strong>${r}Still in:</strong> ${names}`;
      card.appendChild(still);
    }

    const opts = document.createElement("div");
    opts.className = "odec-opts";
    card.appendChild(opts);

    let textarea = null;
    const confirm = document.createElement("button");
    // #775 (owner request): the Confirm / "Evict" CTA composes the kit's .ow-btn .ow-btn-prominent
    // for the kit's state machinery (focus ring, press, disabled). Its legible FILL stays the
    // sanctioned system-blue (style.css body.theme-frosted .odec-confirm, !important color:#fff) —
    // or eviction-RED on a risk card — so the label is ALWAYS white-on-accent, never dark-on-dark.
    confirm.className = "ow-btn ow-btn-prominent odec-confirm"; confirm.type = "button";
    // 0006 staged-rounds: only the FIRST comp-round BINDS (the approach the single outcome roll honors);
    // later rounds are non-binding FLAVOR over an already-decided result (audit 2026-06-20) — phrase the
    // confirm so a flavor round reads as "push through", never a fresh stakes commitment. Single source
    // of truth: confirmLabelFor (also reused on the error-recovery relabel).
    confirm.textContent = confirmLabelFor(kind, pending.binding);
    confirm.disabled = true;

    // J4-20 (WCAG 3.3.2 — instructions on a disabled control): a disabled Confirm previously gave
    // no hint about WHY it was disabled or WHAT to do. Add a hint that says what's still needed; it
    // is announced to AT via the confirm button's aria-describedby and shown visibly only while the
    // button is disabled (hidden once the move is legal, so it never clutters a ready card).
    const hint = document.createElement("span");
    hint.className = "odec-hint";
    hint.id = CARD_ID + "-hint";
    hint.textContent = disabledHintFor(kind, pick, multi);

    const sync = () => {
      confirm.disabled = buildPayload(kind, sel, textarea && textarea.value.trim(), useVeto) == null;
      // J4-20: surface the hint only while Confirm can't be pressed.
      hint.hidden = !confirm.disabled;
    };

    const addChip = (label, value) => {
      const b = document.createElement("button");
      b.className = "ow-btn ow-btn-prominent odec-opt"; b.type = "button";
      b.setAttribute("aria-pressed", "false");
      b.textContent = label;
      b.addEventListener("click", () => {
        const on = b.getAttribute("aria-pressed") === "true";
        if (on) {
          // R2-01: comp-round/comp-intent are required single-picks with a pre-selected default
          // (a non-binding flavor round arms "compete" + enables "Push through"). Re-tapping the
          // lit chip must NOT clear it — that left Confirm stuck disabled with no cue. Other kinds
          // keep their toggle-off (e.g. the veto "Don't use" chip legitimately deselects).
          if (!multi && (kind === "comp-round" || kind === "comp-intent")) return;
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
      textarea.setAttribute("aria-label", "Your opening statement to the jury"); // J5-02: placeholders aren't accessible names
      textarea.addEventListener("input", sync);
      card.appendChild(textarea);
      confirm.disabled = false; // a statement may be short; engine treats it as flavor
    } else if (kind === "juror-question") {
      // E37: scoreless free text — the player-juror's own question to the finalist.
      textarea = document.createElement("textarea");
      textarea.placeholder = "Your question to the finalist…";
      textarea.setAttribute("aria-label", "Your question to the finalist"); // J5-02
      textarea.addEventListener("input", sync);
      card.appendChild(textarea);
      confirm.disabled = false; // free text; the engine scores nothing here
    } else if (kind === "goodbye-message") {
      // E34: pick a tone (the binding part) + optional message text (the model voices it).
      (pending.options || []).forEach((o) => addChip(o.name || String(o.id), o.id));
      textarea = document.createElement("textarea");
      textarea.placeholder = "Your goodbye message (optional — the tone is what binds)…";
      textarea.setAttribute("aria-label", "Your goodbye message (optional)"); // J5-02
      textarea.addEventListener("input", sync);
      card.appendChild(textarea);
    } else if (kind === "finale-answer") {
      (Array.isArray(pending.appeals) && pending.appeals.length ? pending.appeals : []).forEach((a) => addChip(String(a), String(a)));
    } else if (kind === "comp-intent" || kind === "comp-round") {
      // 0006 staged-rounds: the same compete/throw/play-safe approaches, but per-round for comp-round.
      const chips = COMP_INTENTS.map((i) => addChip(i, i));
      // audit 2026-06-20: only the FIRST comp-round binds (the intent the single outcome roll honored).
      // A later round is non-binding FLAVOR over an already-decided result — default it to "compete" so
      // the player can one-click "Push through" (still free to pick a different colour, or dismiss).
      if (kind === "comp-round" && pending.binding === false && chips[0]) {
        sel = [COMP_INTENTS[0]];
        chips[0].setAttribute("aria-pressed", "true");
        confirm.disabled = false;
      }
    } else if (kind === "self-evict") {
      // 0061: no options to pick — an explicit Confirm IS the irreversible decision (a Cancel
      // button is added to the row below, posting the engine cancel so the player plays on).
      confirm.disabled = false;
      confirm.textContent = "Confirm — leave the game (final)";
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
    note.id = CARD_ID + "-note";
    if (kind === "self-evict") {
      note.textContent = "This ends and forfeits your game — it cannot be undone.";
    } else if (kind === "comp-round") {
      // 0006 staged-rounds (audit 2026-06-20): the first round sets the binding approach; later rounds
      // are color over an already-decided result, so say so plainly rather than implying fresh stakes.
      note.textContent = pending.binding === false
        ? "No stakes here — your approach was locked in round one. Push through, or dismiss to play it out in conversation."
        : "This sets how you play the comp. Your selection only — never read from prose.";
    } else if (kind === "juror-question") {
      // J5-01: this card IS a prose textarea — the generic "never read from prose" note (announced
      // via aria-describedby) directly contradicted the only input on the card.
      note.textContent = "Your own words — type your question, then Confirm. Leave it blank to pass.";
    } else if (kind === "finale-statement") {
      note.textContent = "Your own words — type your statement to the jury, then Confirm.";
    } else if (kind === "goodbye-message") {
      // J5-01: the tone chip binds (the written message is optional) — say so, since Confirm stays
      // disabled until a tone is picked and nothing else explained why.
      note.textContent = "Pick a tone — that's what binds. Your written message is optional.";
    } else {
      // UX-9: this note is the card's aria-describedby source, announced at nominations /
      // the eviction vote. "never read from prose" is OOC engine-language that breaks the
      // fiction — reword to a player-facing line that still says the choice is the player's
      // (the button selection is what counts, not anything typed in chat).
      // J3-22: first-timer "binding" context — the Confirm button says "this is binding" but never
      // says what binding MEANS. Spell it out for the genuinely irreversible kinds (the high-stakes
      // set wears the ⚠ badge): once you confirm, it's locked and plays out — you can't take it back.
      const base = multi ? `Select ${pick} — only a legal move counts.` : "Your choice here is what counts — make it with the buttons.";
      note.textContent = risk ? base + " Once you confirm, it's locked in and plays out — there's no taking it back." : base;
    }
    row.appendChild(note);
    // 0061: a self-eviction confirmation gets an explicit CANCEL — declining must clear the engine
    // confirmation so the player simply plays on (never a fabricated, half-committed exit).
    if (kind === "self-evict") {
      const cancel = document.createElement("button");
      // #775: the self-evict Cancel is a standard secondary action, NOT a selectable option chip —
      // give it the kit's secondary variant (the .odec-opt layout class stays for the row sizing),
      // never the prominent option-chip treatment + aria-pressed toggle semantics.
      cancel.className = "ow-btn ow-btn-secondary odec-opt"; cancel.type = "button";
      cancel.textContent = "Cancel — stay in the house";
      cancel.addEventListener("click", async () => {
        _userDismissed = true;
        _dismissedSig = _sig(pending);
        try {
          await fetch("/api/appkit/self-eviction/cancel", { method: "POST", credentials: "same-origin" });
        } catch (_) { if (window.AppkitReport) window.AppkitReport.fail("self-evict", "cancel-post", _); }
        if (window.appkitGameChanged) window.appkitGameChanged("self-evict:cancel");
        removeCard();
      });
      row.appendChild(cancel);
    }
    row.appendChild(confirm);
    // J4-20: the disabled-state hint rides in the row beside Confirm; sync() toggles its `hidden`.
    // Cards that start with Confirm already enabled (free-text statements/questions, the non-binding
    // flavor round, self-evict) never need it, so suppress it when Confirm is not initially disabled.
    if (confirm.disabled) { hint.hidden = false; confirm.setAttribute("aria-describedby", hint.id); row.appendChild(hint); }
    card.appendChild(row);

    // J4-09: pre-declare the error region before it might be populated — dynamic
    // live-region injection is unreliable across AT/browser pairs; a pre-existing
    // role="alert" ensures all AT pairs announce the error text when it's set.
    const err = document.createElement("div");
    err.className = "odec-err";
    err.setAttribute("role", "alert");
    err.setAttribute("aria-live", "assertive");
    err.setAttribute("aria-atomic", "true");
    card.appendChild(err);

    // J5-21: append the dismiss × LAST so it is the final tab stop — the options/textarea and Confirm
    // (built above) come first. CSS (position:absolute, top/right) keeps it visually in the corner;
    // Escape-to-dismiss still works via the card-scoped keydown handler above. Focus-on-mount below
    // targets the card itself (tabindex=-1), unaffected by DOM order.
    card.appendChild(x);

    confirm.addEventListener("click", async () => {
      const payload = buildPayload(kind, sel, textarea && textarea.value.trim(), useVeto);
      if (!payload) return;
      confirm.disabled = true;
      confirm.textContent = "Locking in…";
      try {
        const r = await fetch("/api/appkit/decision", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw Object.assign(new Error("HTTP " + r.status), { httpStatus: r.status });
        _userDismissed = true;   // this pending is handled — stop any boot re-assert loop
        _dismissedSig = _sig(pending);
        // G15: a bound decision mutates the game — nudge every panel through the
        // shared debounced dispatcher NOW, not at the next 20–30s poll.
        if (window.appkitGameChanged) window.appkitGameChanged("decision:" + kind);
        card.classList.add("odec-done");
        card.innerHTML = `<div class="odec-head"><span class="odec-title">✓ Locked in.</span></div>`;
        // The play continues in conversation: prefill (never auto-send) so the model
        // narrates the ceremony from FRESH engine state on the player's next turn.
        // F-NEW-5: branch the prefill cue on the decision kind so the dramatic context
        // carries over — a generic "I've made my decision" loses the moment.
        const box = document.getElementById("message");
        if (box && !box.value.trim()) {
          box.value = prefillCueFor(kind);
          box.dispatchEvent(new Event("input", { bubbles: true }));
          box.focus();
        }
        _doneTimer = setTimeout(() => {
          // J5-06: only remove if THIS card is still the lingering done-card — never a card that
          // re-armed into the same id within the 4s window (removeCard() also clears this timer).
          // #642/#753: remove the host (sheet or notice) too (if any) so no empty wrapper lingers.
          if (card.isConnected && card.classList.contains("odec-done")) {
            if (_sheet) { try { _sheet.dismiss("api"); } catch (_) {} _sheet = null; }
            if (_notice) { try { _notice.hide(); } catch (_) {} _notice = null; }
            card.remove();
          }
          _doneTimer = null;
        }, 4000);
      } catch (_) {
        if (window.AppkitReport) window.AppkitReport.fail("decision", "submit-post", _); // G11: fail open, never silent
        confirm.disabled = false;
        // J4-08: restore the correct confirm label — mirrors the initial render,
        // including the self-evict irreversibility signal and non-binding round phrasing.
        confirm.textContent = confirmLabelFor(kind, pending.binding);
        // F-NEW-6: branch the recovery copy on the HTTP status — the correct next step
        // differs by failure mode and the player can't otherwise tell which. A 409 (the
        // board moved since this card armed) self-heals via the rearm seam, so we say so;
        // a 400 means the move itself was illegal (pick another); anything else (network
        // exception with no httpStatus, or a 5xx) is a connection problem. J4-09: err is
        // pre-declared role="alert" — setting textContent triggers the announcement.
        const status = _ && _.httpStatus;
        if (status === 409) {
          err.textContent = "The board moved since this card appeared — refreshing the latest state. Try again in a moment, or decide in conversation.";
        } else if (status === 400) {
          err.textContent = "That move isn't legal right now — pick another, or decide in conversation.";
        } else {
          err.textContent = "Connection problem — that didn't reach the house. Try again, or decide in conversation.";
        }
      }
    });

    // #753 (Genius #15/16/17): the decision card is now a NON-BLOCKING ANCHORED ACTION-SHEET
    // (AppkitSheet, anchored placement) above the composer — deliberate, not a snap-modal that
    // blocks the whole screen, so the player can keep reading the room and still talk it out
    // instead. The sheet is the anchor/chrome (grabber + accent rim + glass fill); the existing
    // #appkit-decision-card element is appended INTO the sheet body so ALL its rich internals
    // (legal options, pick-count, the binding Confirm, the J5-20 risk skin, the per-signature
    // dismiss, the boot/poll rearm) and every CSS selector / escape-scope are untouched. The
    // decision is a live HARD-STOP affordance: the sheet renders dismissible:false (no kit ×, no
    // swipe-away) — the card carries its OWN .odec-x with the per-signature dismiss semantics, and
    // its card-scoped Escape still dismisses. Fail-open chain: AppkitSheet → the pre-#753
    // AppkitNotice anchor → the in-stream #chat-history.
    const hasSheet = !!(window.AppkitSheetKit && window.AppkitSheetKit.create &&
      (document.querySelector(".chat-input-bar") || document.getElementById("chat-bar") ||
       (window.AppkitNoticeKit && window.AppkitNoticeKit.ensureZone)));
    if (hasSheet) {
      _sheet = window.AppkitSheetKit.create({
        id: "appkit-decision-sheet",
        anchored: true,                 // non-modal: no scrim, no inert background — keep reading the room
        title: titleFor(kind, pending.binding),
        role: "group",                  // the inner card is the role="form" landmark; don't double it
        dismissible: false,             // a live hard-stop: the card owns its own .odec-x dismiss
      });
      const host = _sheet.ensure();     // the .ow-sheet-body of the anchored action-sheet
      // The sheet's title row would duplicate the card's own .odec-title — hide the sheet header so
      // the card brings the single title + risk badge (no double chrome).
      const sheetHead = _sheet.el && _sheet.el.querySelector(".ow-sheet-head");
      if (sheetHead) sheetHead.style.display = "none";
      host.appendChild(card);
    } else if (hasKit) {
      // Pre-#753 fallback: mount into the AppkitNotice kit's stacked above-composer zone (kind
      // "decision"). Suppress the kit × (dismissible:false) — the card carries its OWN .odec-x.
      _notice = window.AppkitNoticeKit.create({
        id: "appkit-decision-notice",
        kind: "decision",
        title: titleFor(kind, pending.binding),
        role: "presentation",
        dismissible: false,
        persistDismiss: false,
      });
      const host = _notice.ensure();   // the .on-body of the stacked kit card
      const kitHead = _notice.el && _notice.el.querySelector(".on-head");
      if (kitHead) kitHead.style.display = "none";
      host.appendChild(card);
    } else {
      chatBox.appendChild(card);
    }
    card.scrollIntoView({ block: "nearest" });
    // J3-18: move focus to the card so keyboard/SR users know a binding decision appeared.
    // tabindex=-1 allows programmatic focus without adding the card to the Tab order.
    card.setAttribute("tabindex", "-1");
    card.focus();
  }

  // chat.js dispatches this from advanceGame/submitDecision tool results.
  // D3/E66: a pending decision must survive a reload. The card is event-mounted
  // on live turns; on boot (and on a game change) we re-arm it from the status
  // route's cached `pending` — the engine's own legal-options view. Without this,
  // refreshing mid-decision left the player with no card and no signal.
  let _userDismissed = false;   // set when the player explicitly dismisses (×/Escape)
  // F2 (audit): the signature of the pending the player dismissed, so a later `gamechanged`
  // (or the status re-poll) re-arms a genuinely NEW decision but NEVER re-shoves the SAME card
  // the player just waved away to decide in conversation.
  let _dismissedSig = null;
  const _sig = (p) => (p && p.kind)
    ? p.kind + "|" + ((p.options || []).map((o) => o && o.id).join(",")) + "|" + (p.prompt || "")
    : "";
  async function rearmFromStatus() {
    try {
      const r = await fetch("/api/appkit/status", { credentials: "same-origin" });
      if (!r.ok) return;
      const st = await r.json();
      const pending = st && st.pending && st.pending.kind ? st.pending : null;
      if (!pending) return;
      // F2: don't re-nag the EXACT card the player dismissed — a `gamechanged` / re-poll of the
      // SAME pending must stay dismissed; only a genuinely DIFFERENT pending re-arms.
      if (_userDismissed && _sig(pending) === _dismissedSig) return;
      _userDismissed = false;   // a fresh (different) pending arrived — honor it again
      // The game build mounts #chat-history ASYNCHRONOUSLY and then renders the session's
      // history INTO it after DOMContentLoaded — a boot rearm that fired early either had
      // no host or got wiped when the history re-rendered, so a refresh mid-decision left
      // the player with no card (the E66 path was a no-op in practice). Re-assert the card
      // until it is STABLY mounted (survives the boot history render), then stop — never
      // fight an explicit dismissal or a submit (both set _userDismissed).
      let stable = 0;
      for (let i = 0; i < 25 && !_userDismissed; i++) {
        const host = document.getElementById("chat-history");
        // A lingering "✓ Locked in" (.odec-done) card from the PRIOR decision must not block a NEW
        // pending from arming (audit 2026-06-20): the next round's card could otherwise be suppressed
        // by the done-card still holding CARD_ID during its 4s fade. Treat it as absent so the fresh
        // decision card replaces it; a LIVE (not-done) card is left alone (stable branch below).
        const _doneCard = document.getElementById(CARD_ID);
        if (_doneCard && _doneCard.classList.contains("odec-done")) _doneCard.remove();
        if (host && !document.getElementById(CARD_ID)) {
          window.dispatchEvent(new CustomEvent("appkit:pending", { detail: { pending } }));
          stable = 0;
        } else if (document.getElementById(CARD_ID)) {
          if (++stable >= 3) break;   // survived ~600ms → boot settled, stop re-asserting
        }
        await new Promise((res) => setTimeout(res, 200));
      }
    } catch (_) { /* fail open */ }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", rearmFromStatus, { once: true });
  } else { rearmFromStatus(); }
  window.addEventListener("appkit:gamechanged", rearmFromStatus);
  // S4-1 (E2E audit) — the structural escape hatch: a pending player decision must be reachable
  // WITHOUT the chat agent ever dispatching it. `appkit:gamechanged` fires only on a LOCAL
  // game-mutating tool, so a pending that surfaces with no such event in this tab (the model
  // narrated past it without calling submitDecision, another device advanced, a missed tool call)
  // would otherwise sit unreachable until a reload. Poll the engine's own `pending` on a slow
  // cadence as a backstop. This deliberately does NOT call rearmFromStatus (which clears
  // _userDismissed) — it surfaces a pending ONLY when the player hasn't dismissed it and no card
  // is already up, so it never re-nags a waved-away card. Fail-open everywhere.
  setInterval(async () => {
    try {
      if (document.getElementById(CARD_ID)) return;    // a card is already showing
      if (!document.getElementById("chat-history")) return;
      const r = await fetch("/api/appkit/status", { credentials: "same-origin" });
      if (!r.ok) return;
      const st = await r.json();
      const pending = st && st.pending && st.pending.kind ? st.pending : null;
      // F-NEW-4: respect a dismissal PER SIGNATURE, not as a blanket flag — the old
      // unconditional `if (_userDismissed) return` let a dismissed low-stakes pending
      // suppress a genuinely DIFFERENT, later card (e.g. nominations) on this backstop.
      // Stay silent ONLY for the EXACT card the player waved away (the F2 signature guard);
      // a new pending surfaces normally without re-nagging the dismissed one. This still does
      // NOT clear _userDismissed (no re-nag of the waved-away card).
      if (_userDismissed && pending && _sig(pending) === _dismissedSig) return;
      if (pending && !document.getElementById(CARD_ID)) {
        window.dispatchEvent(new CustomEvent("appkit:pending", { detail: { pending } }));
      }
    } catch (_) { /* fail open — the conversation path always remains */ }
    // F14 (#1013): the eviction goodbye/vote card was surfacing a full WEEK late on the old 15s
    // cadence (the model narrates the eviction with no mutating tool, so the per-tool `appkit:pending`
    // seam never fires and only this poll catches it). Tighten to ~2.5s so a player-owned pending the
    // chat narrated past appears almost immediately. Still respects an explicit dismissal (the
    // per-signature guard above) and short-circuits when a card is already up — no extra nag, no churn.
  }, 2500);

  window.addEventListener("appkit:pending", (e) => {
    try {
      render(e.detail && e.detail.pending);
    } catch (_) { /* fail open — the conversation path always remains */ }
  });
})();
