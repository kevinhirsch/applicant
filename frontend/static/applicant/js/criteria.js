/*
 * Applicant — criteria editor (FR-CRIT-1/2/3, FR-FB-3, FR-UI-6).
 *
 * Loads the campaign's criteria (human-readable + learned adjustments), lets the
 * user edit them, and PUTs the change. Integral edits route through the
 * confirmation gate (FR-FB-3): the API returns 409 and we re-ask, retrying with
 * confirm=true. Learned adjustments are surfaced and clearable (FR-CRIT-3).
 * Network failures degrade gracefully — never dead UI shown as live (FR-UI-2).
 */
import { ApplicantUI, apiFetch, el } from "./applicant-ui.js";

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
    status("Could not load criteria (backend unavailable).", true);
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
    // FR-FB-3: an integral change is confirmation-gated -> 409. Re-ask the user
    // and retry with confirm=true so the gate is surfaced, not hidden.
    if (String(e.message) === "HTTP 409" && !confirm) {
      if (window.confirm("This is an integral change to your criteria. Confirm it?")) {
        return save(true);
      }
      status("Integral change not confirmed — no edit applied (FR-FB-3).", true);
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
