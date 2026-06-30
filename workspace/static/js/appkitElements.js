// appkitElements.js — AppKit Elements kit (FR-UIKIT-1).
//
// The Elements kit is CSS-first: all atomic controls (.ow-btn, .ow-field,
// .ow-switch, .ow-check, .ow-radio, .ow-select, .ow-slider) are defined in
// workspace/static/style.css and workspace/static/css/kit-themes.css.
// This file exposes a thin JS helper so call sites can programmatically
// construct kit-conformant DOM nodes without writing boilerplate HTML.
//
// CSS class vocabulary (reference — do not duplicate here):
//   .ow-btn                    — base button (every variant composes this)
//   .ow-btn-secondary          — the default secondary/ghost affordance
//   .ow-btn-prominent          — the primary/CTA button (filled)
//   .ow-btn-icon               — icon-only button (square, no label)
//   .ow-btn-plain              — inline text-link–style button
//   .ow-btn-destructive        — a destructive action (red fill on confirmation)
//   .ow-btn-sm / .ow-btn-lg    — compact / large size modifier
//   .ow-btn-group              — a joined pill-bar of .ow-btn siblings
//   .ow-btn-concentric         — a button nested INSIDE a kit surface (concentric corner radius)
//   .ow-field                  — label + input wrapper (provides the associated-label contract)
//   .ow-switch                 — an iOS-style toggle (checkbox with role=switch)
//   .ow-check                  — a styled checkbox (label + input[type=checkbox])
//   .ow-radio                  — a styled radio (label + input[type=radio])
//   .ow-select                 — a styled <select> wrapper
//   .ow-slider                 — a styled range input

(function () {
  "use strict";

  /**
   * makeBtn(text, variant, opts) — create a kit button element.
   *   text     — button label (string) or null for icon-only
   *   variant  — one of 'secondary' | 'prominent' | 'icon' | 'plain' | 'destructive' (default 'secondary')
   *   opts     — { type, ariaLabel, title, disabled, className, onClick, dataset }
   */
  function makeBtn(text, variant, opts) {
    opts = opts || {};
    var b = document.createElement("button");
    b.type = opts.type || "button";
    b.className = "ow-btn ow-btn-" + (variant || "secondary") +
      (opts.className ? " " + opts.className : "");
    if (text != null) b.textContent = text;
    if (opts.ariaLabel) b.setAttribute("aria-label", opts.ariaLabel);
    if (opts.title) b.title = opts.title;
    if (opts.disabled) b.disabled = true;
    if (opts.dataset) {
      Object.keys(opts.dataset).forEach(function (k) { b.dataset[k] = opts.dataset[k]; });
    }
    if (typeof opts.onClick === "function") b.addEventListener("click", opts.onClick);
    return b;
  }

  /**
   * makeField(id, labelText, inputEl, opts) — wrap an input element in the .ow-field structure.
   *   id        — the input's id (and the label's for= attribute)
   *   labelText — visible label string
   *   inputEl   — an existing <input> / <textarea> / <select> element to wrap
   *   opts      — { hint } where hint is an optional description string
   * Returns the .ow-field wrapper element.
   */
  function makeField(id, labelText, inputEl, opts) {
    opts = opts || {};
    var wrap = document.createElement("div");
    wrap.className = "ow-field";
    var lbl = document.createElement("label");
    lbl.htmlFor = id;
    lbl.textContent = labelText;
    if (id) inputEl.id = id;
    wrap.appendChild(lbl);
    wrap.appendChild(inputEl);
    if (opts.hint) {
      var hint = document.createElement("span");
      hint.className = "ow-field-hint";
      hint.textContent = opts.hint;
      wrap.appendChild(hint);
    }
    return wrap;
  }

  /**
   * makeSwitch(id, labelText, checked, onChange) — create an .ow-switch toggle.
   *   id         — input id
   *   labelText  — visible label
   *   checked    — initial checked state
   *   onChange   — callback(checked: boolean)
   * Returns the .ow-switch wrapper element.
   */
  function makeSwitch(id, labelText, checked, onChange) {
    var wrap = document.createElement("label");
    wrap.className = "ow-switch";
    wrap.htmlFor = id;
    var inp = document.createElement("input");
    inp.type = "checkbox";
    inp.id = id;
    inp.role = "switch";
    inp.setAttribute("role", "switch");
    inp.checked = !!checked;
    if (typeof onChange === "function") {
      inp.addEventListener("change", function () { onChange(inp.checked); });
    }
    var track = document.createElement("span");
    track.className = "ow-switch-track";
    track.setAttribute("aria-hidden", "true");
    var lbl = document.createElement("span");
    lbl.className = "ow-switch-label";
    lbl.textContent = labelText;
    wrap.appendChild(inp);
    wrap.appendChild(track);
    wrap.appendChild(lbl);
    return wrap;
  }

  /**
   * makeCheck(id, labelText, checked, onChange) — create an .ow-check checkbox.
   */
  function makeCheck(id, labelText, checked, onChange) {
    var wrap = document.createElement("label");
    wrap.className = "ow-check";
    wrap.htmlFor = id;
    var inp = document.createElement("input");
    inp.type = "checkbox";
    inp.id = id;
    inp.checked = !!checked;
    if (typeof onChange === "function") {
      inp.addEventListener("change", function () { onChange(inp.checked); });
    }
    var lbl = document.createElement("span");
    lbl.textContent = labelText;
    wrap.appendChild(inp);
    wrap.appendChild(lbl);
    return wrap;
  }

  var AppkitElements = { makeBtn: makeBtn, makeField: makeField, makeSwitch: makeSwitch, makeCheck: makeCheck };

  if (typeof window !== "undefined") window.AppkitElements = AppkitElements;
})();

export default (typeof window !== "undefined" ? window.AppkitElements : null);
export { };
