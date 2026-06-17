// Applicant anchor slots — floating panels position by SLOT, never by coordinate
// (E91/S11; the Stream-S mechanism, part 2). One registry owns where game
// panels sit: each slot stacks its panels by MEASURED height (top slots stack
// down, bottom slots stack up), with safe-area insets, so no panel can encode
// assumptions about another's size — the D2 collision rule becomes structural.
//
// Drag (where a panel allows it) persists an OFFSET-FROM-SLOT, clamped to the
// viewport at restore (S11: a position saved at 2560px can't strand the panel
// off-screen at 1366px) and keyed per user+game (E71). On narrow viewports the
// slot engine stands down — the panels' shared sheet rules own the layout.
//
// E97 rides here too: one animation contract for every registered panel —
// fade+scale on open, the reverse on close — honoring prefers-reduced-motion.
(function () {
  "use strict";

  const NARROW = window.matchMedia ? window.matchMedia("(max-width: 768px)") : { matches: false, addEventListener() {} };
  const REDUCED = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : { matches: false };
  const GAP = 10;
  const TOP_BASE = 52;     // below the app header
  const BOTTOM_BASE = 12;  // above the composer's inset

  // slot → [{ el, key, draggable }]
  const slots = { "top-right": [], "top-left": [], "bottom-center": [], "bottom-right": [] };
  let _user = "";
  try { _user = (document.body && document.body.dataset.user) || ""; } catch (_) {}

  function offsetKey(key) { return "applicant-slot-offset:" + key + ":" + _user; }

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
    return el.isConnected && el.style.display !== "none" && el.offsetParent !== null
      || (el.isConnected && getComputedStyle(el).position === "fixed" && getComputedStyle(el).display !== "none");
  }

  // F2 (DWE audit): the restack must never fight a live drag. windowDrag moves
  // a panel by writing style.left/top per pointermove; the style observer below
  // used to restack on EVERY write, snapping the panel straight back to its
  // slot base — drag was dead and every saved offset was (0,0). While a
  // registered panel carries `modal-dragging` (windowDrag sets it for the whole
  // gesture), restacks stand down; the drag-end save then records the REAL drop
  // rect and the next restack applies it clamped (S11 unchanged).
  let _restacking = false;
  function dragInProgress() {
    for (const list of Object.values(slots)) {
      for (const { el } of list) if (el.classList && el.classList.contains("modal-dragging")) return true;
    }
    return false;
  }

  // Write a style prop only when the value actually changes. Restacks run off a
  // style MutationObserver, so every write must be IDEMPOTENT — a value that
  // ping-pongs between passes (the old base-then-offset two-phase write flipped
  // `left` auto→px every cycle once a real offset existed) re-queues mutation
  // records forever and busy-loops the page (F2 follow-up).
  function setStyle(el, prop, val) {
    if (el.style[prop] !== val) el.style[prop] = val;
  }

  // F3 (DWE audit / F-2 wave 1): the narrow tier is a SHEET HOST, not a
  // stand-down. Both top-slot panels used to pin themselves to top:44px with
  // per-panel !important CSS — with two visible (a finale staging while an
  // approach is live) they overlapped and occluded each other's controls.
  // Now the slot engine stacks every visible top-slot panel as a full-width
  // sheet by MEASURED height (the same rule it applies on desktop), one
  // column across both top slots; bottom slots keep their own narrow CSS.
  function restackNarrowSheets() {
    let cursor = TOP_BASE - 8; // sheets sit flush under the app header
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

  // Stack one slot: measured heights, gap, safe-area; the final position —
  // slot base PLUS the persisted drag offset, clamped (S11/E91) — is computed
  // arithmetically and written ONCE, never via an intermediate base write.
  function restackSlot(name) {
    if (NARROW.matches) { restackNarrowSheets(); return; } // F3: the sheet host owns narrow
    if (dragInProgress()) return; // F2: the gesture owns the position until drop
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
        // Derive the base coordinates numerically — no intermediate writes.
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
        // base position (the slot's anchor)
        setStyle(el, "top", top !== null ? top + "px" : "auto");
        setStyle(el, "bottom", bottom !== null ? bottom + "px" : "auto");
        if (name.endsWith("right")) { setStyle(el, "right", "14px"); setStyle(el, "left", "auto"); setStyle(el, "transform", ""); }
        else if (name.endsWith("left")) { setStyle(el, "left", "14px"); setStyle(el, "right", "auto"); setStyle(el, "transform", ""); }
        else { setStyle(el, "left", "50%"); setStyle(el, "right", "auto"); setStyle(el, "transform", "translateX(-50%)"); }
      }
    }
  }

  function restackAll() { for (const name of Object.keys(slots)) restackSlot(name); }

  // E97: the shared open/close animation — visibility flips animate; reduced
  // motion disables (the class is inert under the media query in tokens css).
  function animateIn(el) {
    if (REDUCED.matches) return;
    el.classList.remove("applicant-anim-in");
    void el.offsetWidth; // restart
    el.classList.add("applicant-anim-in");
  }

  function register(el, slotName, opts) {
    const o = opts || {};
    if (!slots[slotName]) slotName = "top-right";
    slots[slotName].push({ el, key: o.key || null, draggable: !!o.draggable });
    el.classList.add("applicant-slotted");
    // Re-stack whenever this panel shows/hides or resizes — but never re-enter
    // off our own restack writes, and never while a drag owns the position (F2).
    try {
      let _wasHidden = el.style.display === "none";
      new MutationObserver((muts) => {
        for (const m of muts) {
          if (m.attributeName === "style") {
            if (_restacking) return;
            const hidden = el.style.display === "none";
            if (!hidden && _wasHidden) animateIn(el); // animate on reveal, not on every write
            _wasHidden = hidden;
            if (el.classList.contains("modal-dragging")) return; // F2: drag in progress
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
      /** Record a drag-end as an offset from the slot base (never while hidden). */
      saveDragOffset(rect) {
        if (!o.key || !visible(el)) return;
        // Re-derive the base by restacking with no offset, then diff. The whole
        // dance runs under the reentrancy guard so the style observer stays
        // quiet until the final clamped position is applied (F2).
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

  window.addEventListener("resize", restackAll);
  NARROW.addEventListener("change", () => {
    // Crossing the breakpoint re-lays out under the new tier's rules — the
    // sheet host on narrow (F3), slot anchors + offsets on wide.
    for (const list of Object.values(slots)) for (const { el } of list) {
      el.style.top = ""; el.style.bottom = ""; el.style.left = ""; el.style.right = ""; el.style.transform = "";
    }
    restackAll();
  });

  window.ApplicantSlots = { register, restackAll };
})();
