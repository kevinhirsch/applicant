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
  try {
    const sb = await ApplicantUI.apiFetch("/api/setup/sandbox-connection");
    const el = document.getElementById("sandbox-status");
    if (el) {
      el.innerHTML =
        "Windows sandbox: <strong>" +
        (sb.configured ? "configured" : "not configured") +
        "</strong>";
    }
  } catch (e) {
    /* offline; ignore */
  }
}

// Native Proxmox Windows VM connection (FR-OOBE, FR-SANDBOX-1). Secrets (token
// secret + RDP password) are sealed in the credential vault server-side; this form
// only POSTs them, never reads them back.
function onSandboxSubmit(ev) {
  ev.preventDefault();
  const form = ev.target;
  const val = (n) => (form[n] || {}).value || "";
  const body = {
    proxmox_api_url: val("proxmox_api_url"),
    proxmox_node: val("proxmox_node"),
    proxmox_token_id: val("proxmox_token_id"),
    proxmox_token_secret: val("proxmox_token_secret"),
    template_vmid: parseInt(val("template_vmid") || "0", 10),
    clone_mode: val("clone_mode") || "snapshot-revert",
    cdp_host: val("cdp_host"),
    cdp_port: parseInt(val("cdp_port") || "9222", 10),
    rdp_username: val("rdp_username"),
    rdp_password: val("rdp_password"),
    takeover_method: val("takeover_method") || "rdp",
    takeover_url_template: val("takeover_url_template"),
  };
  ApplicantUI.apiFetch("/api/setup/sandbox-connection", {
    method: "POST",
    body: JSON.stringify(body),
  }).then(refreshStatus, refreshStatus);
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
  const sandbox = document.getElementById("sandbox-form");
  if (sandbox) sandbox.addEventListener("submit", onSandboxSubmit);
  refreshStatus();
});
