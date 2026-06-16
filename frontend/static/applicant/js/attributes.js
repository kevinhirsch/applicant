/*
 * Applicant — attribute-cloud editor (FR-ATTR-1/2/3/4/6, FR-FB-3, FR-UI-6).
 *
 * Lists the campaign's attributes (the pre-fill answers, learned values included
 * and overridable), and adds/updates one. Integral edits are confirmation-gated
 * (FR-FB-3): the API 409s and we re-ask, retrying with confirm=true. A sensitive
 * attribute given an AI-suggested value is rejected (FR-ATTR-6 -> 422), surfaced
 * here. Network failures degrade gracefully — no dead UI as live (FR-UI-2).
 */
import { ApplicantUI, apiFetch, el } from "./applicant-ui.js";

const campaignId =
  document.body.getAttribute("data-campaign-id") ||
  new URLSearchParams(location.search).get("campaign_id") ||
  "default";
const api = apiFetch;

function status(text, isError) {
  const node = document.getElementById("attributes-status");
  node.hidden = false;
  node.textContent = text;
  node.classList.toggle("applicant-error", !!isError);
}

function flags(a) {
  const parts = [];
  if (a.is_integral) parts.push("integral");
  if (a.is_sensitive) parts.push("sensitive");
  return parts.join(", ") || "—";
}

async function load() {
  const tbody = document.getElementById("attributes-rows");
  try {
    const payload = await api(`/api/attributes/${encodeURIComponent(campaignId)}`);
    tbody.innerHTML = "";
    if (!payload.items.length) {
      tbody.appendChild(
        el("tr", {}, [el("td", { colSpan: 3, className: "admin-empty" }, ["No attributes yet — add one below."])])
      );
      return;
    }
    payload.items.forEach((a) => {
      tbody.appendChild(
        el("tr", {}, [
          el("td", {}, [a.name]),
          el("td", {}, [a.value]),
          el("td", { className: "admin-empty" }, [flags(a)]),
        ])
      );
    });
  } catch (e) {
    tbody.innerHTML = "";
    tbody.appendChild(
      el("tr", {}, [el("td", { colSpan: 3, className: "admin-empty applicant-error" }, ["Could not load attributes."])])
    );
  }
}

async function save(confirm) {
  const body = {
    campaign_id: campaignId,
    name: document.getElementById("a-name").value,
    value: document.getElementById("a-value").value,
    is_integral: document.getElementById("a-integral").checked,
    is_sensitive: document.getElementById("a-sensitive").checked,
    confirm: !!confirm,
  };
  try {
    await api("/api/attributes", { method: "POST", body: JSON.stringify(body) });
    status("Attribute saved.");
    load();
  } catch (e) {
    // FR-FB-3: integral change is confirmation-gated -> 409; re-ask + retry.
    if (String(e.message) === "HTTP 409" && !confirm) {
      if (window.confirm("This is an integral change. Confirm it?")) {
        return save(true);
      }
      status("Integral change not confirmed — no edit applied (FR-FB-3).", true);
      return;
    }
    if (String(e.message) === "HTTP 422") {
      status("Sensitive attributes are never AI-guessed (FR-ATTR-6).", true);
      return;
    }
    status("Could not save attribute.", true);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  ApplicantUI.mountShell({ active: "attributes" });
  document.getElementById("attribute-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    save(false);
  });
  load();
});
