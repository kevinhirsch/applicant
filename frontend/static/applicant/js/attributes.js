/*
 * Applicant — your details editor.
 *
 * Lists the answers used to pre-fill applications (learned values included and
 * overridable), and adds or updates one. Important fields ask for confirmation
 * before saving; if the change isn't confirmed we re-ask, then retry with
 * confirm=true. Equal-opportunity fields can't be given an AI-suggested value.
 * Network failures are handled gracefully rather than showing a broken screen.
 */
import { ApplicantUI, apiFetch, el } from "/static/applicant/js/applicant-ui.js";

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
    // Important fields need confirmation (HTTP 409); re-ask, then retry.
    if (String(e.message) === "HTTP 409" && !confirm) {
      if (window.confirm("This is an important field. Save this change?")) {
        return save(true);
      }
      status("Change not confirmed — nothing was saved.", true);
      return;
    }
    if (String(e.message) === "HTTP 422") {
      status("Equal-opportunity fields are never auto-filled.", true);
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
