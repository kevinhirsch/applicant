/* AppKit Notice — severity notification cards (.on-card, .on-sev-*, .on-icon).
   Renamed from upstream orwellNotice.js per FR-UIKIT-4.
   Re-backs ui.js showToast through the Notice Kit per FR-UIKIT-3. */

"use strict";

let _cssInjected = false;

function injectCss() {
  if (_cssInjected) return;
  _cssInjected = true;
  const st = document.createElement("style");
  st.id = "appkit-notice-css";
  st.textContent = `
    .on-card {
      display: flex; align-items: flex-start; gap: .5rem;
      padding: .5rem .7rem; border-radius: 8px;
      border: 1px solid var(--border, #355a66);
      background: var(--panel, #111); color: var(--fg, #9cdef2);
      font-size: .8rem; line-height: 1.4;
      box-shadow: 0 4px 12px rgba(0,0,0,.25);
    }
    .on-icon { flex-shrink: 0; width: 18px; height: 18px; margin-top: 1px; }
    .on-body { flex: 1; min-width: 0; }
    .on-dismiss {
      flex-shrink: 0; background: none; border: none; color: inherit;
      cursor: pointer; opacity: .5; padding: 2px; font-size: 1rem; line-height: 1;
    }
    .on-dismiss:hover { opacity: 1; }
    .on-sev-info { border-left: 3px solid var(--accent, #e06c75); }
    .on-sev-success { border-left: 3px solid var(--color-success, #4caf50); }
    .on-sev-warning { border-left: 3px solid var(--color-warning, #f0ad4e); }
    .on-sev-error { border-left: 3px solid var(--color-error, #ff4444); }
    .on-sev-recording { border-left: 3px solid var(--color-recording, #ff3b30); }
    .on-toast {
      position: fixed; bottom: 20px; right: 20px; z-index: 9999;
      max-width: 360px; pointer-events: auto;
    }
    .on-toast-show { animation: on-toast-in .2s ease-out; }
    @keyframes on-toast-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    @media (prefers-reduced-motion: reduce) {
      .on-toast-show { animation: none; }
    }
  `;
  document.head.appendChild(st);
}

/**
 * Create a notice card element.
 * @param {object} opts - { severity, icon, message, dismissable, action }
 * @returns {HTMLElement}
 */
export function createNotice(opts = {}) {
  injectCss();
  const card = document.createElement("div");
  card.className = "on-card";
  if (opts.severity) card.classList.add("on-sev-" + opts.severity);

  if (opts.icon) {
    const icon = document.createElement("span");
    icon.className = "on-icon";
    if (typeof opts.icon === "string") icon.innerHTML = opts.icon;
    else icon.appendChild(opts.icon);
    card.appendChild(icon);
  }

  const body = document.createElement("div");
  body.className = "on-body";
  if (typeof opts.message === "string") body.textContent = opts.message;
  else if (opts.message instanceof Node) body.appendChild(opts.message);
  card.appendChild(body);

  if (opts.dismissable !== false) {
    const dismiss = document.createElement("button");
    dismiss.className = "on-dismiss";
    dismiss.type = "button";
    dismiss.setAttribute("aria-label", "Dismiss notification");
    dismiss.innerHTML = "&times;";
    dismiss.addEventListener("click", () => { card.remove(); });
    card.appendChild(dismiss);
  }

  return card;
}

/**
 * Show a toast notification using the Notice Kit (.on-card).
 * Replaces the bare showToast implementation per FR-UIKIT-3.
 * @param {string} msg - Message text
 * @param {object|number} opts - Options or duration in ms
 * @returns {HTMLElement} The toast element
 */
export function showToast(msg, opts) {
  injectCss();
  // Remove any existing toast
  const existing = document.querySelector(".on-toast");
  if (existing) existing.remove();

  let duration = 1200;
  let severity = "info";
  let actionLabel = null;
  let onAction = null;

  if (typeof opts === "object" && opts) {
    if (opts.duration) duration = opts.duration;
    if (opts.severity) severity = opts.severity;
    actionLabel = opts.action || null;
    onAction = opts.onAction || null;
  } else if (typeof opts === "number") {
    duration = opts;
  }

  const card = createNotice({
    severity,
    message: msg,
    dismissable: false,
    icon: severity === "success" ? '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>' : undefined,
  });
  card.classList.add("on-toast", "on-toast-show");

  if (actionLabel && onAction) {
    const btn = document.createElement("button");
    btn.textContent = actionLabel;
    btn.style.cssText = "margin-left:8px;padding:2px 8px;border:1px solid var(--fg);border-radius:4px;background:none;color:var(--fg);cursor:pointer;font-size:12px;";
    btn.addEventListener("click", (e) => { e.stopPropagation(); card.remove(); onAction(); });
    card.querySelector(".on-body").appendChild(btn);
  }

  document.body.appendChild(card);

  setTimeout(() => {
    card.classList.remove("on-toast-show");
    card.style.opacity = "0";
    setTimeout(() => card.remove(), 300);
  }, duration);

  return card;
}

export { injectCss as ensureNoticeCss };

window.AppKitNotice = {
  createNotice,
  showToast,
};
