/*
 * Applicant — daily digest and the things waiting for your input.
 *
 * Fetches the digest and the waiting-for-you list for the active search, then
 * renders the digest table (role, work mode, score, why suggested, approve or
 * decline with feedback) and the list. Decline collects a short note that Applicant
 * learns from for next time. Network failures are handled gracefully. Shares the
 * redirect-aware fetch and DOM builder from ApplicantUI.
 */
import { ApplicantUI, apiFetch, el } from "/static/applicant/js/applicant-ui.js";

const campaignId = document.body.getAttribute("data-campaign-id") || "";
const api = apiFetch;

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
    renderEmpty(tbody, "Could not load the digest. Please try again.");
  }
}

function digestRow(row) {
  const actions = el("div", {});
  const approve = el("button", { className: "admin-btn admin-btn-sm", textContent: "Approve" });
  approve.addEventListener("click", () => decide(row, "approve"));
  const decline = el("button", { className: "admin-btn admin-btn-sm", textContent: "Decline" });
  const feedback = el("input", {
    className: "applicant-feedback",
    placeholder: "Why not? (helps Applicant learn)",
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
    /* leave the row in place if the action could not be saved */
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

// Let the app know you're active in the browser so it can hold the Discord ping
// and show the update here instead.
async function signalPresence(present) {
  try {
    await api("/api/digest/presence", { method: "POST", body: JSON.stringify({ present: present }) });
  } catch (e) {
    /* presence is best-effort */
  }
}

document.addEventListener("DOMContentLoaded", function () {
  ApplicantUI.mountShell({ active: "digest" });
  loadDigest();
  loadPending();
  signalPresence(true);
  document.addEventListener("visibilitychange", function () {
    signalPresence(document.visibilityState === "visible");
  });
  window.addEventListener("focus", function () { signalPresence(true); });
  window.addEventListener("blur", function () { signalPresence(false); });
});
