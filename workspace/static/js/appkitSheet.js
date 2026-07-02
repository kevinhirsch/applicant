// appkitSheet.js — AppKit Sheet kit (design-audit "missing kit" #3).
//
// A reusable bottom-sheet primitive: mobile-style, bottom-anchored, swipe-to-dismiss —
// that ALSO renders as a centered desktop popover/panel on wide viewports, and as a
// non-modal ANCHORED action-sheet (no scrim, no focus trap, no swipe) for surfaces that
// want to stay in-flow rather than block the screen (e.g. a review/redline prompt that
// should let the rest of the page stay usable).
//
// Builds on real residue: `workspace/static/style.css` already ships a full ".ow-sheet"
// CSS family (search "The iOS bottom-sheet kit") — the scrim, the medium/large DETENTS,
// the opaque-up cross-fade (--ow-sheet-prog), the grabber, the anchored variant, and the
// full a11y trio (reduced-transparency/contrast/motion). That CSS was written in
// anticipation of exactly this module ("the sheet script, which ALSO injects this family
// at runtime") — `ensureCss()` below is the runtime twin, kept in lock-step with it.
// `workspace/static/js/appkitDecision.js` (the decision-card kit) already CONSUMES this
// module's contract (`window.AppkitSheetKit.create({...}).ensure()` / `.el`) — this file
// is the missing implementation behind that seam, matching it exactly.
//
// Sibling kits: AppkitWindowKit (appkitWindow.js, floating/dockable windows),
// AppkitGadgetKit (appkitGadget.js, rail cards), AppkitNoticeKit (appkitNotice.js,
// above-composer affordances) — this kit follows the SAME shape: a constructor +
// `window.AppkitSheetKit = { create, esc }` seam, an idempotent `ensureCss()`, and
// `ensure()` returning the content host for the consumer to fill.
//
// ── Public API ────────────────────────────────────────────────────────────────────────
//   AppkitSheetKit.create(opts) -> AppkitSheet
//     opts:
//       id            (required) stable element id.
//       title         header text (shown in `.ow-sheet-head`; a consumer that brings its
//                     own title, like appkitDecision.js, hides that row itself).
//       role          ARIA role on the sheet root. Default: "dialog" (modal) / "group"
//                     (anchored).
//       dismissible   (default true) render the × close affordance and honor
//                     Escape / backdrop-click / swipe-to-dismiss.
//       anchored      (default false) a non-modal, in-flow action-sheet: no scrim, no
//                     focus trap, no swipe/drag (matches the existing `.ow-sheet-anchored`
//                     CSS). Use for a "keep reading the rest of the page" prompt.
//       popover       (default true; ignored when anchored) on wide viewports (>=769px)
//                     render as a centered desktop popover/panel instead of an
//                     edge-anchored bottom sheet. Always a bottom sheet under 769px.
//       detent        "medium" | "large" (default "medium") — the initial opaque-up
//                     progress (`--ow-sheet-prog`); "large" starts fully opaque.
//       container     mount parent (element or selector). Default: document.body.
//       onOpen()      called after the sheet is mounted + animated in.
//       onClose(reason)  called after teardown. reason: 'user' | 'backdrop' | 'escape' |
//                     'swipe' | 'api'.
//
//   AppkitSheet#el            the root `.ow-sheet` element (null until first open/ensure).
//   AppkitSheet#body          the `.ow-sheet-body` content host (null until built).
//   AppkitSheet#open()        -> el          build (if needed) + mount + animate in.
//   AppkitSheet#ensure()      -> body        open() + return the content host (the
//                              convention this kit's existing consumer already uses).
//   AppkitSheet#close(reason) -> void        animate out (reduced-motion: instant) + unmount.
//   AppkitSheet#isOpen()      -> boolean
//   AppkitSheet#setTitle(text)
//   AppkitSheet#setBody(content)   string (trusted HTML) | Node.
//   AppkitSheet#destroy()     force-remove immediately (no animation), drop listeners.
//
// data-no-swipe-dismiss: any element inside the sheet body can opt OUT of the
// swipe-to-dismiss gesture (mirrors the exact convention `ui.js`'s global swipe-dismiss
// handler already uses for `.cal-splitter` / other internal drag surfaces — read there
// for the precedent) by carrying that attribute, e.g. an internal splitter or a
// horizontally-scrollable strip inside the sheet body.

