/*
 * Applicant — assistant chatbot client (FR-CHAT-1, FR-FB-2/3).
 *
 * Posts conversational turns to /api/chat, renders the reply + identified gaps,
 * and surfaces proposed changes. Integral/sensitive proposals (requires_confirmation)
 * show a Confirm button that commits via /api/chat/confirm (FR-FB-3). Non-integral
 * proposals are auto-applied server-side and shown as applied. Degrades gracefully
 * on network error (FR-UI-2).
 */
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const campaignId = document.body.getAttribute("data-campaign-id") || params.get("campaign_id") || "";

  const log = document.getElementById("chat-log");
  const gapsBox = document.getElementById("chat-gaps");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");

  async function api(path, body) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.assign(node, attrs || {});
    (children || []).forEach((c) => node.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return node;
  }

  function addTurn(cls, text) {
    const node = el("div", { className: "chat-turn " + cls }, [text]);
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  function renderGaps(gaps) {
    gapsBox.innerHTML = "";
    if (gaps && gaps.length) {
      gapsBox.appendChild(el("span", {}, ["Missing details: " + gaps.join(", ")]));
    }
  }

  function renderProposals(proposals) {
    (proposals || []).forEach((p) => {
      if (p.applied) {
        addTurn("chat-bot chat-proposal", `Applied: ${p.name} = ${p.value}`);
        return;
      }
      const row = addTurn("chat-bot chat-proposal", `Proposed (needs confirmation): ${p.name} = ${p.value} `);
      const btn = el("button", { className: "admin-btn admin-btn-sm", type: "button" }, ["Confirm"]);
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api("/api/chat/confirm", { campaign_id: campaignId, name: p.name, value: p.value });
          row.textContent = `Confirmed: ${p.name} = ${p.value}`;
        } catch (e) {
          btn.disabled = false;
          row.appendChild(el("span", { className: "applicant-note" }, [" (confirm failed)"]));
        }
      });
      row.appendChild(btn);
    });
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const msg = input.value.trim();
    if (!msg) return;
    addTurn("chat-user", msg);
    input.value = "";
    try {
      const r = await api("/api/chat", { campaign_id: campaignId, message: msg });
      addTurn("chat-bot", r.message);
      renderGaps(r.gaps);
      renderProposals(r.proposed_changes);
    } catch (e) {
      addTurn("chat-bot applicant-note", "Assistant unavailable right now.");
    }
  });
})();
