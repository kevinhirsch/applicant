/*
 * Applicant — first-run setup, driving the real settings page.
 *
 * The model-connection flow (Test / Add an endpoint, then auto-list its models and
 * fill the model dropdowns) is ported from the shared chat app's settings:
 *   - _fetchModelEndpoints()  -> GET /api/model-endpoints
 *   - _fillEndpointSelect()   -> populate the endpoint <select>
 *   - _fillModelSelect()      -> populate the model <select>
 *   - the local + cloud "Test"/"Add" handlers POST multipart form data to
 *     /api/model-endpoints[/test], exactly like the chat app, and the server lists
 *     the models live from the address you entered.
 *
 * On first run this page opens itself to the setup sections and keeps the chat
 * surface locked until the model is connected. As each section is saved it is
 * marked done and its feature unlocks; fields pre-fill from already-saved settings.
 */
import { ApplicantUI } from "./applicant-ui.js";

const { el } = ApplicantUI;

/* ── helpers (ported from the chat app's settings model helpers) ──────────── */

async function fetchModelEndpoints() {
  const res = await fetch("/api/model-endpoints", { credentials: "same-origin" });
  if (!res.ok) return [];
  try {
    const data = await res.json();
    return Array.isArray(data) ? data : [];
  } catch (e) {
    return [];
  }
}

function modelLabel(id) {
  return String(id).split("/").pop();
}

function fillEndpointSelect(selectEl, endpoints, selected) {
  if (!selectEl) return;
  const previous = selected !== undefined ? selected : selectEl.value;
  while (selectEl.options.length) selectEl.remove(0);
  (endpoints || []).forEach((ep) => {
    if (!ep.is_enabled) return;
    const opt = document.createElement("option");
    opt.value = ep.id;
    opt.textContent = ep.name + (ep.online ? "" : " (offline)");
    selectEl.appendChild(opt);
  });
  if (previous && Array.from(selectEl.options).some((o) => o.value === previous)) {
    selectEl.value = previous;
  }
}

function fillModelSelect(selectEl, models, selected) {
  if (!selectEl) return;
  const previous = selected !== undefined ? selected : selectEl.value;
  while (selectEl.options.length) selectEl.remove(0);
  (models || []).slice().sort().forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = modelLabel(m);
    selectEl.appendChild(opt);
  });
  if (previous && Array.from(selectEl.options).some((o) => o.value === previous)) {
    selectEl.value = previous;
  }
}

function esc(s) {
  return String(s || "").replace(/[<>&"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", '"': "&quot;" }[c]));
}

function normalizeBaseUrl(raw) {
  let u = (raw || "").trim();
  if (!u) return u;
  if (!/^https?:\/\//i.test(u)) u = "http://" + u;
  return u.replace(/\/+$/, "");
}

let _endpoints = [];

/* ── render the "Added Models" list (ported from loadEndpoints) ───────────── */

async function loadEndpoints() {
  _endpoints = await fetchModelEndpoints();
  const list = document.getElementById("adm-epList");
  if (list) {
    if (!_endpoints.length) {
      list.innerHTML = '<div class="admin-empty">None yet — connect one above.</div>';
    } else {
      list.innerHTML = _endpoints
        .map((ep) => {
          const count = (ep.models || []).length;
          const badge = ep.online
            ? `<span class="admin-badge">${count} model${count !== 1 ? "s" : ""}</span>`
            : '<span class="admin-badge admin-badge-off">offline</span>';
          return `<div class="admin-user-row" data-ep-id="${esc(ep.id)}">
            <div class="admin-user-info" style="flex:1;flex-wrap:wrap;gap:0.3rem;">
              <span class="admin-user-name">${esc(ep.name)}</span>
              <span class="admin-badge">${ep.category === "local" ? "Local" : "Cloud"}</span>
              ${badge}
              ${ep.is_enabled ? "" : '<span class="admin-badge admin-badge-off">disabled</span>'}
            </div>
            <div class="admin-ep-actions">
              <button class="admin-btn-sm" data-ep-toggle="${esc(ep.id)}" title="Turn this endpoint on or off">${ep.is_enabled ? "Disable" : "Enable"}</button>
              <button class="admin-btn-delete" data-ep-del="${esc(ep.id)}" title="Remove this endpoint">Delete</button>
            </div>
          </div>`;
        })
        .join("");
      list.querySelectorAll("[data-ep-toggle]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await fetch(`/api/model-endpoints/${btn.dataset.epToggle}`, { method: "PATCH", credentials: "same-origin" });
          await refreshAll();
        });
      });
      list.querySelectorAll("[data-ep-del]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          await fetch(`/api/model-endpoints/${btn.dataset.epDel}`, { method: "DELETE", credentials: "same-origin" });
          await refreshAll();
        });
      });
    }
  }
  // Keep the AI-defaults dropdowns in sync with the connected endpoints.
  fillAiDefaults();
}

