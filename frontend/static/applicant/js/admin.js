/*
 * Applicant — debug/observability + tool-toggle + history/variant-library surface.
 * FR-UI-4 (tool toggles), FR-OBS-2 / FR-LOG-3 (logs, screenshots, history,
 * workflow state, variant library), FR-OOBE-4 (in-UI Update button). Phase 4.
 *
 * Network failures degrade gracefully — an error note is shown, never dead UI
 * presented as live (FR-UI-2). Shares the redirect-aware fetch + DOM builder from
 * ApplicantUI (a 409 from the gate routes to the wizard).
 */
import { ApplicantUI, apiFetch, el } from "./applicant-ui.js";

  const params = new URLSearchParams(location.search);
  const campaignId = document.body.getAttribute("data-campaign-id") || params.get("campaign_id") || "";
  const applicationId = document.body.getAttribute("data-application-id") || params.get("application_id") || "";

  const api = apiFetch;

  function note(container, text) {
    container.innerHTML = "";
    container.appendChild(el("p", { className: "admin-empty applicant-note" }, [text]));
  }

  // --- tool toggles (FR-UI-4) ---------------------------------------------
  async function loadTools() {
    const list = document.getElementById("tools-list");
    try {
      const payload = await api("/api/admin/tools");
      list.innerHTML = "";
      (payload.tools || []).forEach((t) => {
        const checkbox = el("input", { type: "checkbox", checked: !!t.enabled });
        checkbox.addEventListener("change", async () => {
          try {
            await api(`/api/admin/tools/${encodeURIComponent(t.key)}?enabled=${checkbox.checked}`, { method: "POST" });
          } catch (e) {
            checkbox.checked = !checkbox.checked; // revert on failure
          }
        });
        list.appendChild(el("div", { className: "applicant-toggle-row" }, [el("span", {}, [t.label]), checkbox]));
      });
    } catch (e) {
      note(list, "Tool registry unavailable.");
    }
  }

  // --- per-application history (FR-OBS-2 / FR-LOG-3) -----------------------
  async function loadHistory() {
    const tbody = document.getElementById("history-rows");
    try {
      const payload = await api(`/api/admin/history/${encodeURIComponent(campaignId)}`);
      tbody.innerHTML = "";
      const apps = payload.applications || [];
      if (!apps.length) {
        tbody.appendChild(el("tr", {}, [el("td", { colSpan: 6, className: "admin-empty" }, ["No applications yet."])]));
        return;
      }
      apps.forEach((a) => {
        const outcomes = (a.outcomes || []).map((o) => o.type).join(", ") || "—";
        tbody.appendChild(el("tr", {}, [
          el("td", {}, [a.role_name || a.job_title || "—"]),
          el("td", {}, [a.status]),
          el("td", {}, [a.work_mode || "—"]),
          el("td", {}, [String(a.screenshot_count || 0)]),
          el("td", {}, [outcomes]),
          el("td", {}, [el("a", { href: `/api/admin/workflow/${encodeURIComponent(a.application_id)}` }, ["state"])]),
        ]));
      });
    } catch (e) {
      tbody.innerHTML = "";
      tbody.appendChild(el("tr", {}, [el("td", { colSpan: 6, className: "admin-empty applicant-note" }, ["History unavailable."])]));
    }
  }

  // --- variant library (FR-UI-6 / FR-RESUME-6) ----------------------------
  async function loadVariants() {
    const tbody = document.getElementById("variants-rows");
    if (!tbody) return;
    try {
      const payload = await api(`/api/admin/variants/${encodeURIComponent(campaignId)}`);
      tbody.innerHTML = "";
      const variants = payload.variants || [];
      if (!variants.length) {
        tbody.appendChild(el("tr", {}, [el("td", { colSpan: 5, className: "admin-empty" }, ["No variants yet."])]));
        return;
      }
      variants.forEach((v) => {
        tbody.appendChild(el("tr", {}, [
          el("td", {}, [(v.variant_id || "").slice(0, 8)]),
          el("td", {}, [v.parent_id ? v.parent_id.slice(0, 8) : "root"]),
          el("td", {}, [String(v.lineage_depth || 0)]),
          el("td", {}, [v.approved ? "yes" : "no"]),
          el("td", {}, [v.targeted_jd_signature || "—"]),
        ]));
      });
    } catch (e) {
      tbody.innerHTML = "";
      tbody.appendChild(el("tr", {}, [el("td", { colSpan: 5, className: "admin-empty applicant-note" }, ["Variant library unavailable."])]));
    }
  }

  // --- structured logs tail (FR-LOG-3) ------------------------------------
  async function loadLogs() {
    const list = document.getElementById("logs-list");
    if (!list) return;
    try {
      const payload = await api("/api/admin/logs?limit=50");
      list.innerHTML = "";
      const entries = payload.entries || [];
      if (!entries.length) {
        note(list, "No log entries yet.");
        return;
      }
      entries.forEach((e) => {
        const line = [e.timestamp, e.level, e.event].filter(Boolean).join(" ");
        list.appendChild(el("div", {}, [line || JSON.stringify(e)]));
      });
    } catch (e) {
      note(list, "Logs unavailable.");
    }
  }

  // --- per-page screenshots (FR-OBS-2) ------------------------------------
  async function loadScreenshots() {
    const list = document.getElementById("screenshots-list");
    if (!list || !applicationId) return;
    try {
      const payload = await api(`/api/admin/screenshots/${encodeURIComponent(applicationId)}`);
      list.innerHTML = "";
      const shots = payload.screenshots || [];
      if (!shots.length) {
        note(list, "No screenshots captured for this run.");
        return;
      }
      shots.forEach((s) => {
        list.appendChild(el("div", { className: "applicant-toggle-row" }, [
          el("span", {}, [s.page_ref || s.id]),
          el("a", { href: s.page_url || "#" }, ["view"]),
        ]));
      });
    } catch (e) {
      note(list, "Screenshots unavailable.");
    }
  }

  // --- stealth honesty caveat + egress posture (FR-STEALTH-4/5) -----------
  async function loadStealth() {
    const caveat = document.getElementById("stealth-caveat");
    const egress = document.getElementById("stealth-egress");
    if (!caveat) return;
    try {
      const s = await api("/api/admin/stealth");
      caveat.textContent = s.caveat;
      const e = s.egress || {};
      egress.textContent =
        `Egress: ${e.mode}` +
        (e.proxy_configured ? " (residential proxy threaded into launch)" : " (direct residential)") +
        ` — ${s.egress_caveat}`;
    } catch (e) {
      note(caveat.parentElement, "Stealth posture unavailable.");
    }
  }

  // --- in-UI Update button (FR-OOBE-4) ------------------------------------
  function wireUpdate() {
    const btn = document.getElementById("update-btn");
    const out = document.getElementById("update-result");
    if (!btn) return;
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const r = await api("/api/update/trigger", { method: "POST" });
        out.hidden = false;
        out.textContent = r.message;
      } catch (e) {
        out.hidden = false;
        out.textContent = "Update check failed.";
      } finally {
        btn.disabled = false;
      }
    });
  }

  ApplicantUI.mount({ active: "debug" });
  loadTools();
  loadHistory();
  loadVariants();
  loadLogs();
  loadScreenshots();
  loadStealth();
  wireUpdate();
