/*
 * Applicant — digest + pending-actions portal (FR-DIG-3, FR-DIG-5/6, FR-UI-3).
 *
 * Phase 1 thin client: fetches the digest payload and pending actions for the active
 * campaign, renders the FR-DIG-3 table (summary, work mode, score, why-suggested,
 * approve/decline-with-feedback), and the pending-actions list. Decline collects
 * free-text feedback that the backend folds into learning + the next run (FR-DIG-5).
 * Network failures degrade gracefully (no dead UI shown as live, FR-UI-2).
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

  function renderEmpty(tbody, note) {
    tbody.innerHTML = "";
    tbody.appendChild(el("tr", {}, [el("td", { colSpan: 5, className: "admin-empty applicant-note" }, [note])]));
  }

  async function loadDigest() {
    const tbody = document.getElementById("digest-rows");
    const noteEl = document.getElementById("digest-empty-note");
    try {
      const payload = await api(`/api/digest/${encodeURIComponent(campaignId)}`);
      if (payload.empty) {
        noteEl.hidden = false;
        noteEl.textContent = payload.note;
        renderEmpty(tbody, payload.note);
        return;
      }
      noteEl.hidden = true;
      tbody.innerHTML = "";
      payload.rows.forEach((row) => tbody.appendChild(digestRow(row)));
    } catch (e) {
      renderEmpty(tbody, "Could not load the digest (backend unavailable).");
    }
  }

  function digestRow(row) {
    const actions = el("div", {});
    const approve = el("button", { className: "admin-btn admin-btn-sm", textContent: "Approve" });
    approve.addEventListener("click", () => decide(row, "approve"));
    const decline = el("button", { className: "admin-btn admin-btn-sm", textContent: "Decline" });
    const feedback = el("input", {
      className: "applicant-feedback",
      placeholder: "Why not? (feeds learning, FR-DIG-5)",
      type: "text",
    });
    decline.addEventListener("click", () => decide(row, "decline", feedback.value));
    actions.appendChild(approve);
    actions.appendChild(decline);
    actions.appendChild(feedback);

    return el("tr", {}, [
      el("td", {}, [el("a", { href: row.link, textContent: row.summary, target: "_blank", rel: "noopener" })]),
      el("td", {}, [row.work_mode || "—"]),
      el("td", {}, [row.viability_score == null ? "—" : String(row.viability_score)]),
      el("td", { className: "admin-empty" }, [row.why_suggested || ""]),
      el("td", {}, [actions]),
    ]);
  }

  async function decide(row, kind, feedbackText) {
    // Phase 1: digest rows reference postings; application binding lands in Phase 2.
    const appId = row.application_id || row.posting_id;
    const base = `/api/digest/applications/${encodeURIComponent(appId)}`;
    try {
      if (kind === "approve") {
        await api(base + "/approve", { method: "POST" });
      } else {
        await api(base + "/decline", {
          method: "POST",
          body: JSON.stringify({ feedback_text: feedbackText || "", criteria_delta: {} }),
        });
      }
      loadDigest();
    } catch (e) {
      /* leave the row; surfacing an error toast is a later polish item */
    }
  }

  async function loadPending() {
    const list = document.getElementById("pending-list");
    try {
      const payload = await api(`/api/pending-actions/${encodeURIComponent(campaignId)}`);
      list.innerHTML = "";
      if (!payload.items.length) {
        list.appendChild(el("li", { className: "admin-empty" }, ["Nothing pending — all caught up."]));
        return;
      }
      payload.items.forEach((item) => {
        const li = el("li", {}, [`${item.kind}: ${item.title} `]);
        const resolve = el("button", { className: "admin-btn admin-btn-sm", textContent: "Resolve" });
        resolve.addEventListener("click", async () => {
          try { await api(`/api/pending-actions/${encodeURIComponent(item.id)}/resolve`, { method: "POST" }); loadPending(); } catch (e) {}
        });
        li.appendChild(resolve);
        list.appendChild(li);
      });
    } catch (e) {
      list.innerHTML = "";
      list.appendChild(el("li", { className: "admin-empty" }, ["Could not load pending actions."]));
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadDigest();
    loadPending();
  });
})();