/* ── AI Defaults — endpoint + model dropdowns (ported fill flow) ──────────── */

function fillAiDefaults(selectedEpId, selectedModel) {
  const epSel = document.getElementById("set-defaultEpSelect");
  const modelSel = document.getElementById("set-defaultModelSelect");
  if (!epSel || !modelSel) return;
  fillEndpointSelect(epSel, _endpoints, selectedEpId);
  const ep = _endpoints.find((e) => e.id === epSel.value);
  fillModelSelect(modelSel, ep ? ep.models : [], selectedModel);
}

function initAiDefaults() {
  const epSel = document.getElementById("set-defaultEpSelect");
  const modelSel = document.getElementById("set-defaultModelSelect");
  const msg = document.getElementById("set-defaultChatMsg");
  if (!epSel || !modelSel) return;
  epSel.addEventListener("change", () => {
    const ep = _endpoints.find((e) => e.id === epSel.value);
    fillModelSelect(modelSel, ep ? ep.models : []);
    saveDefault();
  });
  modelSel.addEventListener("change", saveDefault);

  async function saveDefault() {
    if (!epSel.value || !modelSel.value) return;
    if (msg) { msg.textContent = "Saving…"; msg.className = "adm-ep-inline-msg"; }
    try {
      await ApplicantUI.apiFetch("/api/setup/llm/from-endpoint", {
        method: "POST",
        body: JSON.stringify({ endpoint_id: epSel.value, model: modelSel.value }),
      });
      if (msg) { msg.textContent = "Saved"; msg.className = "admin-success"; }
      await refreshStatus();
    } catch (e) {
      if (msg) { msg.textContent = "Could not save — check the endpoint."; msg.className = "admin-error"; }
    }
  }
}

/* ── Add Models forms — Test/Add handlers (ported from the chat app) ──────── */

function renderTestResult(msg, result) {
  if (result && result.online) {
    const models = result.models || [];
    const preview = models.slice(0, 3).map((m) => esc(modelLabel(m))).join(", ");
    msg.innerHTML = `Online — found ${models.length} model${models.length !== 1 ? "s" : ""}${preview ? `: ${preview}${models.length > 3 ? ", …" : ""}` : ""}`;
    msg.className = "admin-success";
  } else {
    msg.textContent = result && result.ping_error ? `Offline — ${result.ping_error}` : "Offline — could not reach that address";
    msg.className = "admin-error";
  }
}

