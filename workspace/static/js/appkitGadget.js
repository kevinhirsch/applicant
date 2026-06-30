/* AppKit Gadget — focusable widget cards (.og-card, .og-head, .og-body).
   Renamed from upstream orwellGadget.js per FR-UIKIT-4. */

"use strict";

let _cssInjected = false;

function injectCss() {
  if (_cssInjected) return;
  _cssInjected = true;
  const st = document.createElement("style");
  st.id = "appkit-gadget-css";
  st.textContent = `
    .og-card {
      border: 1px solid var(--border, #355a66); border-radius: 8px;
      background: var(--panel, #111); color: var(--fg, #9cdef2);
      font-size: .8rem; line-height: 1.4;
      overflow: hidden; transition: border-color .12s ease, box-shadow .12s ease;
    }
    .og-card:focus-visible {
      outline: 2px solid var(--accent, #e06c75); outline-offset: 2px;
    }
    .og-card:hover {
      border-color: color-mix(in srgb, var(--accent, #e06c75) 40%, var(--border, #355a66));
    }
    .og-head {
      display: flex; align-items: center; gap: .4rem;
      padding: .4rem .6rem;
      font-weight: 600; font-size: .85rem;
      border-bottom: 1px solid var(--border, #355a66);
      background: color-mix(in srgb, var(--bg, #282c34) 50%, transparent);
    }
    .og-body { padding: .4rem .6rem .5rem; }
    .og-card-draggable { cursor: grab; }
    .og-card-draggable:active { cursor: grabbing; }
  `;
  document.head.appendChild(st);
}

/**
 * Create a gadget card element.
 * @param {object} opts - { title, icon, content (Node|string), draggable, ariaLabel }
 * @returns {HTMLElement}
 */
export function createGadget(opts = {}) {
  injectCss();
  const card = document.createElement("div");
  card.className = "og-card";
  if (opts.draggable) card.classList.add("og-card-draggable");
  if (opts.ariaLabel) card.setAttribute("aria-label", opts.ariaLabel);
  card.setAttribute("tabindex", "0");

  const head = document.createElement("div");
  head.className = "og-head";
  if (opts.icon) {
    const icon = document.createElement("span");
    icon.style.cssText = "display:inline-flex;width:16px;height:16px;flex-shrink:0;";
    if (typeof opts.icon === "string") icon.innerHTML = opts.icon;
    else icon.appendChild(opts.icon);
    head.appendChild(icon);
  }
  const title = document.createElement("span");
  title.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
  title.textContent = opts.title || "";
  head.appendChild(title);
  card.appendChild(head);

  if (opts.content) {
    const body = document.createElement("div");
    body.className = "og-body";
    if (opts.content instanceof Node) body.appendChild(opts.content);
    else if (typeof opts.content === "string") body.innerHTML = opts.content;
    card.appendChild(body);
  }

  return card;
}

export { injectCss as ensureGadgetCss };

window.AppKitGadget = {
  createGadget,
};
