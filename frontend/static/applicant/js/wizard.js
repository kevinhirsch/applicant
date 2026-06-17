// Applicant setup wizard. Posts the language-model and notification settings and
// reflects their status. Uses the shared ApplicantUI module for the redirect-aware
// fetch (the wizard never redirects to itself — it is where you complete setup).
import { ApplicantUI } from "./applicant-ui.js";

async function refreshStatus() {
  try {
    const s = await ApplicantUI.apiFetch("/api/setup/status");
    const el = document.getElementById("llm-status");
    if (el) {
      el.innerHTML = "Status: <strong>" + (s.gate_open ? "connected" : "not connected") + "</strong>";
    }
    const ch = document.getElementById("channels-status");
    if (ch) {
      ch.innerHTML =
        "Notifications: <strong>" +
        (s.channels_configured ? "configured" : "not configured") +
        "</strong>";
    }
  } catch (e) {
    /* offline; ignore */
  }
}

// Notification setup: post Discord/email and reflect the status.
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
