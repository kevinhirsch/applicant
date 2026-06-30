/* AppKit Decision — prompt → options → confirm with risk variant (.odec-*).
   Renamed from upstream orwellDecision.js per FR-UIKIT-4.
   Standardizes approve/decline/confirm incl. the destructive variant. */

"use strict";

import { esc } from "./applicantCore.js";

let _cssInjected = false;

function injectCss() {
  if (_cssInjected) return;
  _cssInjected = true;
  const st = document.createElement("style");
  st.id = "appkit-decision-css";
  st.textContent = `
    .odec-card {
      border: 1px solid var(--border, #355a66); border-radius: 8px;
      background: var(--panel, #111); color: var(--fg, #9cdef2);
      font-size: .8rem; line-height: 1.4;
      padding: .6rem .7rem; max-width: 420px;
      box-shadow: 0 6px 20px rgba(0,0,0,.35);
    }
    .odec-card.odec-risk {
      border-color: var(--color-error, #ff4444);
      box-shadow: 0 6px 20px rgba(255,68,68,.2);
    }
    .odec-head { display: flex; align-items: baseline; gap: .5rem; }
    .odec-title { font-weight: 700; letter-spacing: .03em; flex: 1; }
    .odec-x { cursor: pointer; border: none; background: none; color: inherit; opacity: .55; font-size: 1rem; padding: 0 4px; }
    .odec-x:hover { opacity: .9; }
    .odec-prompt { margin: .35rem 0 .55rem; opacity: .9; }
    .odec-opts { display: flex; flex-wrap: wrap; gap: .4rem; }
    .odec-opt {
      padding: .3rem .6rem; border: 1px solid var(--border, #355a66); border-radius: 6px;
      background: transparent; color: var(--fg, #9cdef2); cursor: pointer;
      font: inherit; font-size: .78rem; transition: background .1s ease, border-color .1s ease;
    }
    .odec-opt:hover { background: color-mix(in srgb, var(--accent, #e06c75) 12%, transparent); }
    .odec-opt[aria-pressed="true"] { border-color: var(--accent, #e06c75); background: var(--accent, #e06c75); color: #fff; }
    .odec-row { display: flex; align-items: center; gap: .6rem; margin-top: .65rem; }
    .odec-confirm {
      padding: .35rem .85rem; border: none; border-radius: 6px;
      background: var(--accent, #e06c75); color: #fff; cursor: pointer;
      font: inherit; font-size: .8rem; font-weight: 600;
    }
    .odec-confirm:disabled { opacity: .4; cursor: not-allowed; }
    .odec-confirm.odec-risk { background: var(--color-error, #ff4444); }
    .odec-note { opacity: .65; font-size: .78em; flex: 1; }
    .odec-err { color: var(--red, #e06c75); margin-top: .4rem; }
    .odec-done { border-color: var(--border, #355a66); opacity: .8; }
    .odec-risk-badge {
      display: inline-block; padding: 1px 6px; border-radius: 3px;
      background: var(--color-error, #ff4444); color: #fff;
      font-size: .68rem; font-weight: 700; text-transform: uppercase;
    }
  `;
  document.head.appendChild(st);
}

/**
 * Create a decision card for prompt → options → confirm.
 * @param {object} opts - { id, title, prompt, options, risk, onConfirm, onDismiss, confirmLabel }
 * @returns {HTMLElement}
 */
export function createDecision(opts = {}) {
  injectCss();
  const card = document.createElement("div");
  card.id = opts.id || "appkit-decision-card";
  card.className = "odec-card" + (opts.risk ? " odec-risk" : "");

  // Header
  const head = document.createElement("div");
  head.className = "odec-head";
  head.innerHTML = `<span class="odec-title">${esc(opts.title || "")}</span>`;
  if (opts.risk) {
    const badge = document.createElement("span");
    badge.className = "odec-risk-badge";
    badge.textContent = "Risk";
    head.appendChild(badge);
  }
  const xBtn = document.createElement("button");
  xBtn.className = "odec-x"; xBtn.type = "button";
  xBtn.setAttribute("aria-label", "Close");
  xBtn.innerHTML = "&times;";
  xBtn.addEventListener("click", () => {
    card.remove();
    if (opts.onDismiss) opts.onDismiss();
  });
  head.appendChild(xBtn);
  card.appendChild(head);

  // Prompt
  if (opts.prompt) {
    const p = document.createElement("div");
    p.className = "odec-prompt";
    p.textContent = opts.prompt;
    card.appendChild(p);
  }

  // Options
  const optsDiv = document.createElement("div");
  optsDiv.className = "odec-opts";
  if (opts.options) {
    for (const opt of opts.options) {
      const b = document.createElement("button");
      b.className = "odec-opt"; b.type = "button";
      b.textContent = opt.label || opt.value;
      b.dataset.value = opt.value;
      b.addEventListener("click", () => {
        optsDiv.querySelectorAll(".odec-opt").forEach((el) => el.setAttribute("aria-pressed", "false"));
        b.setAttribute("aria-pressed", "true");
      });
      optsDiv.appendChild(b);
    }
  }
  card.appendChild(optsDiv);

  // Confirm row
  const row = document.createElement("div");
  row.className = "odec-row";
  const confirm = document.createElement("button");
  confirm.className = "odec-confirm" + (opts.risk ? " odec-risk" : "");
  confirm.type = "button";
  confirm.textContent = opts.confirmLabel || "Confirm";
  confirm.disabled = true;
  // Enable confirm when an option is selected
  optsDiv.addEventListener("click", () => {
    const selected = optsDiv.querySelector('.odec-opt[aria-pressed="true"]');
    confirm.disabled = !selected;
  });
  confirm.addEventListener("click", () => {
    const selected = optsDiv.querySelector('.odec-opt[aria-pressed="true"]');
    if (!selected) return;
    confirm.disabled = true;
    if (opts.onConfirm) opts.onConfirm(selected.dataset.value);
    card.classList.add("odec-done");
  });
  row.appendChild(confirm);

  if (opts.note) {
    const note = document.createElement("span");
    note.className = "odec-note";
    note.textContent = opts.note;
    row.appendChild(note);
  }
  card.appendChild(row);

  return card;
}

export { injectCss as ensureDecisionCss };

window.AppKitDecision = {
  createDecision,
};