import { initModalA11y } from './ui.js';

var Z_SCRIM = 1200;
var Z_SHEET = 1201;

var REDUCED_MOTION = function () {
  return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
};
var DESKTOP = function () {
  return !!(window.matchMedia && window.matchMedia('(min-width: 769px)').matches);
};

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
  });
}

// ── the one CSS family — the runtime twin of style.css's ".ow-sheet" block ─────────────
// Idempotent + additive only: it never overrides the linked stylesheet (same selectors,
// so whichever loads last simply wins the cascade harmlessly) — it exists purely so a
// sheet that mounts before style.css has parsed still renders correctly (the same
// contract appkitWindow.js / appkitGadget.js / appkitNotice.js each honor for their own
// families).
function ensureCss() {
  if (document.getElementById('ow-sheet-css')) return;
  var st = document.createElement('style');
  st.id = 'ow-sheet-css';
  st.textContent =
    '.ow-sheet-scrim{position:fixed;inset:0;z-index:' + Z_SCRIM + ';' +
    'background:var(--ow-scrim-bg,rgba(0,0,0,.55))}' +
    '@keyframes ow-sheet-scrim-in{from{opacity:0}to{opacity:1}}' +
    '.ow-sheet-scrim{animation:ow-sheet-scrim-in .2s ease-out}' +
    '.ow-sheet{position:fixed;left:50%;bottom:0;transform:translateX(-50%);' +
    'z-index:' + Z_SHEET + ';width:100%;max-width:720px;display:flex;flex-direction:column;' +
    'border-top-left-radius:var(--ow-glass-radius,14px);border-top-right-radius:var(--ow-glass-radius,14px);' +
    'border:1px solid var(--win-border,var(--border,#355a66));border-bottom:none;' +
    'background:var(--win-bg,var(--panel,#111));color:var(--fg,#eef1f4);' +
    'box-shadow:var(--win-shadow,0 -8px 40px rgba(0,0,0,.45));' +
    'font-family:var(--ow-ui-font,sans-serif);font-size:var(--ow-fs-body,.875rem);line-height:1.5;' +
    '--ow-sheet-prog:0;overflow:hidden;' +
    'transition:height .32s cubic-bezier(.32,.72,0,1),background-color .2s ease}' +
    '.ow-sheet.ow-sheet-dragging{transition:none}' +
    '@keyframes ow-sheet-in{from{transform:translate(-50%,100%)}to{transform:translate(-50%,0)}}' +
    '@keyframes ow-sheet-out{from{transform:translate(-50%,0)}to{transform:translate(-50%,100%)}}' +
    '.ow-sheet.ow-sheet-anim-in{animation:ow-sheet-in .34s cubic-bezier(.32,.72,0,1) both}' +
    '.ow-sheet.ow-sheet-anim-out{animation:ow-sheet-out .26s cubic-bezier(.4,0,1,1) both}' +
    '.ow-sheet-grabber{position:relative;flex:0 0 auto;min-height:28px;padding-top:8px;' +
    'display:flex;align-items:flex-start;justify-content:center;cursor:grab;touch-action:none;' +
    'user-select:none;-webkit-user-select:none}' +
    '.ow-sheet-grabber:active{cursor:grabbing}' +
    '.ow-sheet-grabber span{display:block;width:38px;height:5px;border-radius:3px;' +
    'background:color-mix(in srgb,var(--fg,#eef1f4) 38%,transparent)}' +
    '.ow-sheet-grabber::after{content:"";position:absolute;left:0;right:0;top:0;height:44px}' +
    '.ow-sheet-head{flex:0 0 auto;display:flex;align-items:center;gap:.5rem;' +
    'padding:.15rem .9rem .5rem;touch-action:none}' +
    '.ow-sheet-title{flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;' +
    'white-space:nowrap;font-size:var(--ow-fs-title,1rem);font-weight:var(--ow-fw-semibold,600);' +
    'letter-spacing:-.01em}' +
    '.ow-sheet-close{flex:0 0 auto;min-width:44px;min-height:44px;padding:0;' +
    'margin:-.5rem -.4rem -.5rem 0;display:inline-flex;align-items:center;justify-content:center;' +
    'border:none;background:none;color:inherit;cursor:pointer;opacity:.65;border-radius:8px;' +
    'font:inherit;font-size:1.1rem}' +
    '.ow-sheet-close:hover,.ow-sheet-close:focus-visible{opacity:1;background:rgba(255,255,255,.1)}' +
    '.ow-sheet-close:focus-visible{outline:3px solid var(--ow-ios-blue,#0a84ff);outline-offset:2px}' +
    '.ow-sheet-body{flex:1 1 auto;overflow:auto;-webkit-overflow-scrolling:touch;' +
    'padding:0 .9rem calc(.9rem + env(safe-area-inset-bottom,0px))}' +
    '.ow-sheet.ow-sheet-anchored{position:relative;left:auto;bottom:auto;transform:none;' +
    'width:100%;max-width:760px;margin:0 auto var(--ow-space-2,.45rem);height:auto!important;' +
    'z-index:auto;pointer-events:auto;border-radius:var(--ow-glass-radius-inner,14px);' +
    'border:1px solid var(--accent,var(--red,#e06c75));' +
    'box-shadow:var(--win-shadow,0 8px 32px rgba(0,0,0,.45))}' +
    '.ow-sheet.ow-sheet-anchored .ow-sheet-grabber{min-height:18px;padding-top:6px;cursor:default}' +
    '.ow-sheet.ow-sheet-anchored .ow-sheet-grabber::after{display:none}' +
    '.ow-sheet.ow-sheet-anchored .ow-sheet-body{max-height:60vh}' +
    '@keyframes ow-sheet-anchored-in{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}' +
    '.ow-sheet.ow-sheet-anchored.ow-sheet-anim-in{animation:ow-sheet-anchored-in .22s cubic-bezier(.22,.61,.36,1) both}' +
    // ── the desktop popover/panel variant (this kit's addition) — a centered, non-edge-
    // anchored dialog on wide viewports; still a bottom sheet under 769px or when anchored.
    '@media (min-width:769px){' +
    '.ow-sheet.ow-sheet-popover-desktop{left:50%;top:50%;bottom:auto;right:auto;' +
    'transform:translate(-50%,-50%);width:min(480px,92vw);max-width:480px;max-height:80vh;' +
    'border-radius:var(--ow-glass-radius,14px);' +
    'border-bottom:1px solid var(--win-border,var(--border,#355a66))}' +
    '.ow-sheet.ow-sheet-popover-desktop .ow-sheet-grabber{display:none}' +
    '@keyframes ow-sheet-popover-in{from{opacity:0;transform:translate(-50%,-50%) scale(.96)}' +
    'to{opacity:1;transform:translate(-50%,-50%) scale(1)}}' +
    '@keyframes ow-sheet-popover-out{from{opacity:1;transform:translate(-50%,-50%) scale(1)}' +
    'to{opacity:0;transform:translate(-50%,-50%) scale(.96)}}' +
    '.ow-sheet.ow-sheet-popover-desktop.ow-sheet-anim-in{animation:ow-sheet-popover-in .18s ease-out both}' +
    '.ow-sheet.ow-sheet-popover-desktop.ow-sheet-anim-out{animation:ow-sheet-popover-out .16s ease-in both}' +
    '}' +
    // a modal sheet suppresses page scroll behind it (anchored sheets never set this class).
    'body.ow-sheet-open{overflow:hidden}' +
    '@media (prefers-reduced-transparency:no-preference){' +
    'body.theme-frosted .ow-sheet{background-color:var(--ow-glass-light-color,rgba(255,255,255,.6));' +
    'background-image:var(--ow-glass-light-fill,none);' +
    '-webkit-backdrop-filter:blur(18px) saturate(180%);backdrop-filter:blur(18px) saturate(180%);' +
    'color:#16191f}' +
    'body.theme-frosted .ow-sheet::before{content:"";position:absolute;inset:0;z-index:-1;' +
    'pointer-events:none;background:var(--win-bg,var(--panel,#111));' +
    'opacity:var(--ow-sheet-prog,0);transition:opacity .2s ease;' +
    'border-top-left-radius:inherit;border-top-right-radius:inherit}' +
    'body.theme-frosted .ow-sheet{color:color-mix(in srgb,#16191f calc((1 - var(--ow-sheet-prog,0)) * 100%),var(--fg,#eef1f4))}' +
    '}' +
    '@media (prefers-reduced-transparency:reduce){' +
    '.ow-sheet{background:var(--win-bg,var(--panel,#111))!important;' +
    '-webkit-backdrop-filter:none!important;backdrop-filter:none!important}' +
    '.ow-sheet::before{display:none!important}}' +
    '@media (prefers-contrast:more),(forced-colors:active){' +
    '.ow-sheet{border-color:var(--fg,CanvasText)!important;border-width:2px!important}' +
    '.ow-sheet-grabber span{background:var(--fg,CanvasText)!important}}' +
    '@media (prefers-reduced-motion:reduce){' +
    '.ow-sheet,.ow-sheet.ow-sheet-anim-in,.ow-sheet.ow-sheet-anim-out,' +
    '.ow-sheet-scrim,.ow-sheet::before{animation:none!important;transition:none!important}}';
  document.head.appendChild(st);
}

