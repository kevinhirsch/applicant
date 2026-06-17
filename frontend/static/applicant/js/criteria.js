/*
 * Applicant — search criteria editor.
 *
 * Loads the search criteria (plain-language summary plus learned adjustments),
 * lets the user edit them, and saves the change. Important changes ask for
 * confirmation: if not confirmed we re-ask, then retry with confirm=true.
 * Learned adjustments are shown and clearable. Network failures are handled
 * gracefully rather than showing a broken screen.
 */
import { ApplicantUI, apiFetch, el } from "/static/applicant/js/applicant-ui.js";

const campaignId =
  document.body.getAttribute("data-campaign-id") ||
  new URLSearchParams(location.search).get("campaign_id") ||
  "default";
const api = apiFetch;

function csv(value) {
  return (value || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function status(text, isError) {
  const node = document.getElementById("criteria-status");
  node.hidden = false;
  node.textContent = text;
  node.classList.toggle("applicant-error", !!isError);
}

async function load() {
  try {
    const c = await api(`/api/criteria/${encodeURIComponent(campaignId)}`);
    document.getElementById("c-human").value = c.human_readable || "";
    document.getElementById("c-titles").value = (c.titles || []).join(", ");
    document.getElementById("c-locations").value = (c.locations || []).join(", ");
    document.getElementById("c-modes").value = (c.work_modes || []).join(", ");
    document.getElementById("c-keywords").value = (c.keywords || []).join(", ");
    document.getElementById("c-salary").value = c.salary_floor == null ? "" : c.salary_floor;
    renderLearned(c.learned_adjustments);
  } catch (e) {
    status("Could not load criteria. Please try again.", true);
  }
}

function renderLearned(adjustments) {
  const pre = document.getElementById("learned-json");
  pre.textContent =
    adjustments && Object.keys(adjustments).length
      ? JSON.stringify(adjustments, null, 2)
      : "No learned adjustments yet.";
}

function collect(confirm) {
  const salary = document.getElementById("c-salary").value;
  return {
    human_readable: document.getElementById("c-human").value,
    titles: csv(document.getElementById("c-titles").value),
    locations: csv(document.getElementById("c-locations").value),
    work_modes: csv(document.getElementById("c-modes").value),
    keywords: csv(document.getElementById("c-keywords").value),
    salary_floor: salary === "" ? null : Number(salary),
    confirm: !!confirm,
  };
}

async function save(confirm) {
  let body = collect(confirm);
  try {
    const updated = await api(`/api/criteria/${encodeURIComponent(campaignId)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    renderLearned(updated.learned_adjustments);
    status("Criteria saved.");
  } catch (e) {
    // An important change needs confirmation (HTTP 409). Re-ask, then retry.
    if (String(e.message) === "HTTP 409" && !confirm) {
      if (window.confirm("This is an important change to your criteria. Save it?")) {
        return save(true);
      }
      status("Change not confirmed — nothing was saved.", true);
      return;
    }
    status("Could not save criteria.", true);
  }
}

async function clearLearned() {
  try {
    const updated = await api(`/api/criteria/${encodeURIComponent(campaignId)}`, {
      method: "PUT",
      body: JSON.stringify({ clear_learned: true, confirm: true }),
    });
    renderLearned(updated.learned_adjustments);
    status("Learned adjustments cleared.");
  } catch (e) {
    status("Could not clear learned adjustments.", true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  ApplicantUI.mountShell({ active: "criteria" });
  document.getElementById("criteria-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    save(false);
  });
  document.getElementById("c-clear-learned").addEventListener("click", clearLearned);
  load();
});
