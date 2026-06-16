// OrwellWindow — THE window kit (Lane F / F-1; DWE audit Phase 2).
//
// One base class + one CSS family (.ow-window / .ow-titlebar / .ow-controls /
// .ow-body + state modifiers) that every panel, modal, and popover composes —
// replacing the per-panel reimplementations the 2026-06-11 DWE audit censused
// (3 drag engines, 7 geometry-key schemes, 6 chrome builders, 5+ Escape paths,
// 2 z escalators). The kit OWNS, in one place:
//
//   • registration: OrwellSlots (placement) + modalManager (minimize/dock chip)
//   • drag (windowDrag) with an EXPLICIT clamp — never trust cursor physics
//   • one z-authority for the window band (modals stay above; banner above all)
//     + click-to-front + a visible focused state (audit F9)
//   • minimize-to-dock with the ruling-#19 fly-out toward the dock and a
//     fly-away on close; open keeps the E97 fade+scale; prefers-reduced-motion
//     strips ALL of it (audit F4)
//   • ONE geometry-persistence scheme: the slot offset, clamped at restore
//     (S11/E91) — kit windows never mint their own position keys (audit F5)
//   • focus management: focus-return to the opener on close (audit F8),
//     keyboard move on the titlebar — arrows move, Shift+arrows resize where
//     enabled, Home re-docks to the slot base (audit F10)
//   • Escape participation through ui.js's single arbiter (audit F7): menus
//     dismiss first, then the top kit window parks/closes, then modals
//   • teardown: one AbortController; destroy() leaves no listeners, no node
//
// Migration waves (Lane F / F-2) move each existing surface onto this class
// and DELETE its bespoke code in the same PR. New windows MUST compose the kit
// (the F-3 ratchet pins it).
import * as Modals from './modalManager.js';
import { makeWindowDraggable } from './windowDrag.js';

const Z_BASE = 500;          // the window band: above the legacy panel stamps
const Z_CEIL = 980;          //   (modalManager's 300s), below modals (1000+)
let _zTop = Z_BASE;
const _stack = [];           // open, un-minimized kit windows, bottom → top

const REDUCED = () =>
  !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);