function AppkitSheet(opts) {
  if (!(this instanceof AppkitSheet)) return new AppkitSheet(opts);
  this.o = Object.assign({
    id: null,
    title: '',
    role: null,
    dismissible: true,
    anchored: false,
    popover: true,
    detent: 'medium',
    container: null,
    onOpen: null,
    onClose: null,
  }, opts || {});
  if (!this.o.id) throw new Error('AppkitSheet needs an id');
  this.el = null;
  this.scrim = null;
  this.head = null;
  this.titleEl = null;
  this.body = null;
  this.closeBtn = null;
  this._a11yCleanup = null;
  this._escHandler = null;
  this._mqHandler = null;
  this._open = false;
  this._swipe = null;
}

AppkitSheet.prototype._isModal = function () { return !this.o.anchored; };

AppkitSheet.prototype._resolveContainer = function () {
  var c = this.o.container;
  if (typeof c === 'string') c = document.querySelector(c);
  return c || document.body;
};

AppkitSheet.prototype._build = function () {
  ensureCss();
  var anchored = this.o.anchored;
  var el = document.createElement('section');
  el.id = this.o.id;
  el.className = 'ow-sheet' + (anchored ? ' ow-sheet-anchored' : '');
  el.setAttribute('role', this.o.role || (anchored ? 'group' : 'dialog'));
  if (!anchored) el.setAttribute('aria-modal', 'true');
  el.style.setProperty('--ow-sheet-prog', this.o.detent === 'large' ? '1' : '0');
  el.tabIndex = -1;

  var grabber = document.createElement('div');
  grabber.className = 'ow-sheet-grabber';
  grabber.setAttribute('aria-hidden', 'true');
  var grip = document.createElement('span');
  grabber.appendChild(grip);
  el.appendChild(grabber);

  var head = document.createElement('div');
  head.className = 'ow-sheet-head';
  var title = document.createElement('span');
  title.className = 'ow-sheet-title';
  title.setAttribute('role', 'heading');
  title.setAttribute('aria-level', '2');
  title.textContent = this.o.title || '';
  head.appendChild(title);
  if (this.o.dismissible) {
    var self = this;
    var x = document.createElement('button');
    x.type = 'button';
    x.className = 'ow-sheet-close';
    x.textContent = '×';
    x.title = 'Close';
    x.setAttribute('aria-label', 'Close' + (this.o.title ? ' — ' + this.o.title : ''));
    x.addEventListener('click', function () { self.close('user'); });
    head.appendChild(x);
    this.closeBtn = x;
  }
  el.appendChild(head);

  var body = document.createElement('div');
  body.className = 'ow-sheet-body';
  el.appendChild(body);

  this.el = el; this.head = head; this.titleEl = title; this.body = body;
  return el;
};