function initLocalForm() {
  const urlInput = document.getElementById("adm-epLocalUrl");
  const keyInput = document.getElementById("adm-epLocalApiKey");
  const typeSel = document.getElementById("adm-epLocalType");
  const msg = document.getElementById("adm-epLocalMsg");
  const testBtn = document.getElementById("adm-epLocalTestBtn");
  const addBtn = document.getElementById("adm-epLocalAddBtn");
  const ollamaBtn = document.getElementById("adm-epOllamaBtn");

  if (ollamaBtn) {
    ollamaBtn.addEventListener("click", () => {
      urlInput.value = "http://localhost:11434/v1";
      urlInput.focus();
      msg.textContent = "Ollama address filled in — Test or Add.";
      msg.className = "";
    });
  }

  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      msg.textContent = ""; msg.className = "";
      const raw = (urlInput.value || "").trim();
      if (!raw) { msg.textContent = "Enter a base URL to test"; msg.className = "admin-error"; return; }
      const url = normalizeBaseUrl(raw);
      testBtn.disabled = true; testBtn.textContent = "Testing…";
      try {
        const fd = new FormData();
        fd.append("base_url", url);
        if (keyInput.value.trim()) fd.append("api_key", keyInput.value.trim());
        const res = await fetch("/api/model-endpoints/test", { method: "POST", body: fd, credentials: "same-origin" });
        renderTestResult(msg, await res.json());
      } catch (e) {
        msg.textContent = "Test failed: " + (e && e.message ? e.message : "request failed");
        msg.className = "admin-error";
      }
      testBtn.disabled = false; testBtn.textContent = "Test";
    });
  }

  if (addBtn) {
    addBtn.addEventListener("click", async () => {
      msg.textContent = ""; msg.className = "";
      const raw = (urlInput.value || "").trim();
      if (!raw) { msg.textContent = "Enter a base URL (e.g. http://localhost:11434/v1)"; msg.className = "admin-error"; return; }
      const url = normalizeBaseUrl(raw);
      addBtn.disabled = true; addBtn.textContent = "Adding…";
      try {
        const fd = new FormData();
        fd.append("base_url", url);
        fd.append("model_type", typeSel ? typeSel.value : "llm");
        if (keyInput.value.trim()) fd.append("api_key", keyInput.value.trim());
        const res = await fetch("/api/model-endpoints", { method: "POST", body: fd, credentials: "same-origin" });
        const d = await res.json();
        if (res.ok) {
          urlInput.value = ""; keyInput.value = "";
          const count = (d.models || []).length;
          msg.textContent = d.status === "empty"
            ? "Added — reachable, but no models found yet"
            : d.online
            ? `Added — found ${count} model${count !== 1 ? "s" : ""}`
            : "Added (offline — will retry on next load)";
          msg.className = d.online ? "admin-success" : "admin-error";
          await refreshAll();
        } else { msg.textContent = d.detail || "Failed"; msg.className = "admin-error"; }
      } catch (e) { msg.textContent = "Request failed"; msg.className = "admin-error"; }
      addBtn.disabled = false; addBtn.textContent = "Add";
    });
  }
}

function initApiForm() {
  const provider = document.getElementById("adm-epProvider");
  const urlInput = document.getElementById("adm-epUrl");
  const keyInput = document.getElementById("adm-epApiKey");
  const typeSel = document.getElementById("adm-epType");
  const msg = document.getElementById("adm-epApiMsg");
  const testBtn = document.getElementById("adm-epApiTestBtn");
  const addBtn = document.getElementById("adm-epAddBtn");

  if (provider) {
    provider.addEventListener("change", () => {
      if (provider.value) { urlInput.value = provider.value; urlInput.focus(); }
    });
  }

  const readUrl = () => normalizeBaseUrl((urlInput.value || provider.value || "").trim());

  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      msg.textContent = ""; msg.className = "";
      const url = readUrl();
      const apiKey = keyInput.value.trim();
      if (!url) { msg.textContent = "Pick a provider or enter a base URL"; msg.className = "admin-error"; return; }
      if (!apiKey) { msg.textContent = "API key is required for cloud providers"; msg.className = "admin-error"; return; }
      testBtn.disabled = true; testBtn.textContent = "Testing…";
      try {
        const fd = new FormData();
        fd.append("base_url", url);
        fd.append("api_key", apiKey);
        const res = await fetch("/api/model-endpoints/test", { method: "POST", body: fd, credentials: "same-origin" });
        renderTestResult(msg, await res.json());
      } catch (e) {
        msg.textContent = "Test failed: " + (e && e.message ? e.message : "request failed");
        msg.className = "admin-error";
      }
      testBtn.disabled = false; testBtn.textContent = "Test";
    });
  }

  if (addBtn) {
    addBtn.addEventListener("click", async () => {
      msg.textContent = ""; msg.className = "";
      const url = readUrl();
      const apiKey = keyInput.value.trim();
      if (!url) { msg.textContent = "Pick a provider or enter a base URL"; msg.className = "admin-error"; return; }
      if (!apiKey) { msg.textContent = "API key is required for cloud providers"; msg.className = "admin-error"; return; }
      addBtn.disabled = true; addBtn.textContent = "Adding…";
      try {
        const fd = new FormData();
        fd.append("base_url", url);
        fd.append("api_key", apiKey);
        fd.append("model_type", typeSel ? typeSel.value : "llm");
        if (provider.value && provider.selectedOptions[0]) fd.append("name", provider.selectedOptions[0].textContent.trim());
        const res = await fetch("/api/model-endpoints", { method: "POST", body: fd, credentials: "same-origin" });
        const d = await res.json();
        if (res.ok) {
          urlInput.value = ""; keyInput.value = ""; provider.value = "";
          const count = (d.models || []).length;
          msg.textContent = d.status === "empty"
            ? "Added — reachable, but no models found"
            : d.online
            ? `Added — found ${count} model${count !== 1 ? "s" : ""}`
            : "Added (offline — will retry on next load)";
          msg.className = d.online ? "admin-success" : "admin-error";
          await refreshAll();
        } else { msg.textContent = d.detail || "Failed"; msg.className = "admin-error"; }
      } catch (e) { msg.textContent = "Request failed"; msg.className = "admin-error"; }
      addBtn.disabled = false; addBtn.textContent = "Add";
    });
  }
}

