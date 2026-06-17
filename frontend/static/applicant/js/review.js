/*
 * Applicant — document review.
 *
 *  - resume / cover-letter / screening-answer tabs over an application's documents;
 *  - shows what changed (additions and removals highlighted);
 *  - runs the add/subtract/free-text revision loop, refreshing the changes after
 *    each request;
 *  - approve or decline (nothing is submitted until you approve it).
 * The aggressiveness control isn't available yet and ships disabled. Network
 * failures are handled gracefully. Shares the redirect-aware fetch from ApplicantUI.
 */
import { ApplicantUI, apiFetch } from "/static/applicant/js/applicant-ui.js";

  function qs(name) {
    var m = new RegExp("[?&]" + name + "=([^&]*)").exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : "";
  }

  // The notification link passes ?document_id=; fall back to the data attribute.
  var documentId = qs("document_id") || document.body.getAttribute("data-document-id") || "";
  var variantId = document.body.getAttribute("data-variant-id") || "";
  var applicationId = qs("application_id") || document.body.getAttribute("data-application-id") || "";
  var activeType = "resume";
  var lastBase = "";

  const api = apiFetch;

  function setStatus(msg) {
    const el = document.getElementById("review-status");
    if (el) el.textContent = msg;
  }

  async function loadRedline(baseSource, newSource) {
    const view = document.getElementById("redline-view");
    if (!view) return;
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
      view.textContent = "Could not load the changes. Please try again.";
    }
  }

  function renderTurns(session) {
    const log = document.getElementById("turn-log");
    if (!log) return;
    log.innerHTML = "";
    (session.turns || []).forEach((t) => {
      const li = document.createElement("li");
      li.textContent = "[" + t.kind + "] " + t.instruction + " -> " + t.ai_response;
      log.appendChild(li);
    });
    setStatus("Status: " + (session.status || "open"));
    // Re-render the redline from the latest revised content (filters already applied
    // server-side on every turn): base = original, new = current redline_state.
    if (session.redline_state && typeof session.redline_state.content === "string") {
      loadRedline(lastBase, session.redline_state.content);
    }
  }

  async function loadMaterials() {
    const list = document.getElementById("material-list");
    if (!list || !applicationId) return;
    try {
      const payload = await api("/api/documents/applications/" + encodeURIComponent(applicationId));
      list.innerHTML = "";
      (payload.items || [])
        .filter((d) => d.type === activeType)
        .forEach((d) => {
          const li = document.createElement("li");
          const btn = document.createElement("button");
          btn.className = "admin-btn admin-btn-sm";
          btn.textContent = (d.approved ? "[approved] " : "") + d.id;
          btn.addEventListener("click", () => {
            documentId = d.id;
            lastBase = d.content || "";
            openReview();
            loadRedline(lastBase, lastBase);
          });
          li.appendChild(btn);
          list.appendChild(li);
        });
      if (!list.children.length) list.textContent = "No " + activeType + " materials yet.";
    } catch (e) {
      list.textContent = "Could not load materials.";
    }
  }

  async function openReview() {
    if (!documentId) return;
    try {
      const session = await api("/api/documents/" + encodeURIComponent(documentId) + "/review", { method: "POST" });
      renderTurns(session);
    } catch (e) {
      setStatus("Could not open the review session.");
    }
  }

  async function submitTurn(kind) {
    if (!documentId) {
      setStatus("Select a material first.");
      return;
    }
    const instruction = (document.getElementById("revise-instruction") || {}).value || "";
    try {
      const session = await api("/api/documents/" + encodeURIComponent(documentId) + "/turn", {
        method: "POST",
        body: JSON.stringify({ kind: kind, instruction: instruction }),
      });
      renderTurns(session);
    } catch (e) {
      setStatus("Revision turn failed.");
    }
  }

  async function decide(action) {
    if (!documentId) return;
    try {
      const doc = await api("/api/documents/" + encodeURIComponent(documentId) + "/" + action, { method: "POST" });
      setStatus(action === "approve" ? "Approved." : "Declined.");
      loadMaterials();
      return doc;
    } catch (e) {
      setStatus(action + " failed.");
    }
  }

  function selectTab(type) {
    activeType = type;
    document.querySelectorAll(".review-tab").forEach((t) => {
      t.setAttribute("aria-selected", String(t.getAttribute("data-type") === type));
    });
    loadMaterials();
  }

  document.addEventListener("DOMContentLoaded", function () {
    ApplicantUI.mountShell({ active: "review" });
    document.querySelectorAll("button[data-kind]").forEach((btn) => {
      btn.addEventListener("click", () => submitTurn(btn.getAttribute("data-kind")));
    });
    document.querySelectorAll(".review-tab").forEach((tab) => {
      tab.addEventListener("click", () => selectTab(tab.getAttribute("data-type")));
    });
    const approve = document.getElementById("approve-btn");
    const decline = document.getElementById("decline-btn");
    if (approve) approve.addEventListener("click", () => decide("approve"));
    if (decline) decline.addEventListener("click", () => decide("decline"));
    loadMaterials();
    openReview();
    loadRedline("", "");
  });
