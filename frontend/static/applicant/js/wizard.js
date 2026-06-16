// Applicant OOBE wizard glue (FR-UI-5). Minimal, real: posts LLM settings to the
// gate endpoint and reflects gate state. STAGE B (Phase 0/1) deepens the wizard.
(function () {
  "use strict";

  async function refreshStatus() {
    try {
      const res = await fetch("/api/setup/status");
      const s = await res.json();
      const el = document.getElementById("llm-status");
      if (el) {
        el.innerHTML = "Gate: <strong>" + (s.gate_open ? "open" : "closed") + "</strong>";
      }
      const ch = document.getElementById("channels-status");
      if (ch) {
        ch.innerHTML =
          "Channels: <strong>" +
          (s.channels_configured ? "configured" : "not configured") +
          "</strong>";
      }
    } catch (e) {
      /* offline; ignore */
    }
  }

  // Channel setup (FR-NOTIF-1, FR-OOBE-2/3): post Discord/email and reflect the gate.
  function onChannelsSubmit(ev) {
    ev.preventDefault();
    const form = ev.target;
    const body = {
      discord_webhook_url: (form.discord_webhook_url || {}).value || "",
      apprise_urls: (form.apprise_urls || {}).value || "",
    };
    fetch("/api/setup/channels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(refreshStatus);
  }

  function onChannelsTest() {
    fetch("/api/setup/channels/test", { method: "POST" }).then(refreshStatus);
  }

  function onSubmit(ev) {
    ev.preventDefault();
    const body = {
      provider: (document.getElementById("llm-provider") || {}).value || "",
      base_url: (document.getElementById("llm-base-url") || {}).value || "",
      api_key: (document.getElementById("llm-api-key") || {}).value || "",
      model: (document.getElementById("llm-model") || {}).value || "",
    };
    fetch("/api/setup/llm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(refreshStatus);
  }

  document.addEventListener("DOMContentLoaded", function () {
    const form = document.getElementById("llm-form");
    if (form) form.addEventListener("submit", onSubmit);
    const channels = document.getElementById("channels-form");
    if (channels) channels.addEventListener("submit", onChannelsSubmit);
    const test = document.getElementById("channels-test");
    if (test) test.addEventListener("click", onChannelsTest);
    refreshStatus();
  });
})();
