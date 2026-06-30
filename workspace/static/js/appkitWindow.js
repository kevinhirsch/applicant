/* AppKit Window — the window kit (FR-UIKIT F3).
   Renamed from upstream orwellWindow.js per FR-UIKIT-4.
   One base class + one CSS family (.ow-window / .ow-titlebar / .ow-controls / .ow-body)
   that every panel, modal, and popover composes — replacing the per-panel reimplementations.
   Reconciles with existing modalManager.js, windowDrag.js, modalSnap.js per FR-UIKIT-3. */

"use strict";

import * as Modals from "./modalManager.js";
import { makeWindowDraggable } from "./windowDrag.js";

const Z_BASE = 500;
const Z_CEIL = 980;
let _zTop = Z_BASE;
const _stack = [];

const REDUCED = () =>
  !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

function ensureCss() {
  if (document.getElementById("appkit-window-css")) return;
  const st = document.createElement("style");
  st.id = "appkit-window-css";
  st.textContent = `
    .ow-window {
      position: fixed; z-index: ${Z_BASE};
      min-width: 180px; max-width: 64vw;
      background: var(--win-bg, var(--panel, #111)); color: var(--fg, #9cdef2);
      border: 1px solid var(--win-border, var(--border, #355a66));
      border-radius: var(--win-radius, 10px);
      box-shadow: var(--win-shadow, 0 8px 32px rgba(0,0,0,.45));
      font-size: var(--fs-sm, .8rem); line-height: 1.45;
    }
    .ow-window.ow-focused {
      border-color: color-mix(in srgb, var(--accent, #e06c75) 65%, var(--win-border, var(--border, #355a66)));
      box-shadow: 0 12px 36px rgba(0,0,0,.5);
    }
    .ow-titlebar {
      display: flex; align-items: center; gap: .4rem;
      padding: .45rem .55rem .35rem .7rem;
      cursor: move; user-select: none; -webkit-user-select: none;
      border-radius: var(--win-radius, 10px) var(--win-radius, 10px) 0 0;
    }
    .ow-titlebar:focus-visible { outline: 2px solid var(--accent, #e06c75); outline-offset: -2px; }
    .ow-title {
      flex: 1; min-width: 0;
      font-size: var(--win-titlebar-fs, 1rem);
      font-weight: var(--win-titlebar-weight, 600);
      letter-spacing: var(--win-titlebar-ls, -0.03em);
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .ow-controls { display: flex; gap: 2px; flex-shrink: 0; }
    .ow-dismiss {
      min-width: 24px; min-height: 24px; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
      border: none; background: none; color: inherit; cursor: pointer;
      opacity: .6; border-radius: 6px; font: inherit; font-size: var(--fs-sm, .8rem);
    }
    .ow-controls button {
      min-width: 24px; min-height: 24px; padding: 0;
      display: inline-flex; align-items: center; justify-content: center;
      border: none; background: none; color: inherit; cursor: pointer;
      opacity: .6; border-radius: 6px; font: inherit; font-size: var(--fs-sm, .8rem);
    }
    .ow-controls button:hover, .ow-controls button:focus-visible,
    .ow-dismiss:hover, .ow-dismiss:focus-visible { opacity: 1; background: rgba(255,255,255,.08); }
    .ow-body { padding: .4rem .7rem .6rem; overflow: auto; max-height: min(70vh, 560px); }
    @keyframes ow-open { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: scale(1); } }
    .ow-anim-open { animation: ow-open .18s ease-out; }
    .ow-anim-fly { transition: transform .26s cubic-bezier(.45,.05,.55,.95), opacity .24s ease-in; }
    @media (prefers-reduced-motion: reduce) {
      .ow-anim-open { animation: none; }
      .ow-anim-fly { transition: none; }
    }
    /* Modal/dialog role styling for a11y */
    .ow-window[role="dialog"] { outline: none; }
    .ow-window[aria-modal="true"] { outline: 2px solid var(--accent, #e06c75); }
  `;
  document.head.appendChild(st);
}

function clampPos(left, top, w, h) {
  const margin = 4;
  return {
    left: Math.max(margin, Math.min(window.innerWidth - Math.max(w, 60) - margin, left)),
    top: Math.max(margin, Math.min(window.innerHeight - Math.min(h, 200) - margin, top)),
  };
}

function parkedKey(id) {
  return "applicant-win-parked:" + id + ":" + ((document.body && document.body.dataset.user) || "");
}
function loadParked(id) {
  try { return localStorage.getItem(parkedKey(id)) === "1"; } catch (_) { return false; }
}
function saveParked(id, on) {
  try {
    if (on) localStorage.setItem(parkedKey(id), "1");
    else localStorage.removeItem(parkedKey(id));
  } catch (_) {}
}

export class AppKitWindow {
  /**
   * opts: { id, title, icon, slot='top-right', slotKey=null, role='dialog',
   *         draggable=true, minimizable=true, closable=true, resizable=false,
   *         modal=false, content (Node|string), focus=false, onClose, onMinimize, onRestore }
   */
  constructor(opts) {
    this.o = Object.assign(
      { slot: "top-right", role: "dialog", draggable: true, minimizable: true,
        closable: true, resizable: false, modal: false, focus: false },
      opts
    );
    if (!this.o.id || !this.o.title) throw new Error("AppKitWindow needs id + title");
    this.ac = new AbortController();
    this.opener = null;
    this.el = null;
    this.titlebar = null;
    this.body = null;
    this._slot = null;
    this._displayBeforeMin = "";
  }