/* ── Notifications, fonts, intake ─────────────────────────────────────────── */

function initNotifications() {
  const discord = document.getElementById("notif-discord");
  const email = document.getElementById("notif-email");
  const msg = document.getElementById("notif-msg");
  const saveBtn = document.getElementById("notif-save");
  const testBtn = document.getElementById("notif-test");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const body = { discord_webhook_url: discord.value.trim(), apprise_urls: email.value.trim() };
      if (!body.discord_webhook_url && !body.apprise_urls) {
        msg.textContent = "Add a Discord webhook and/or an email address."; msg.className = "admin-error"; return;
      }
      msg.textContent = "Saving…"; msg.className = "";
      try {
        await ApplicantUI.apiFetch("/api/setup/channels", { method: "POST", body: JSON.stringify(body) });
        msg.textContent = "Saved"; msg.className = "admin-success";
        await refreshStatus();
      } catch (e) { msg.textContent = "Could not save notifications."; msg.className = "admin-error"; }
    });
  }
  if (testBtn) {
    testBtn.addEventListener("click", async () => {
      msg.textContent = "Sending test…"; msg.className = "";
      try {
        await ApplicantUI.apiFetch("/api/setup/channels/test", { method: "POST" });
        msg.textContent = "Test sent"; msg.className = "admin-success";
      } catch (e) { msg.textContent = "Test could not be sent."; msg.className = "admin-error"; }
    });
  }
}

function initFonts() {
  const toggle = document.getElementById("fonts-toggle");
  const msg = document.getElementById("fonts-msg");
  if (!toggle) return;
  toggle.addEventListener("change", async () => {
    if (!toggle.checked) return;
    msg.textContent = "Marking fonts ready…"; msg.className = "";
    try {
      await ApplicantUI.apiFetch("/api/setup/advance/fonts", { method: "POST" });
      msg.textContent = "Fonts ready"; msg.className = "admin-success";
      await refreshStatus();
    } catch (e) { toggle.checked = false; msg.textContent = "Could not update."; msg.className = "admin-error"; }
  });
}

function initIntake() {
  const toggle = document.getElementById("intake-toggle");
  const msg = document.getElementById("intake-msg");
  if (!toggle) return;
  toggle.addEventListener("change", async () => {
    if (!toggle.checked) return;
    msg.textContent = "Marking intake ready…"; msg.className = "";
    try {
      await ApplicantUI.apiFetch("/api/setup/advance/onboarding", { method: "POST" });
      msg.textContent = "Intake ready"; msg.className = "admin-success";
      await refreshStatus();
    } catch (e) { toggle.checked = false; msg.textContent = "Could not update."; msg.className = "admin-error"; }
  });
}

