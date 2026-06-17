/*
 * Applicant — diagnostics: tool switches, application history, resume variants,
 * activity log, screenshots, and the in-app updater.
 *
 * Network failures are handled gracefully — an error note is shown rather than a
 * broken screen. Shares the redirect-aware fetch and DOM builder from ApplicantUI.
 */
import { ApplicantUI, apiFetch, el } from "/static/applicant/js/applicant-ui.js";

  const params = new URLSearchParams(location.search);
  const campaignId = document.body.getAttribute("data-campaign-id") || params.get("campaign_id") || "";
  const applicationId = document.body.getAttribute("data-application-id") || params.get("application_id") || "";

  const api = apiFetch;

  function note(container, text) {
    container.innerHTML = "";
    container.appendChild(el("p", { className: "admin-empty applicant-note" }, [text]));
  }

  // --- tool switches -------------------------------------------------------
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
      note(list, "Tools unavailable.");
    }
  }

  // --- application history -------------------------------------------------
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

  // --- resume variants -----------------------------------------------------
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
      tbody.appendChild(el("tr", {}, [el("td", { colSpan: 5, className: "admin-empty applicant-note" }, ["Resume variants unavailable."])]));
    }
  }

  // --- recent activity -----------------------------------------------------
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

  // --- screenshots ---------------------------------------------------------
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

  // --- stealth caveat + network posture ------------------------------------
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

  // --- in-app updater ------------------------------------------------------
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