// ── the one CSS family ────────────────────────────────────────────────────
// The window FRAME (bg / border / radius / shadow) and the titlebar TYPE
// (size / weight / tracking) come from the shared --win-* tokens defined
// once in style.css :root (Lane G4) — the SAME tokens the legacy modal
// family (.modal-content / .modal-header h4) consumes, so kit windows and
// the settings/theme/tool modals paint one visual language and per-theme
// overrides (the 0052 house presets, the frost layer) hit both families at
// once. The fallbacks below only cover style.css not having loaded. The
// titlebar COLOR stays var(--fg) by design — see the :root token note
// (the modal family's var(--red) header fails AA on some palettes).
function ensureCss() {
  if (document.getElementById('ow-window-css')) return;
  const st = document.createElement('style');
  st.id = 'ow-window-css';
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
    /* .ow-dismiss: non-window dismissible surfaces (strips, banners, panels —
       ruling-#3/#4-class chrome) adopt the SAME control affordance without
       becoming windows (audit F6 tail). */
    .ow-controls button, .ow-dismiss {
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
  `;
  document.head.appendChild(st);
}

// Explicit viewport clamp (audit note on norm c: never rely on cursor physics).
function clampPos(left, top, w, h) {
  const margin = 4;
  return {
    left: Math.max(margin, Math.min(window.innerWidth - Math.max(w, 60) - margin, left)),
    top: Math.max(margin, Math.min(window.innerHeight - Math.min(h, 200) - margin, top)),
  };
}

function flyTargetRect() {
  // Where minimize flies to: the window's own dock chip if rendered, else the
  // dock, else the sidebar's bottom corner (the dock's home).
  const dock = document.getElementById('minimized-dock');
  if (dock && dock.getBoundingClientRect().height > 0) return dock.getBoundingClientRect();
  const sb = document.getElementById('sidebar');
  if (sb) { const r = sb.getBoundingClientRect(); return { left: r.left + 16, top: r.bottom - 48, width: 32, height: 24 }; }
  return { left: 16, top: window.innerHeight - 48, width: 32, height: 24 };
}

// ── parked-state persistence (G5 refresh-persistence audit F2 / Lane G16) ──
// Parked means parked: modalManager's minimized registry is in-memory, so a
// refresh used to snap every parked window back open (and lose its dock
// chip). The kit persists a per-window parked flag — keyed per user,
// mirroring the slot-offset scheme ('orwell-slot-offset:<key>:<user>') —
// set on minimize(), cleared on a dock restore and on close/teardown.
// open() consults it and mounts a previously-parked window DIRECTLY into
// the dock (chip rendered, panel hidden, no open animation — no flash, no
// raise, no focus steal).
function parkedKey(id) {
  return 'orwell-win-parked:' + id + ':' + ((document.body && document.body.dataset.user) || '');
}
function loadParked(id) {
  try { return localStorage.getItem(parkedKey(id)) === '1'; } catch (_) { return false; }
}
function saveParked(id, on) {
  try {
    if (on) localStorage.setItem(parkedKey(id), '1');
    else localStorage.removeItem(parkedKey(id));
  } catch (_) {}
}

export class OrwellWindow {
  /**
   * opts: { id, title, icon, slot='top-right', slotKey=null, role='complementary',
   *         draggable=true, minimizable=true, closable=true, resizable=false,
   *         content (Node|string), focus=false, onClose, onMinimize, onRestore }
   */
  constructor(opts) {
    this.o = Object.assign({ slot: 'top-right', role: 'complementary',
      draggable: true, minimizable: true, closable: true, resizable: false, focus: false }, opts);
    if (!this.o.id || !this.o.title) throw new Error('OrwellWindow needs id + title');
    this.ac = new AbortController();
    this.opener = null;
    this.el = null;
    this._slot = null;
  }

  _build() {
    ensureCss();
    const el = document.createElement('div');
    el.id = this.o.id;
    el.className = 'ow-window';
    el.setAttribute('data-ow-window', '');
    el.setAttribute('role', this.o.role);
    el.setAttribute('aria-label', this.o.title);
    const tb = document.createElement('div');
    tb.className = 'ow-titlebar';
    tb.setAttribute('tabindex', '0');
    tb.title = this.o.draggable ? 'Drag to move · arrows to nudge' : '';
    const title = document.createElement('span');
    title.className = 'ow-title';
    title.textContent = this.o.title;
    const controls = document.createElement('div');
    controls.className = 'ow-controls';
    if (this.o.minimizable) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ow-min';
      b.setAttribute('aria-label', 'Minimize'); b.title = 'Minimize';
      b.textContent = '–';
      b.addEventListener('click', (e) => { e.stopPropagation(); this.minimize(); }, { signal: this.ac.signal });
      controls.appendChild(b);
    }
    if (this.o.closable) {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'ow-close';
      b.setAttribute('aria-label', 'Close'); b.title = 'Close';
      b.textContent = '×';
      b.addEventListener('click', (e) => { e.stopPropagation(); this.close(); }, { signal: this.ac.signal });
      controls.appendChild(b);
    }
    tb.appendChild(title); tb.appendChild(controls);
    const body = document.createElement('div');
    body.className = 'ow-body';
    if (this.o.content instanceof Node) body.appendChild(this.o.content);
    else if (typeof this.o.content === 'string') body.innerHTML = this.o.content;
    el.appendChild(tb); el.appendChild(body);
    this.el = el; this.titlebar = tb; this.body = body;

    // click-to-front (capture so any inner click raises first) — audit F9
    el.addEventListener('pointerdown', () => this.raise(), { capture: true, signal: this.ac.signal });

    // keyboard move / resize / re-dock on the titlebar — audit F10
    tb.addEventListener('keydown', (e) => this._onTitlebarKey(e), { signal: this.ac.signal });

    if (this.o.draggable) {
      makeWindowDraggable(el, {
        content: el, header: tb,
        enableDock: false, enableFullscreen: false, enableResize: false,
        skipSelector: 'button, input, select, textarea',
        onDragEnd: ({ rect }) => this._persist(rect),
      });
    }
    return el;
  }

  _persist(rect) {
    // ONE scheme: the slot offset, clamped at restore (S11). Clamp at SAVE too.
    const c = clampPos(rect.left, rect.top, rect.width, rect.height);
    if (c.left !== rect.left || c.top !== rect.top) {
      this.el.style.left = c.left + 'px'; this.el.style.top = c.top + 'px';
      rect = this.el.getBoundingClientRect();
    }
    if (this._slot) this._slot.saveDragOffset(rect);
  }

  _onTitlebarKey(e) {
    const STEP = 16;
    const dirs = { ArrowLeft: [-STEP, 0], ArrowRight: [STEP, 0], ArrowUp: [0, -STEP], ArrowDown: [0, STEP] };
    if (e.key === 'Home' && this._slot && this.o.slotKey) {
      e.preventDefault();
      try { localStorage.removeItem('orwell-slot-offset:' + this.o.slotKey + ':' + ((document.body && document.body.dataset.user) || '')); } catch (_) {}
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
      this.el.style.width = w + 'px'; this.el.style.height = h + 'px';
      return;
    }
    const c = clampPos(r.left + d[0], r.top + d[1], r.width, r.height);
    this.el.style.left = c.left + 'px'; this.el.style.top = c.top + 'px';
    this.el.style.right = 'auto'; this.el.style.bottom = 'auto'; this.el.style.transform = 'none';
    this._persist(this.el.getBoundingClientRect());
  }

  open(opener) {
    if (this.el && this.el.isConnected) { this.restore(); return this; }
    this.opener = opener || document.activeElement || null;
    const el = this._build();
    document.body.appendChild(el);
    if (window.OrwellSlots) {
      this._slot = window.OrwellSlots.register(el, this.o.slot,
        { key: this.o.slotKey || null, draggable: this.o.draggable });
    }
    Modals.register(this.o.id, {
      label: this.o.title, icon: this.o.icon || '',
      restoreFn: () => this._afterDockRestore(),
      closeFn: () => this._teardown(),
    });
    // F2 (G5 audit / G16): a window the player parked stays parked across a
    // refresh — mount straight into the minimized state (dock chip, panel
    // hidden; no open animation, no raise, no focus steal), exactly as if the
    // minimize had happened this page-life. The dock chip (or an explicit
    // restore) brings it back and durably un-parks it.
    if (this.o.minimizable && loadParked(this.o.id)) {
      this._displayBeforeMin = el.style.display;
      Modals.minimize(this.o.id);
      el.style.display = 'none';
      return this;
    }
    if (!REDUCED()) { el.classList.add('ow-anim-open'); setTimeout(() => el.classList.remove('ow-anim-open'), 220); }
    this.raise();
    if (this.o.focus) this.titlebar.focus();
    return this;
  }

  raise() {
    if (!this.el) return;
    if (_zTop >= Z_CEIL) { // renormalize the band
      _zTop = Z_BASE;
      for (const w of _stack) { w.el.style.zIndex = String(++_zTop); }
    }
    this.el.style.zIndex = String(++_zTop);
    const i = _stack.indexOf(this);
    if (i !== -1) _stack.splice(i, 1);
    _stack.push(this);
    for (const w of _stack) w.el && w.el.classList.toggle('ow-focused', w === this);
  }

  minimize() {
    if (!this.el) return;
    saveParked(this.o.id, true); // F2 (G16): parked means parked — survive a refresh
    const i = _stack.indexOf(this);
    if (i !== -1) _stack.splice(i, 1);
    this.el.classList.remove('ow-focused');
    // Capture the pre-minimize inline display so restore can put it BACK —
    // clearing to '' would fall through to a consumer's own CSS (e.g. a panel
    // whose stylesheet defaults to display:none), reproducing the F1 bug class
    // one layer up.
    this._displayBeforeMin = this.el.style.display;
    const done = () => {
      this.el.classList.remove('ow-anim-fly');
      this.el.style.transform = ''; this.el.style.opacity = '';
      Modals.minimize(this.o.id);            // chip renders; F1 makes the dock visible
      this.el.style.display = 'none';        // kit windows aren't .modal — hide explicitly
      try { this.o.onMinimize && this.o.onMinimize(); } catch (_) {}
    };
    if (REDUCED()) { done(); return; }
    // ruling #19: fly-out toward the dock
    const from = this.el.getBoundingClientRect();
    const to = flyTargetRect();
    const dx = (to.left + (to.width || 32) / 2) - (from.left + from.width / 2);
    const dy = (to.top + (to.height || 24) / 2) - (from.top + from.height / 2);
    this.el.classList.add('ow-anim-fly');
    requestAnimationFrame(() => {
      this.el.style.transform = `translate(${dx}px, ${dy}px) scale(.12)`;
      this.el.style.opacity = '0';
      setTimeout(done, 270);
    });
  }

  _afterDockRestore() {
    // modalManager.restore removed .hidden/.modal-minimized and stamped ITS z —
    // re-show (the exact pre-minimize inline display, never '' — see minimize),
    // then re-assert the kit band so stacking stays one authority.
    this.el.style.display = this._displayBeforeMin || '';
    // F2 (G16): a window that mounted straight into the dock (boot-parked)
    // never had a real pre-minimize display captured, and '' can fall through
    // to a consumer stylesheet's display:none (the finale defaults hidden) —
    // a dock restore must always yield a VISIBLE window.
    if (getComputedStyle(this.el).display === 'none') this.el.style.display = 'block';
    saveParked(this.o.id, false); // F2 (G16): an explicit restore un-parks durably
    this.el.style.transform = ''; this.el.style.opacity = '';
    if (this._slot) this._slot.restack();
    this.raise();
    try { this.o.onRestore && this.o.onRestore(); } catch (_) {}
  }

  restore() { Modals.restore(this.o.id); }

  /** True while this window is parked in the dock (modalManager's registry). */
  isMinimized() { return Modals.isMinimized(this.o.id); }

  close() {
    if (!this.el) return;
    const finish = () => Modals.close(this.o.id);   // closeFn → _teardown()
    if (REDUCED()) { finish(); return; }
    this.el.classList.add('ow-anim-fly');           // fly-away on close (ruling #19)
    requestAnimationFrame(() => {
      this.el.style.transform = 'scale(.9)';
      this.el.style.opacity = '0';
      setTimeout(finish, 180);
    });
  }

  _teardown() {
    const i = _stack.indexOf(this);
    if (i !== -1) _stack.splice(i, 1);
    saveParked(this.o.id, false); // F2 (G16): a closed window forgets its parked state
    this.ac.abort();
    const opener = this.opener;
    if (this.el) { this.el.remove(); this.el = null; }
    try { this.o.onClose && this.o.onClose(); } catch (_) {}
    // audit F8: focus returns to the opener
    if (opener && opener.isConnected && typeof opener.focus === 'function') {
      try { opener.focus(); } catch (_) {}
    }
  }

  destroy() { this._teardown(); Modals.unregister(this.o.id); }
}

// Escape participation (audit F7): ui.js's single arbiter calls this between
// the menu stack and the modal pass. Top kit window parks (minimizable) or
// closes; returns true when it consumed the key.
export function dismissTop() {
  for (let i = _stack.length - 1; i >= 0; i--) {
    const w = _stack[i];
    if (!w.el || !w.el.isConnected || w.el.style.display === 'none') { _stack.splice(i, 1); continue; }
    if (w.o.minimizable) w.minimize(); else w.close();
    return true;
  }
  return false;
}

export function stackIds() { return _stack.map((w) => w.o.id); }

// The .ow-* family is page-global chrome (the .ow-dismiss affordance is used by
// non-window surfaces that may render before any window exists) — inject at load.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", ensureCss, { once: true });
} else {
  ensureCss();
}

// The seam every consumer + the headless gate use.
window.OrwellWindowKit = {
  create: (opts) => new OrwellWindow(opts),
  dismissTop,
  stackIds,
};
