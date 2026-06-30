/* AppKit Elements — atomic controls: button, field, checkbox, radio, switch, select, slider.
   Renamed from upstream orwellElements.js per FR-UIKIT-4.
   Provides the .ow-btn* / .ow-field / .ow-check / .ow-radio / .ow-switch / .ow-select / .ow-slider
   component primitives as a JS module with CSS injection. */

"use strict";

let _cssInjected = false;

function injectCss() {
  if (_cssInjected) return;
  _cssInjected = true;
  const st = document.createElement("style");
  st.id = "appkit-elements-css";
  st.textContent = `
    /* ---- Buttons (.ow-btn*) -------------------------------------------- */
    .ow-btn {
      display: inline-flex; align-items: center; justify-content: center; gap: .35rem;
      border: 1px solid var(--border, #355a66); border-radius: 6px;
      background: transparent; color: var(--fg, #9cdef2);
      font: inherit; font-size: .8rem; line-height: 1.4;
      cursor: pointer; white-space: nowrap;
      padding: .35rem .7rem; min-height: 28px;
      transition: background .12s ease, border-color .12s ease, opacity .12s ease;
    }
    .ow-btn:hover { background: color-mix(in srgb, var(--accent, #e06c75) 12%, transparent); }
    .ow-btn:focus-visible { outline: 2px solid var(--accent, #e06c75); outline-offset: 2px; }
    .ow-btn:disabled { opacity: .4; cursor: not-allowed; }

    .ow-btn-primary { background: var(--accent, #e06c75); color: #fff; border-color: var(--accent, #e06c75); }
    .ow-btn-primary:hover { filter: brightness(1.1); }
    .ow-btn-secondary { border-color: var(--accent, #e06c75); color: var(--accent, #e06c75); }
    .ow-btn-secondary:hover { background: color-mix(in srgb, var(--accent, #e06c75) 12%, transparent); }
    .ow-btn-plain { border: none; background: none; padding: .2rem .4rem; }
    .ow-btn-destructive { border-color: var(--color-error, #ff4444); color: var(--color-error, #ff4444); }
    .ow-btn-destructive:hover { background: color-mix(in srgb, var(--color-error, #ff4444) 12%, transparent); }
    .ow-btn-icon { padding: .3rem; min-width: 28px; min-height: 28px; border: none; }
    .ow-btn-sm { font-size: .72rem; padding: .2rem .5rem; min-height: 22px; }
    .ow-btn-lg { font-size: .9rem; padding: .45rem .9rem; min-height: 34px; }
    .ow-btn-xl { font-size: 1rem; padding: .55rem 1.1rem; min-height: 40px; }
    .ow-btn-group { display: inline-flex; }
    .ow-btn-group .ow-btn:not(:first-child) { border-top-left-radius: 0; border-bottom-left-radius: 0; }
    .ow-btn-group .ow-btn:not(:last-child) { border-top-right-radius: 0; border-bottom-right-radius: 0; border-right-width: 0; }
    .ow-btn-concentric { border-radius: 50%; width: 32px; height: 32px; padding: 0; }

    /* ---- Text field (.ow-field) ---------------------------------------- */
    .ow-field {
      display: block; width: 100%; box-sizing: border-box;
      padding: .35rem .55rem; border: 1px solid var(--border, #355a66); border-radius: 6px;
      background: var(--bg, #282c34); color: var(--fg, #9cdef2);
      font: inherit; font-size: .8rem; line-height: 1.4;
      transition: border-color .12s ease;
    }
    .ow-field:focus { outline: none; border-color: var(--accent, #e06c75); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent, #e06c75) 25%, transparent); }
    .ow-field.is-invalid { border-color: var(--color-error, #ff4444); }
    .ow-field::placeholder { opacity: .45; }

    /* ---- Checkbox (.ow-check) ------------------------------------------ */
    .ow-check {
      display: inline-flex; align-items: center; gap: .4rem;
      cursor: pointer; font-size: .8rem;
    }
    .ow-check input[type="checkbox"] {
      appearance: none; -webkit-appearance: none; width: 16px; height: 16px;
      border: 1px solid var(--border, #355a66); border-radius: 3px;
      background: transparent; cursor: pointer; flex-shrink: 0;
      display: inline-flex; align-items: center; justify-content: center;
      transition: background .12s ease, border-color .12s ease;
    }
    .ow-check input[type="checkbox"]:checked {
      background: var(--accent, #e06c75); border-color: var(--accent, #e06c75);
    }
    .ow-check input[type="checkbox"]:checked::after {
      content: "✓"; color: #fff; font-size: 12px; line-height: 1;
    }
    .ow-check input[type="checkbox"]:focus-visible { outline: 2px solid var(--accent, #e06c75); outline-offset: 2px; }

    /* ---- Radio (.ow-radio) --------------------------------------------- */
    .ow-radio {
      display: inline-flex; align-items: center; gap: .4rem;
      cursor: pointer; font-size: .8rem;
    }
    .ow-radio input[type="radio"] {
      appearance: none; -webkit-appearance: none; width: 16px; height: 16px;
      border: 1px solid var(--border, #355a66); border-radius: 50%;
      background: transparent; cursor: pointer; flex-shrink: 0;
      transition: background .12s ease, border-color .12s ease;
    }
    .ow-radio input[type="radio"]:checked {
      background: var(--accent, #e06c75); border-color: var(--accent, #e06c75);
      box-shadow: inset 0 0 0 3px var(--bg, #282c34);
    }
    .ow-radio input[type="radio"]:focus-visible { outline: 2px solid var(--accent, #e06c75); outline-offset: 2px; }

    /* ---- Switch (.ow-switch) ------------------------------------------- */
    .ow-switch {
      display: inline-flex; align-items: center; gap: .5rem;
      cursor: pointer; font-size: .8rem;
    }
    .ow-switch-track {
      position: relative; width: 36px; height: 20px;
      border-radius: 10px; background: var(--border, #355a66);
      transition: background .15s ease; flex-shrink: 0;
    }
    .ow-switch-track::after {
      content: ""; position: absolute; top: 2px; left: 2px;
      width: 16px; height: 16px; border-radius: 50%;
      background: var(--fg, #9cdef2); transition: transform .15s ease;
    }
    .ow-switch input[type="checkbox"]:checked + .ow-switch-track { background: var(--accent, #e06c75); }
    .ow-switch input[type="checkbox"]:checked + .ow-switch-track::after { transform: translateX(16px); }
    .ow-switch input[type="checkbox"] { position: absolute; opacity: 0; width: 0; height: 0; }
    .ow-switch input[type="checkbox"]:focus-visible + .ow-switch-track { outline: 2px solid var(--accent, #e06c75); outline-offset: 2px; }

    /* ---- Select (.ow-select) ------------------------------------------- */
    .ow-select {
      display: inline-block; position: relative;
    }
    .ow-select select {
      appearance: none; -webkit-appearance: none;
      padding: .3rem 1.6rem .3rem .5rem; border: 1px solid var(--border, #355a66); border-radius: 6px;
      background: var(--bg, #282c34); color: var(--fg, #9cdef2);
      font: inherit; font-size: .8rem; cursor: pointer; min-width: 100px;
    }
    .ow-select select:focus { outline: none; border-color: var(--accent, #e06c75); box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent, #e06c75) 25%, transparent); }
    .ow-select::after {
      content: "▾"; position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
      pointer-events: none; opacity: .6; font-size: .7rem;
    }

    /* ---- Slider (.ow-slider) ------------------------------------------- */
    .ow-slider {
      display: flex; align-items: center; gap: .5rem;
    }
    .ow-slider input[type="range"] {
      appearance: none; -webkit-appearance: none;
      width: 120px; height: 4px; border-radius: 2px;
      background: var(--border, #355a66); outline: none; cursor: pointer;
    }
    .ow-slider input[type="range"]::-webkit-slider-thumb {
      appearance: none; -webkit-appearance: none;
      width: 16px; height: 16px; border-radius: 50%;
      background: var(--accent, #e06c75); cursor: pointer;
      border: 2px solid var(--bg, #282c34);
    }
    .ow-slider input[type="range"]::-moz-range-thumb {
      width: 16px; height: 16px; border-radius: 50%;
      background: var(--accent, #e06c75); cursor: pointer;
      border: 2px solid var(--bg, #282c34);
    }
    .ow-slider input[type="range"]:focus-visible { outline: 2px solid var(--accent, #e06c75); outline-offset: 2px; }
  `;
  document.head.appendChild(st);
}

