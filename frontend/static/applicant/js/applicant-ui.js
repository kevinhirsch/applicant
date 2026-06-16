/*
 * Applicant — shared UI module for our own surfaces (FR-UI-1/2/5/6).
 *
 * Single source of truth for the chrome/wiring shared by every Applicant surface
 * (wizard / digest / review / debug / chat). Vanilla ES module, no build step — it
 * mirrors the Odysseus "vendored, hand-authored" model. It does NOT restyle the
 * vendored design system; it only reuses its classes so every surface renders
 * identically while sharing one fetch helper, one nav, and a few component helpers.
 *
 * Each surface becomes a thin content fragment that ends with:
 *     import { ApplicantUI } from "./js/applicant-ui.js";
 *     ApplicantUI.mount({ active: "digest" });   // injects shared nav
 * plus its own page glue (which can use ApplicantUI.apiFetch / el / toast / ...).
 */

// The surfaces, in nav order. Adding a surface = add one entry here + one HTML
// fragment (see docs/frontend.md). Keep this list aligned with the ui router.
export const SURFACES = [
  { key: "wizard", href: "/wizard", label: "Setup" },
  { key: "digest", href: "/digest", label: "Digest" },
  { key: "criteria", href: "/criteria", label: "Criteria" },
  { key: "attributes", href: "/attributes", label: "Attributes" },
  { key: "review", href: "/review", label: "Review" },
  { key: "debug", href: "/debug", label: "Debug" },
  { key: "chat", href: "/chat", label: "Assistant" },
];

/**
 * apiFetch(path, opts) — JSON fetch with shared error handling and the LLM-gate /
 * automated-work redirect (FR-UI-5). On a 409 from the setup gate, every surface
 * (except the wizard, which is how the user opens the gate) routes to the wizard.
 * Returns parsed JSON, or null for 204. Throws Error("HTTP <status>") otherwise.
 */
export async function apiFetch(path, opts) {
  const res = await fetch(
    path,
    Object.assign({ headers: { "Content-Type": "application/json" } }, opts || {})
  );
  if (res.status === 409) {
    // The setup/automated-work gate is closed: send the user to the wizard so
    // they can open it. The wizard itself must not redirect to itself.
    if (!_isWizard()) {
      window.location.assign("/wizard");
    }
    throw new Error("HTTP 409");
  }
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.status === 204 ? null : res.json();
}

function _isWizard() {
  const p = window.location.pathname;
  return p === "/" || p === "/wizard" || p.endsWith("/wizard.html");
}

/**
 * el(tag, attrs, children) — tiny DOM builder shared by the surface glue.
 * children may be strings (text nodes) or Nodes.
 */
export function el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.assign(node, attrs || {});
  (children || []).forEach((c) =>
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c)
  );
  return node;
}

/**
 * mountShell({ active }) — inject the shared Odysseus-styled nav into the
 * #applicant-nav container (if present), marking the active link. Surfaces that
 * predate the shared nav simply omit the container and render unchanged.
 */
export function mountShell(opts) {
  const active = (opts || {}).active || "";
  const host = document.getElementById("applicant-nav");
  if (!host) return;
  const nav = el("nav", { className: "applicant-nav" });
  SURFACES.forEach((s) => {
    const a = el("a", {
      href: s.href,
      textContent: s.label,
      className: "admin-btn admin-btn-sm" + (s.key === active ? " applicant-nav-active" : ""),
    });
    if (s.key === active) a.setAttribute("aria-current", "page");
    nav.appendChild(a);
  });
  host.innerHTML = "";
  host.appendChild(nav);
}

// --- design-system component helpers (reuse the vendored CSS classes) --------

/** openModal(elOrId) — show a vendored .modal by removing the .hidden class. */
export function openModal(elOrId) {
  const m = _resolve(elOrId);
  if (m) m.classList.remove("hidden");
  return m;
}

/** closeModal(elOrId) — hide a vendored .modal by adding the .hidden class. */
export function closeModal(elOrId) {
  const m = _resolve(elOrId);
  if (m) m.classList.add("hidden");
  return m;
}

/**
 * bindToggle(elOrId, onChange) — wire a vendored .toggle-switch input's change
 * event. onChange(checked) may return a Promise; if it rejects the toggle reverts.
 */
export function bindToggle(elOrId, onChange) {
  const input = _resolve(elOrId);
  if (!input) return;
  input.addEventListener("change", async () => {
    try {
      await onChange(input.checked);
    } catch (e) {
      input.checked = !input.checked; // revert on failure
    }
  });
  return input;
}

/**
 * toast(message, { error }) — transient notice using the vendored .toast classes.
 * Falls back to a console message if the document body is unavailable.
 */
export function toast(message, opts) {
  const isError = !!(opts && opts.error);
  if (!document.body) return;
  const node = el("div", { className: "toast" + (isError ? " error" : "") }, [String(message)]);
  document.body.appendChild(node);
  // Match the vendored .toast.show / .toast.exiting lifecycle.
  requestAnimationFrame(() => node.classList.add("show"));
  setTimeout(() => {
    node.classList.add("exiting");
    setTimeout(() => node.remove(), 400);
  }, 2600);
  return node;
}

function _resolve(elOrId) {
  return typeof elOrId === "string" ? document.getElementById(elOrId) : elOrId;
}

/** mount(opts) — convenience: run mountShell on DOMContentLoaded. */
export function mount(opts) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => mountShell(opts));
  } else {
    mountShell(opts);
  }
}

export const ApplicantUI = {
  SURFACES,
  apiFetch,
  el,
  mountShell,
  mount,
  openModal,
  closeModal,
  bindToggle,
  toast,
};

export default ApplicantUI;
