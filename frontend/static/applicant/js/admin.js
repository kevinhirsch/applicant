/*
 * Applicant — debug/observability + tool-toggle + history surface client.
 * FR-UI-4 (tool toggles), FR-OBS-2 / FR-LOG-3 (history + workflow state),
 * FR-OOBE-4 (in-UI Update button). Phase 4 thin client.
 *
 * Network failures degrade gracefully — a dormant/error note is shown, never
 * dead UI presented as live (FR-UI-2).
 */
(function () {
  "use strict";

  const campaignId = document.body.getAttribute("data-campaign-id") || "";

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.status === 204 ? null : res.json();
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.assign(node, attrs || {});
    (children || []).forEach((c) => node.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return node;
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
      list.innerHTML = "";
      list.appendChild(el("p", { className: "admin-empty applicant-note" }, ["Tool registry unavailable."]));
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
        tbody.appendChild(el("tr", {}, [el("td", { colSpan: 4, className: "admin-empty" }, ["No applications yet."])]));
        return;
      }
      apps.forEach((a) => {
        tbody.appendChild(el("tr", {}, [
          el("td", {}, [a.role_name || a.job_title || "—"]),
          el("td", {}, [a.status]),
          el("td", {}, [a.work_mode || "—"]),
          el("td", {}, [el("a", { href: `/api/admin/workflow/${encodeURIComponent(a.application_id)}` }, ["state"])]),
        ]));
      });
    } catch (e) {
      tbody.innerHTML = "";
      tbody.appendChild(el("tr", {}, [el("td", { colSpan: 4, className: "admin-empty applicant-note" }, ["History unavailable."])]));
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

  loadTools();
  loadHistory();
  wireUpdate();
})();