/**
 * Create an ow-btn element.
 * @param {string} label - Button label
 * @param {object} opts - { variant, size, disabled, icon, title, ariaLabel }
 * @returns {HTMLButtonElement}
 */
export function createButton(label, opts = {}) {
  injectCss();
  const b = document.createElement("button");
  b.type = "button";
  b.className = "ow-btn";
  if (opts.variant) b.classList.add("ow-btn-" + opts.variant);
  if (opts.size) b.classList.add("ow-btn-" + opts.size);
  if (opts.disabled) b.disabled = true;
  if (opts.icon) b.innerHTML = `<span style="display:inline-flex;align-items:center;gap:4px">${opts.icon}<span>${label}</span></span>`;
  else b.textContent = label;
  if (opts.title) b.title = opts.title;
  if (opts.ariaLabel) b.setAttribute("aria-label", opts.ariaLabel);
  return b;
}

/**
 * Create an ow-field input element.
 * @param {object} opts - { type, placeholder, value, invalid, ariaLabel }
 * @returns {HTMLInputElement}
 */
export function createField(opts = {}) {
  injectCss();
  const el = document.createElement("input");
  el.className = "ow-field";
  el.type = opts.type || "text";
  if (opts.placeholder) el.placeholder = opts.placeholder;
  if (opts.value != null) el.value = opts.value;
  if (opts.invalid) el.classList.add("is-invalid");
  if (opts.ariaLabel) el.setAttribute("aria-label", opts.ariaLabel);
  return el;
}