AppkitSheet.prototype._applyPopoverClass = function () {
  if (!this.el || this.o.anchored) return;
  this.el.classList.toggle('ow-sheet-popover-desktop', !!this.o.popover && DESKTOP());
};

AppkitSheet.prototype._wireBackdrop = function () {
  if (!this._isModal() || !this.o.dismissible) return;
  var self = this;
  this.scrim.addEventListener('click', function () { self.close('backdrop'); });
};

// Anchored (non-modal) sheets don't get the hard focus-trap (they're deliberately
// non-blocking — "keep reading the rest of the page"), but a dismissible one still
// honors a scoped Escape.
AppkitSheet.prototype._wireEscapeOnly = function () {
  if (!this.o.dismissible) return;
  var self = this;
  this._escHandler = function (e) {
    if (e.key === 'Escape') { e.preventDefault(); self.close('escape'); }
  };
  this.el.addEventListener('keydown', this._escHandler);
};

// Swipe-to-dismiss (touch only). Mirrors the convention `ui.js`'s global handler already
// uses for `.modal-content` (grab-zone from the header/grabber OR anywhere once scrolled
// to top; horizontal movement cancels; a nested scroller keeps native scroll; velocity +
// distance both count) — reimplemented HERE, scoped to this sheet's own elements, since
// the global handler only matches `.modal-content` / `#theme-popup`. Honors
// `[data-no-swipe-dismiss]` the same way. Never wired for an anchored sheet (not draggable).
AppkitSheet.prototype._wireSwipe = function () {
  if (this.o.anchored || !('ontouchstart' in window)) return;
  var self = this;
  var DISMISS_PX = 90, VELOCITY = 0.5, RUBBER = 0.35;
  var startY = 0, startX = 0, lastY = 0, lastT = 0, velocity = 0, dragging = false, cancelled = false;

  function onStart(e) {
    if (e.target.closest && e.target.closest('[data-no-swipe-dismiss]')) return;
    var isHeader = !!e.target.closest('.ow-sheet-head, .ow-sheet-grabber');
    var isButton = !!e.target.closest('button, input, select, textarea, a, label');
    if (isHeader && isButton) return;
    var t = e.touches[0];
    var rect = self.el.getBoundingClientRect();
    var grabZone = (t.clientY - rect.top) < 48;
    var atTop = self.body.scrollTop <= 0;
    if (!isHeader && !grabZone && !atTop) return;
    startY = lastY = t.clientY; startX = t.clientX; lastT = e.timeStamp;
    velocity = 0; dragging = false; cancelled = false;
  }
  function onMove(e) {
    if (cancelled) return;
    var t = e.touches[0];
    var dx = Math.abs(t.clientX - startX), dy = t.clientY - startY;
    if (!dragging) {
      if (dx > 40 && dx > Math.abs(dy) * 2) { cancelled = true; return; }
      if (Math.abs(dy) <= 8) return;
      if (dy < 0 && self.body.scrollHeight > self.body.clientHeight + 1) { cancelled = true; return; }
      if (dy > 0 && self.body.scrollTop > 0) { cancelled = true; return; }
      dragging = true;
      self.el.classList.add('ow-sheet-dragging');
    }
    var dt = e.timeStamp - lastT;
    if (dt > 0) velocity = velocity * 0.6 + ((t.clientY - lastY) / dt) * 0.4;
    lastY = t.clientY; lastT = e.timeStamp;
    e.preventDefault();
    var offset = dy > 0 ? dy : dy * RUBBER;
    self.el.style.transform = 'translate(-50%, calc(0px + ' + offset + 'px))';
  }
  function onEnd() {
    if (!dragging) { cancelled = false; return; }
    dragging = false;
    self.el.classList.remove('ow-sheet-dragging');
    var dy = lastY - startY;
    var shouldDismiss = dy > DISMISS_PX || (dy > 24 && velocity > VELOCITY);
    if (shouldDismiss) {
      self.close('swipe');
    } else {
      self.el.style.transition = 'transform .25s cubic-bezier(.2,.9,.3,1.05)';
      self.el.style.transform = '';
      setTimeout(function () { if (self.el) self.el.style.transition = ''; }, 260);
    }
  }
  this.el.addEventListener('touchstart', onStart, { passive: true });
  this.el.addEventListener('touchmove', onMove, { passive: false });
  this.el.addEventListener('touchend', onEnd, { passive: true });
  this.el.addEventListener('touchcancel', onEnd, { passive: true });
  this._swipe = { onStart: onStart, onMove: onMove, onEnd: onEnd };
};

