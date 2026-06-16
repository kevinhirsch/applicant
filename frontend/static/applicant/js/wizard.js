// Applicant OOBE wizard glue (FR-UI-5). Minimal, real: posts LLM settings to the
// gate endpoint and reflects gate state. Uses the shared ApplicantUI module for
// the redirect-aware fetch (the wizard is exempt from the gate redirect — it is
// how the user opens the gate). STAGE B (Phase 0/1) deepens the wizard.
import { ApplicantUI } from "./applicant-ui.js";

async function refreshStatus() {
  try {
    const s = await ApplicantUI.apiFetch("/api/setup/status");
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
  ApplicantUI.apiFetch("/api/setup/channels", {
    method: "POST",
    body: JSON.stringify(body),
  }).then(refreshStatus, refreshStatus);
}

function onChannelsTest() {
  ApplicantUI.apiFetch("/api/setup/channels/test", { method: "POST" }).then(
    refreshStatus,
    refreshStatus
  );
}

function onSubmit(ev) {
  ev.preventDefault();
  const body = {
    provider: (document.getElementById("llm-provider") || {}).value || "",
    base_url: (document.getElementById("llm-base-url") || {}).value || "",
    api_key: (document.getElementById("llm-api-key") || {}).value || "",
    model: (document.getElementById("llm-model") || {}).value || "",
  };
  ApplicantUI.apiFetch("/api/setup/llm", {
    method: "POST",
    body: JSON.stringify(body),
  }).then(refreshStatus, refreshStatus);
}

document.addEventListener("DOMContentLoaded", function () {
  ApplicantUI.mountShell({ active: "wizard" });
  const form = document.getElementById("llm-form");
  if (form) form.addEventListener("submit", onSubmit);
  const channels = document.getElementById("channels-form");
  if (channels) channels.addEventListener("submit", onChannelsSubmit);
  const test = document.getElementById("channels-test");
  if (test) test.addEventListener("click", onChannelsTest);
  refreshStatus();
});