  _build() {
    ensureCss();
    const el = document.createElement("div");
    el.id = this.o.id;
    el.className = "ow-window";
    el.setAttribute("data-ow-window", "");
    el.setAttribute("role", this.o.modal ? "dialog" : (this.o.role || "complementary"));
    el.setAttribute("aria-label", this.o.title);
    if (this.o.modal) {
      el.setAttribute("aria-modal", "true");
    }

    const tb = document.createElement("div");
    tb.className = "ow-titlebar";
    tb.setAttribute("tabindex", "0");
    tb.title = this.o.draggable ? "Drag to move · arrows to nudge" : "";

    const title = document.createElement("span");
    title.className = "ow-title";
    title.textContent = this.o.title;

    const controls = document.createElement("div");
    controls.className = "ow-controls";

    if (this.o.minimizable) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ow-min";
      b.setAttribute("aria-label", "Minimize"); b.title = "Minimize";
      b.textContent = "–";
      b.addEventListener("click", (e) => { e.stopPropagation(); this.minimize(); }, { signal: this.ac.signal });
      controls.appendChild(b);
    }
    if (this.o.closable) {
      const b = document.createElement("button");
      b.type = "button"; b.className = "ow-close";
      b.setAttribute("aria-label", "Close"); b.title = "Close";
      b.textContent = "×";
      b.addEventListener("click", (e) => { e.stopPropagation(); this.close(); }, { signal: this.ac.signal });
      controls.appendChild(b);
    }

    tb.appendChild(title);
    tb.appendChild(controls);

    const body = document.createElement("div");
    body.className = "ow-body";
    if (this.o.content instanceof Node) body.appendChild(this.o.content);
    else if (typeof this.o.content === "string") body.innerHTML = this.o.content;

    el.appendChild(tb);
    el.appendChild(body);

    this.el = el;
    this.titlebar = tb;
    this.body = body;

    // Click-to-front
    el.addEventListener("pointerdown", () => this.raise(), { capture: true, signal: this.ac.signal });

    // Keyboard move/resize on titlebar
    tb.addEventListener("keydown", (e) => this._onTitlebarKey(e), { signal: this.ac.signal });