AppkitSheet.prototype.open = function () {
  if (this._open) return this.el;
  var el = this.el || this._build();
  var container = this._resolveContainer();

  if (this._isModal()) {
    ensureCss();
    var scrim = document.createElement('div');
    scrim.className = 'ow-sheet-scrim';
    scrim.id = this.o.id + '-scrim';
    container.appendChild(scrim);
    this.scrim = scrim;
    this._wireBackdrop();
    document.body.classList.add('ow-sheet-open');
  }
  container.appendChild(el);
  this._applyPopoverClass();
  if (!this.o.anchored && window.matchMedia) {
    var self = this;
    this._mq = window.matchMedia('(min-width: 769px)');
    this._mqHandler = function () { self._applyPopoverClass(); };
    if (this._mq.addEventListener) this._mq.addEventListener('change', this._mqHandler);
    else if (this._mq.addListener) this._mq.addListener(this._mqHandler);
  }

  if (!REDUCED_MOTION()) {
    el.classList.add('ow-sheet-anim-in');
    el.addEventListener('animationend', function handler() {
      el.classList.remove('ow-sheet-anim-in');
      el.removeEventListener('animationend', handler);
    }, { once: true });
  }

  if (this._isModal()) {
    var self2 = this;
    this._a11yCleanup = initModalA11y(el, function () { self2.close('escape'); });
  } else {
    this._wireEscapeOnly();
  }
  this._wireSwipe();

  this._open = true;
  if (typeof this.o.onOpen === 'function') { try { this.o.onOpen(); } catch (_) {} }
  return el;
};