/**
 * Create an ow-switch toggle.
 * @param {boolean} checked - Initial state
 * @param {Function} onChange - Change handler
 * @returns {HTMLLabelElement}
 */
export function createSwitch(checked, onChange) {
  injectCss();
  const label = document.createElement("label");
  label.className = "ow-switch";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = !!checked;
  input.addEventListener("change", () => { if (onChange) onChange(input.checked); });
  const track = document.createElement("span");
  track.className = "ow-switch-track";
  label.appendChild(input);
  label.appendChild(track);
  return label;
}

/**
 * Create an ow-select wrapper.
 * @param {Array<{value,label}>} options
 * @param {string} selected - Selected value
 * @param {Function} onChange - Change handler
 * @returns {HTMLSpanElement}
 */
export function createSelect(options, selected, onChange) {
  injectCss();
  const wrapper = document.createElement("span");
  wrapper.className = "ow-select";
  const sel = document.createElement("select");
  for (const opt of options) {
    const o = document.createElement("option");
    o.value = opt.value;
    o.textContent = opt.label;
    if (opt.value === selected) o.selected = true;
    sel.appendChild(o);
  }
  sel.addEventListener("change", () => { if (onChange) onChange(sel.value); });
  wrapper.appendChild(sel);
  return wrapper;
}

// Export the CSS injector so consumers can ensure styles are present.
export { injectCss as ensureElementsCss };

window.AppKitElements = {
  createButton,
  createField,
  createSwitch,
  createSelect,
  ensureElementsCss: injectCss,
};
