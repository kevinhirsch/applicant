/* AppKit Gadget Rail — gadget rail container for the AppKit gadget cards.
   Renamed from upstream orwellGadgetRail.js per FR-UIKIT-4. */

"use strict";

import { ensureGadgetCss } from "./appkitGadget.js";

let _cssInjected = false;

function injectRailCss() {
  if (_cssInjected) return;
  _cssInjected = true;
  ensureGadgetCss();
  const st = document.createElement("style");
  st.id = "appkit-gadget-rail-css";
  st.textContent = `
    .og-rail {
      display: flex; flex-direction: column; gap: .5rem;
      padding: .5rem; overflow-y: auto;
    }
    .og-rail-horizontal {
      flex-direction: row; overflow-x: auto;
      padding: .5rem;
    }
    .og-rail-compact .og-card { font-size: .75rem; }
    .og-rail-compact .og-head { padding: .25rem .4rem; font-size: .78rem; }
    .og-rail-compact .og-body { padding: .25rem .4rem .35rem; }
  `;
  document.head.appendChild(st);
}

/**
 * Create a gadget rail container.
 * @param {object} opts - { horizontal, compact, ariaLabel }
 * @returns {HTMLElement}
 */
export function createRail(opts = {}) {
  injectRailCss();
  const rail = document.createElement("div");
  rail.className = "og-rail";
  if (opts.horizontal) rail.classList.add("og-rail-horizontal");
  if (opts.compact) rail.classList.add("og-rail-compact");
  if (opts.ariaLabel) rail.setAttribute("aria-label", opts.ariaLabel);
  rail.setAttribute("role", "list");
  return rail;
}

/**
 * Add a gadget card to a rail.
 * @param {HTMLElement} rail - The rail container
 * @param {HTMLElement} gadget - The gadget card
 */
export function addToRail(rail, gadget) {
  if (!rail || !gadget) return;
  gadget.setAttribute("role", "listitem");
  rail.appendChild(gadget);
}

window.AppKitGadgetRail = {
  createRail,
  addToRail,
};