// The convention this kit's existing consumer (appkitDecision.js) uses: build + open,
// return the content host.
AppkitSheet.prototype.ensure = function () {
  this.open();
  return this.body;
};

AppkitSheet.prototype.isOpen = function () { return this._open; };

AppkitSheet.prototype.setTitle = function (text) {
  this.o.title = text || '';
  if (this.titleEl) this.titleEl.textContent = this.o.title;
  if (this.closeBtn) this.closeBtn.setAttribute('aria-label', 'Close' + (this.o.title ? ' — ' + this.o.title : ''));
  return this;
};

AppkitSheet.prototype.setBody = function (content) {
  if (!this.body) this._build();
  if (content instanceof Node) { this.body.innerHTML = ''; this.body.appendChild(content); }
  else this.body.innerHTML = content == null ? '' : String(content);
  return this;
};

AppkitSheet.prototype._teardownListeners = function () {
  if (this._a11yCleanup) { try { this._a11yCleanup(); } catch (_) {} this._a11yCleanup = null; }
  if (this._escHandler && this.el) { this.el.removeEventListener('keydown', this._escHandler); this._escHandler = null; }
  if (this._mq && this._mqHandler) {
    if (this._mq.removeEventListener) this._mq.removeEventListener('change', this._mqHandler);
    else if (this._mq.removeListener) this._mq.removeListener(this._mqHandler);
    this._mq = null; this._mqHandler = null;
  }
  document.body.classList.remove('ow-sheet-open');
};

AppkitSheet.prototype.close = function (reason) {
  if (!this._open) return;
  this._open = false;
  var el = this.el, scrim = this.scrim;
  var self = this;
  this._teardownListeners();

  function done() {
    if (el && el.isConnected) el.remove();
    if (scrim && scrim.isConnected) scrim.remove();
    self.scrim = null;
    el && (el.style.transform = '', el.style.transition = '');
    if (typeof self.o.onClose === 'function') { try { self.o.onClose(reason || 'api'); } catch (_) {} }
  }
  if (REDUCED_MOTION() || !el) { done(); return; }
  el.classList.add('ow-sheet-anim-out');
  if (scrim) scrim.style.transition = 'opacity .18s ease-in', scrim.style.opacity = '0';
  el.addEventListener('animationend', done, { once: true });
  setTimeout(done, 320); // belt: fire even if animationend is missed
};

AppkitSheet.prototype.destroy = function () {
  this._teardownListeners();
  if (this.el && this.el.isConnected) this.el.remove();
  if (this.scrim && this.scrim.isConnected) this.scrim.remove();
  this.el = null; this.scrim = null; this.body = null; this.head = null; this.titleEl = null;
  this._open = false;
};

// The seam every consumer uses (mirrors window.AppkitWindowKit / AppkitGadgetKit / AppkitNoticeKit).
window.AppkitSheetKit = {
  create: function (opts) { return new AppkitSheet(opts); },
  esc: esc,
};
window.AppkitSheet = AppkitSheet;

export { AppkitSheet, esc };
export default AppkitSheet;