    // Focus trap for modal dialogs
    if (this.o.modal) {
      el.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.preventDefault(); this.close(); }
      }, { signal: this.ac.signal });
    }

    if (this.o.draggable) {
      makeWindowDraggable(el, {
        content: el, header: tb,
        enableDock: false, enableFullscreen: false, enableResize: false,
        skipSelector: "button, input, select, textarea",
        onDragEnd: ({ rect }) => this._persist(rect),
      });
    }

    return el;
  }

  _persist(rect) {
    const c = clampPos(rect.left, rect.top, rect.width, rect.height);
    if (c.left !== rect.left || c.top !== rect.top) {
      this.el.style.left = c.left + "px"; this.el.style.top = c.top + "px";
      rect = this.el.getBoundingClientRect();
    }
    if (this._slot) this._slot.saveDragOffset(rect);
  }

  _onTitlebarKey(e) {
    const STEP = 16;
    const dirs = {
      ArrowLeft: [-STEP, 0], ArrowRight: [STEP, 0],
      ArrowUp: [0, -STEP], ArrowDown: [0, STEP],
    };
    if (e.key === "Home" && this._slot && this.o.slotKey) {
      e.preventDefault();
      try { localStorage.removeItem("applicant-slot-offset:" + this.o.slotKey + ":" + ((document.body && document.body.dataset.user) || "")); } catch (_) {}
      this._slot.restack();
      return;
    }
    const d = dirs[e.key];
    if (!d) return;
    e.preventDefault();
    const r = this.el.getBoundingClientRect();
    if (e.shiftKey && this.o.resizable) {
      const w = Math.max(200, Math.min(window.innerWidth - 8, r.width + d[0]));
      const h = Math.max(120, Math.min(window.innerHeight - 8, r.height + d[1]));
      this.el.style.width = w + "px"; this.el.style.height = h + "px";
      return;
    }
    const c = clampPos(r.left + d[0], r.top + d[1], r.width, r.height);
    this.el.style.left = c.left + "px"; this.el.style.top = c.top + "px";
    this.el.style.right = "auto"; this.el.style.bottom = "auto"; this.el.style.transform = "none";
    this._persist(this.el.getBoundingClientRect());
  }

  open(opener) {
    if (this.el && this.el.isConnected) { this.restore(); return this; }
    this.opener = opener || document.activeElement || null;
    const el = this._build();
    document.body.appendChild(el);

    // Register with slot system if available
    if (window.AppKitSlots) {
      this._slot = window.AppKitSlots.register(el, this.o.slot,
        { key: this.o.slotKey || null, draggable: this.o.draggable });
    } else if (window.ApplicantSlots) {
      this._slot = window.ApplicantSlots.register(el, this.o.slot,
        { key: this.o.slotKey || null, draggable: this.o.draggable });
    }

    Modals.register(this.o.id, {
      label: this.o.title, icon: this.o.icon || "",
      restoreFn: () => this._afterDockRestore(),
      closeFn: () => this._teardown(),
    });

    // Restore parked state across refresh (G5/G16)
    if (this.o.minimizable && loadParked(this.o.id)) {
      this._displayBeforeMin = el.style.display;
      Modals.minimize(this.o.id);
      el.style.display = "none";
      return this;
    }

    if (!REDUCED()) { el.classList.add("ow-anim-open"); setTimeout(() => el.classList.remove("ow-anim-open"), 220); }
    this.raise();
    if (this.o.focus) {
      // Focus the first focusable element or the titlebar
      const firstFocusable = el.querySelector("button, input, select, textarea, [tabindex]:not([tabindex='-1'])");
      if (firstFocusable) firstFocusable.focus();
      else this.titlebar.focus();
    }
    return this;
  }

  raise() {
    if (!this.el) return;
    if (_zTop >= Z_CEIL) {
      _zTop = Z_BASE;
      for (const w of _stack) { w.el.style.zIndex = String(++_zTop); }
    }
    this.el.style.zIndex = String(++_zTop);
    const i = _stack.indexOf(this);
    if (i !== -1) _stack.splice(i, 1);
    _stack.push(this);
    for (const w of _stack) w.el && w.el.classList.toggle("ow-focused", w === this);
  }

  minimize() {
    if (!this.el) return;
    saveParked(this.o.id, true);
    const i = _stack.indexOf(this);
    if (i !== -1) _stack.splice(i, 1);
    this.el.classList.remove("ow-focused");
    this._displayBeforeMin = this.el.style.display;
    const done = () => {
      this.el.classList.remove("ow-anim-fly");
      this.el.style.transform = ""; this.el.style.opacity = "";
      Modals.minimize(this.o.id);
      this.el.style.display = "none";
      try { this.o.onMinimize && this.o.onMinimize(); } catch (_) {}
    };
    if (REDUCED()) { done(); return; }
    // Fly-out toward the dock
    const dock = document.getElementById("minimized-dock");
    const from = this.el.getBoundingClientRect();
    let to;
    if (dock && dock.getBoundingClientRect().height > 0) to = dock.getBoundingClientRect();
    else to = { left: 16, top: window.innerHeight - 48, width: 32, height: 24 };
    const dx = (to.left + (to.width || 32) / 2) - (from.left + from.width / 2);
    const dy = (to.top + (to.height || 24) / 2) - (from.top + from.height / 2);
    this.el.classList.add("ow-anim-fly");
    requestAnimationFrame(() => {
      this.el.style.transform = `translate(${dx}px, ${dy}px) scale(.12)`;
      this.el.style.opacity = "0";
      setTimeout(done, 270);
    });
  }

  _afterDockRestore() {
    this.el.style.display = this._displayBeforeMin || "";
    if (getComputedStyle(this.el).display === "none") this.el.style.display = "block";
    saveParked(this.o.id, false);
    this.el.style.transform = ""; this.el.style.opacity = "";
    if (this._slot) this._slot.restack();
    this.raise();
    try { this.o.onRestore && this.o.onRestore(); } catch (_) {}
  }

  restore() { Modals.restore(this.o.id); }

  isMinimized() { return Modals.isMinimized(this.o.id); }

  close() {
    if (!this.el) return;
    const finish = () => Modals.close(this.o.id);
    if (REDUCED()) { finish(); return; }
    this.el.classList.add("ow-anim-fly");
    requestAnimationFrame(() => {
      this.el.style.transform = "scale(.9)";
      this.el.style.opacity = "0";
      setTimeout(finish, 180);
    });
  }

  _teardown() {
    const i = _stack.indexOf(this);
    if (i !== -1) _stack.splice(i, 1);
    saveParked(this.o.id, false);
    this.ac.abort();
    const opener = this.opener;
    if (this.el) { this.el.remove(); this.el = null; }
    try { this.o.onClose && this.o.onClose(); } catch (_) {}
    // Focus return
    if (opener && opener.isConnected && typeof opener.focus === "function") {
      try { opener.focus(); } catch (_) {}
    }
  }

  destroy() { this._teardown(); Modals.unregister(this.o.id); }
}

// Escape participation: ui.js's single arbiter calls this.
export function dismissTop() {
  for (let i = _stack.length - 1; i >= 0; i--) {
    const w = _stack[i];
    if (!w.el || !w.el.isConnected || w.el.style.display === "none") { _stack.splice(i, 1); continue; }
    if (w.o.minimizable) w.minimize(); else w.close();
    return true;
  }
  return false;
}

export function stackIds() { return _stack.map((w) => w.o.id); }

// Inject CSS at load
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", ensureCss, { once: true });
} else {
  ensureCss();
}

window.AppKitWindow = {
  create: (opts) => new AppKitWindow(opts),
  dismissTop,
  stackIds,
};
