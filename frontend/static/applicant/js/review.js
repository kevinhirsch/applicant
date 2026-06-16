/*
 * Applicant — interactive document review (FR-RESUME-8, FR-RESUME-9, FR-ANSWER-1).
 *
 * Phase 3 thin client for the redline review surface:
 *  - renders the redline (additions + deletions highlighted) from the backend;
 *  - runs the interactive add/subtract/free-text revision loop;
 *  - approve/decline (no submission until approved).
 * The aggressiveness control (FR-RESUME-9) ships GRAYED/disabled. Network failures
 * degrade gracefully (no dead UI shown as live, FR-UI-2).
 */
(function () {
  "use strict";

  const documentId = document.body.getAttribute("data-document-id") || "";
  const variantId = document.body.getAttribute("data-variant-id") || "";

  async function api(path, opts) {
    const res = await fetch(path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.status === 204 ? null : res.json();
  }

  function setStatus(msg) {
    const el = document.getElementById("review-status");
    if (el) el.textContent = msg;
  }

  async function loadRedline(baseSource, newSource) {
    const view = document.getElementById("redline-view");
    try {
      const payload = await api("/api/documents/redline", {
        method: "POST",
        body: JSON.stringify({
          variant_id: variantId,
          base_source: baseSource || "",
          new_source: newSource || "",
          aggressiveness: 20,
        }),
      });
      // rendered_html already wraps additions/deletions in highlighted spans.
      view.innerHTML = payload.rendered_html || "(no differences)";
    } catch (e) {
      view.textContent = "Could not load the redline (backend unavailable).";
    }
  }

  function renderTurns(session) {
    const log = document.getElementById("turn-log");
    log.innerHTML = "";
    (session.turns || []).forEach((t) => {
      const li = document.createElement("li");
      li.textContent = `[${t.kind}] ${t.instruction} -> ${t.ai_response}`;
      log.appendChild(li);
    });
    setStatus("Status: " + (session.status || "open"));
  }

  async function openReview() {
    if (!documentId) return;
    try {
      const session = await api(`/api/documents/${encodeURIComponent(documentId)}/review`, { method: "POST" });
      renderTurns(session);
    } catch (e) {
      setStatus("Could not open the review session.");
    }
  }

  async function submitTurn(kind) {
    const instruction = (document.getElementById("revise-instruction") || {}).value || "";
    try {
      const session = await api(`/api/documents/${encodeURIComponent(documentId)}/turn`, {
        method: "POST",
        body: JSON.stringify({ kind: kind, instruction: instruction }),
      });
      renderTurns(session);
    } catch (e) {
      setStatus("Revision turn failed.");
    }
  }

  async function decide(action) {
    try {
      const doc = await api(`/api/documents/${encodeURIComponent(documentId)}/${action}`, { method: "POST" });
      setStatus(action === "approve" ? "Approved." : "Declined.");
      return doc;
    } catch (e) {
      setStatus(action + " failed.");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("button[data-kind]").forEach((btn) => {
      btn.addEventListener("click", () => submitTurn(btn.getAttribute("data-kind")));
    });
    const approve = document.getElementById("approve-btn");
    const decline = document.getElementById("decline-btn");
    if (approve) approve.addEventListener("click", () => decide("approve"));
    if (decline) decline.addEventListener("click", () => decide("decline"));
    openReview();
    loadRedline("", "");
  });
})();
