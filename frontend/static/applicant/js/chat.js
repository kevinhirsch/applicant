/*
 * Applicant — assistant chat client.
 *
 * Posts messages to /api/chat, shows the reply and anything that's missing, and
 * surfaces suggested changes. Important suggestions show a Confirm button that
 * saves via /api/chat/confirm; routine suggestions are applied automatically and
 * shown as applied. Handles network errors gracefully. Shares the redirect-aware
 * fetch and DOM builder from ApplicantUI.
 */
import { ApplicantUI, apiFetch, el } from "/static/applicant/js/applicant-ui.js";

  const params = new URLSearchParams(location.search);
  const campaignId = document.body.getAttribute("data-campaign-id") || params.get("campaign_id") || "";

  const log = document.getElementById("chat-log");
  const gapsBox = document.getElementById("chat-gaps");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");

  // Chat always POSTs a JSON body; wrap the shared helper to keep the call sites.
  function api(path, body) {
    return apiFetch(path, { method: "POST", body: JSON.stringify(body) });
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

  ApplicantUI.mountShell({ active: "chat" });
