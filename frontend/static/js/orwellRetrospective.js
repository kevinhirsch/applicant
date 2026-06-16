// Orwell season retrospective (feature 0048 / C17) — the post-season payoff surface.
//
// While a season is live this module shows NOTHING (the Wall is absolute; the /retrospective
// route 404s by the engine's terminal-state gate). Once a winner is crowned it offers:
//   • the season RECAP — arc highlights straight from the event record (never chat memory), and
//   • "Open the Producer's Vault" — the unsealed hidden story: the off-screen scheming, the
//     private confessionals, and the twist that never fired.
//
// Fail-open, render-only (route payloads verbatim), game-build gated, dismissible. The panel
// AUGMENTS the reunion chat (the model hosts it via seasonRecap/seasonRetrospective levers);
// nothing here progresses the game.
(function () {
  "use strict";

  const POLL_MS = 30000;
  const ID = "orwell-retro";
  const ready = (fn) =>
    document.readyState === "loading"
      ? document.addEventListener("DOMContentLoaded", fn, { once: true })
      : fn();

  let timer = null;
  let _failures = 0;
  function _pollDelay() { return Math.min(POLL_MS * Math.pow(2, _failures), 180000); }
  let unsealed = null; // cached after the player opens the Vault

  async function getJSON(url) {
    const r = await fetch(url, { credentials: "same-origin" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  }

  function el(tag, css, text) {
    const e = document.createElement(tag);
    if (css) e.style.cssText = css;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function ensurePanel() {
    let panel = document.getElementById(ID);
    if (panel) return panel;
    panel = el("div", [
      "position:fixed", "width:min(380px, calc(100vw - 32px))", /* E91/S11: bottom-right slot */
      "max-height:min(70vh, 560px)", "overflow:auto", "z-index:45",
      "background:var(--surface-2, rgba(22,22,26,0.96))", "color:var(--text-1, #ddd)",
      "border:1px solid var(--border-1, rgba(255,255,255,0.14))", "border-radius:12px",
      "padding:12px 14px", "font-size:13px", "line-height:1.5",
      "box-shadow:0 8px 24px rgba(0,0,0,0.45)", "display:none", "backdrop-filter:blur(8px)",
    ].join(";"));
    panel.id = ID;
    panel.setAttribute("role", "complementary");
    panel.setAttribute("aria-label", "Season retrospective");
    document.body.appendChild(panel);
  if (window.OrwellSlots) window.OrwellSlots.register(panel, "bottom-right", { key: "retro" });
    return panel;
  }

  function render(recap) {
    const panel = ensurePanel();
    if (!recap || !recap.finished) { panel.style.display = "none"; return; }
    if (sessionStorage.getItem("orwell-retro-dismissed") === "1") { panel.style.display = "none"; return; }
    panel.replaceChildren();

    const head = el("div", "display:flex;justify-content:space-between;align-items:center;margin-bottom:6px");
    head.appendChild(el("strong", "", "📼 The season, watched back"));
    const close = el("button", "", "×");
    close.className = "ow-dismiss";
    close.setAttribute("aria-label", "Dismiss the retrospective panel");
    close.addEventListener("click", () => {
      try { sessionStorage.setItem("orwell-retro-dismissed", "1"); } catch (_) {}
      panel.style.display = "none";
    });
    head.appendChild(close);
    panel.appendChild(head);

    if (recap.winner) panel.appendChild(el("div", "margin-bottom:6px;opacity:0.9", "👑 " + recap.winner.name + " won the season (week " + recap.weeksPlayed + ")."));

    const list = el("ul", "margin:6px 0;padding-left:18px;opacity:0.85");
    for (const h of (recap.highlights || []).slice(-12)) list.appendChild(el("li", "", h));
    panel.appendChild(list);

    const vaultWrap = el("div", "margin-top:8px");
    if (unsealed) {
      vaultWrap.appendChild(el("strong", "", "🔓 The Producer's Vault"));
      if (unsealed.twists && unsealed.twists.length) {
        const t = el("div", "margin:4px 0;opacity:0.9");
        t.textContent = unsealed.twists.map((x) =>
          x.firedWeek ? `a ${x.kind} fired in week ${x.firedWeek}` : `a ${x.kind} was sealed but never fired`,
        ).join(" · ");
        vaultWrap.appendChild(t);
      }
      const story = el("ul", "margin:6px 0;padding-left:18px;opacity:0.8;font-size:12.5px");
      for (const h of (unsealed.hiddenStory || []).slice(-40)) {
        story.appendChild(el("li", "", "[" + h.type + "] " + h.content));
      }
      vaultWrap.appendChild(story);
    } else {
      const open = el("button", [
        "margin-top:4px", "padding:6px 10px", "border-radius:8px", "cursor:pointer",
        "background:var(--accent, #6d4aff)", "color:#fff", "border:none", "font-size:12.5px",
      ].join(";"), "🔐 Open the Producer's Vault");
      open.addEventListener("click", async () => {
        try {
          const data = await getJSON("/api/orwell/retrospective");
          unsealed = data.retrospective || null;
          render(recap);
        } catch (_) {
          if (window.OrwellReport) window.OrwellReport.fail("retrospective", "vault-open", _); // G11: fail open, never silent
          open.textContent = "The Vault would not open — try again";
        }
      });
      vaultWrap.appendChild(open);
      vaultWrap.appendChild(el("div", "opacity:0.6;font-size:11.5px;margin-top:3px",
        "The hidden story they never showed you — scheming, confessionals, the twist that never fired."));
    }
    panel.appendChild(vaultWrap);
    panel.style.display = "block";
  }

  async function tick() {
    try {
      if (document.hidden) return;
      const state = await getJSON("/api/orwell/state");
      if (!state || !state.started) { render(null); unsealed = null; return; }
      const data = await getJSON("/api/orwell/recap");
      render(data ? data.recap : null);
      _failures = 0;
    } catch (_) {
      _failures += 1;
      if (window.OrwellReport) window.OrwellReport.fail("retrospective", "recap-poll", _); // G11: fail open, never silent
      render(null); // fail OPEN: no panel on error
    } finally {
      timer = setTimeout(tick, _pollDelay());
    }
  }

  ready(() => {
    if (document.body && document.body.dataset.gameBuild !== "1") return;
    tick();
    window.addEventListener("beforeunload", () => timer && clearTimeout(timer));
  });
})();
