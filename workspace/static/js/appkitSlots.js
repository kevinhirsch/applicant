/* AppKit Slots — floating panel positioning by slot, never by coordinate.
   Renamed from upstream orwellSlots.js per FR-UIKIT-4.
   One registry owns where panels sit: each slot stacks its panels by measured height. */

"use strict";

const NARROW = window.matchMedia ? window.matchMedia("(max-width: 768px)") : { matches: false, addEventListener() {} };
const REDUCED = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
const GAP = 10;
const TOP_BASE = 52;
const BOTTOM_BASE = 12;

const slots = { "top-right": [], "top-left": [], "bottom-center": [], "bottom-right": [] };
let _user = "";
try { _user = (document.body && document.body.dataset.user) || ""; } catch (_) {}

function offsetKey(key) { return "appkit-slot-offset:" + key + ":" + _user; }

function loadOffset(key) {
  try {
    const o = JSON.parse(localStorage.getItem(offsetKey(key)) || "null");
    if (o && Number.isFinite(o.dx) && Number.isFinite(o.dy)) return o;
  } catch (_) {}
  return null;
}
function saveOffset(key, dx, dy) {
  try { localStorage.setItem(offsetKey(key), JSON.stringify({ dx, dy })); } catch (_) {}
}

function visible(el) {
  return (el.isConnected && el.style.display !== "none" && el.offsetParent !== null)
    || (el.isConnected && getComputedStyle(el).position === "fixed" && getComputedStyle(el).display !== "none");
}

let _restacking = false;
function dragInProgress() {
  for (const list of Object.values(slots)) {
    for (const { el } of list) if (el.classList && el.classList.contains("modal-dragging")) return true;
  }
  return false;
}

function setStyle(el, prop, val) {
  if (el.style[prop] !== val) el.style[prop] = val;
}

function restackNarrowSheets() {
  let cursor = TOP_BASE - 8;
  for (const name of ["top-left", "top-right"]) {
    for (const entry of slots[name]) {
      const el = entry.el;
      if (!visible(el)) continue;
      setStyle(el, "position", "fixed");
      setStyle(el, "left", "0px");
      setStyle(el, "right", "0px");
      setStyle(el, "top", cursor + "px");
      setStyle(el, "bottom", "auto");
      setStyle(el, "transform", "none");
      cursor += (el.offsetHeight || 0) + GAP;
    }
  }
}

function restackSlot(name) {
  if (NARROW.matches) { restackNarrowSheets(); return; }
  if (dragInProgress()) return;
  const list = slots[name];
  const safeT = TOP_BASE, safeB = BOTTOM_BASE;
  let cursor = name.startsWith("top") ? safeT : safeB;
  for (const entry of list) {
    const el = entry.el;
    if (!visible(el)) continue;
    const h = el.offsetHeight || 0;
    const w = el.offsetWidth || 0;
    let top = null, bottom = null;
    if (name.startsWith("top")) { top = cursor; cursor += h + GAP; }
    else { bottom = cursor; cursor += h + GAP; }

    setStyle(el, "position", "fixed");
    const off = entry.key ? loadOffset(entry.key) : null;
    if (off && (off.dx || off.dy)) {
      const baseLeft = name.endsWith("right") ? (window.innerWidth - 14 - w)
        : name.endsWith("left") ? 14
        : (window.innerWidth - w) / 2;
      const baseTop = top !== null ? top : (window.innerHeight - bottom - h);
      const left = Math.max(4, Math.min(window.innerWidth - w - 4, baseLeft + off.dx));
      const topPx = Math.max(4, Math.min(window.innerHeight - Math.min(h, 200) - 4, baseTop + off.dy));
      setStyle(el, "left", left + "px");
      setStyle(el, "top", topPx + "px");
      setStyle(el, "right", "auto");
      setStyle(el, "bottom", "auto");
      setStyle(el, "transform", "none");
    } else {
      setStyle(el, "top", top !== null ? top + "px" : "auto");
      setStyle(el, "bottom", bottom !== null ? bottom + "px" : "auto");
      if (name.endsWith("right")) { setStyle(el, "right", "14px"); setStyle(el, "left", "auto"); setStyle(el, "transform", ""); }
      else if (name.endsWith("left")) { setStyle(el, "left", "14px"); setStyle(el, "right", "auto"); setStyle(el, "transform", ""); }
      else { setStyle(el, "left", "50%"); setStyle(el, "right", "auto"); setStyle(el, "transform", "translateX(-50%)"); }
    }
  }
}

function restackAll() { for (const name of Object.keys(slots)) restackSlot(name); }

function animateIn(el) {
  if (REDUCED.matches) return;
  el.classList.remove("applicant-anim-in");
  void el.offsetWidth;
  el.classList.add("applicant-anim-in");
}

export function register(el, slotName, opts) {
  const o = opts || {};
  if (!slots[slotName]) slotName = "top-right";
  slots[slotName].push({ el, key: o.key || null, draggable: !!o.draggable });
  el.classList.add("applicant-slotted");
  try {
    let _wasHidden = el.style.display === "none";
    new MutationObserver((muts) => {
      for (const m of muts) {
        if (m.attributeName === "style") {
          if (_restacking) return;
          const hidden = el.style.display === "none";
          if (!hidden && _wasHidden) animateIn(el);
          _wasHidden = hidden;
          if (el.classList.contains("modal-dragging")) return;
          _restacking = true;
          try { restackAll(); } finally { _restacking = false; }
          return;
        }
      }
    }).observe(el, { attributes: true, attributeFilter: ["style"] });
  } catch (_) {}
  try { new ResizeObserver(() => restackSlot(slotName)).observe(el); } catch (_) {}
  restackSlot(slotName);
  return {
    saveDragOffset(rect) {
      if (!o.key || !visible(el)) return;
      _restacking = true;
      try {
        try { localStorage.removeItem(offsetKey(o.key)); } catch (_) {}
        restackSlot(slotName);
        const base = el.getBoundingClientRect();
        saveOffset(o.key, rect.left - base.left, rect.top - base.top);
        restackSlot(slotName);
      } finally { _restacking = false; }
    },
    restack() { restackSlot(slotName); },
  };
}

export { restackAll };

window.addEventListener("resize", restackAll);
NARROW.addEventListener("change", () => {
  for (const list of Object.values(slots)) for (const { el } of list) {
    el.style.top = ""; el.style.bottom = ""; el.style.left = ""; el.style.right = ""; el.style.transform = "";
  }
  restackAll();
});

window.AppKitSlots = { register, restackAll };