/* ── tabs (ported settings tab switching) ─────────────────────────────────── */

function initTabs() {
  const modal = document.getElementById("settings-modal");
  modal.querySelectorAll("[data-settings-tab]").forEach((btn) => {
    btn.addEventListener("click", () => openTab(btn.dataset.settingsTab));
  });
}

function openTab(tab) {
  const modal = document.getElementById("settings-modal");
  modal.querySelectorAll("[data-settings-tab]").forEach((b) =>
    b.classList.toggle("active", b.dataset.settingsTab === tab)
  );
  modal.querySelectorAll("[data-settings-panel]").forEach((p) =>
    p.classList.toggle("hidden", p.dataset.settingsPanel !== tab)
  );
  if (tab === "ai") fillAiDefaults();
}

/* ── gate + status: open settings on first run, unlock chat when done ──────── */

let _gateOpen = false;

function setBadge(name, done, optionalDoneLabel) {
  const badge = document.querySelector(`[data-setup-badge="${name}"]`);
  if (!badge) return;
  if (done) {
    badge.textContent = "done";
    badge.className = "admin-badge admin-badge-on";
  } else {
    badge.textContent = optionalDoneLabel || "to do";
    badge.className = "admin-badge admin-badge-off";
  }
}

async function refreshStatus() {
  let s;
  try {
    s = await ApplicantUI.apiFetch("/api/setup/status");
  } catch (e) {
    return;
  }
  _gateOpen = !!s.gate_open;
  setBadge("llm", s.gate_open);
  setBadge("channels", s.channels_configured, "optional");
  setBadge("fonts", s.fonts_ready, "optional");
  setBadge("onboarding", s.onboarding_complete, "optional");

  const fontsToggle = document.getElementById("fonts-toggle");
  if (fontsToggle) fontsToggle.checked = !!s.fonts_ready;
  const intakeToggle = document.getElementById("intake-toggle");
  if (intakeToggle) intakeToggle.checked = !!s.onboarding_complete;

  applyGate();
}

function applyGate() {
  const chat = document.getElementById("chat-surface");
  const banner = document.getElementById("setup-gate-banner");
  const modal = document.getElementById("settings-modal");
  if (_gateOpen) {
    // Setup's required step is done: chat is available, settings is a normal menu.
    if (chat) chat.style.display = "";
    if (banner) banner.style.display = "none";
  } else {
    // Required setup is incomplete: keep chat locked behind the open settings page.
    if (chat) chat.style.display = "none";
    if (banner) banner.style.display = "none"; // hidden while the modal is open
    if (modal && modal.classList.contains("hidden")) {
      banner.style.display = "";
    }
  }
}

function openSettings(tab) {
  const modal = document.getElementById("settings-modal");
  modal.classList.remove("hidden");
  openTab(tab || "services");
  applyGate();
}

function closeSettings() {
  const modal = document.getElementById("settings-modal");
  if (!_gateOpen) {
    // Required setup isn't done — don't let the user fall through to an empty chat.
    // Keep them in setup; show the gate banner with a clear way back in.
    modal.classList.add("hidden");
    applyGate();
    return;
  }
  modal.classList.add("hidden");
  applyGate();
}

async function refreshAll() {
  await loadEndpoints();
  await refreshStatus();
}

/* ── boot ─────────────────────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", async function () {
  ApplicantUI.mountShell({ active: "wizard" });
  initTabs();
  initLocalForm();
  initApiForm();
  initAiDefaults();
  initNotifications();
  initFonts();
  initIntake();

  document.getElementById("settings-close").addEventListener("click", closeSettings);
  const openBtn = document.getElementById("open-settings-btn");
  if (openBtn) openBtn.addEventListener("click", () => openSettings("services"));
  const reopenBtn = document.getElementById("reopen-settings-btn");
  if (reopenBtn) reopenBtn.addEventListener("click", () => openSettings("services"));

  await loadEndpoints();
  await refreshStatus();

  // First run (setup incomplete): open the settings page to the setup sections.
  if (!_gateOpen) {
    openSettings("services");
  }
});
