// appkitGadgetRail.js — AppKit Gadget Rail kit (design-audit "missing kit" #6).
//
// The rail CONTAINER for `appkitGadget.js` cards. Real residue already anticipates this
// exact module: `appkitGadget.js`'s own header comment says order/side/cross-device sync
// are owned by "appkitGadgetRail.js, #637" and its `mount()` fallback chain looks for
// `#gadget-rail-body` BY ID — this file is the implementation behind that seam. Further
// residue: `workspace/static/style.css` already carries `.gadget-rail-head` /
// `.gadget-rail-title` / `.gadget-rail-rearrange[aria-pressed]` legibility rules and a
// `body.signin-entrance #gadget-rail` entrance animation, and `appkitWindow.js` names
// `#gadget-rail` a PERSISTENT surface (stable position across polls/reloads, no
// entrance-replay after first mount) alongside `#sidebar` / `#minimized-dock` — this kit
// honors that: it builds the container ONCE (idempotent `mount()`), never re-animates it,
// and lets the pre-existing CSS enter/leave rules do their job untouched.
//
// Per the vendored design corpus (`docs/design/liquid-glass/README.md`, "Glass-on-glass
// removed"): the rail is a Control-Center-style TRANSPARENT container — the individual
// `.og-card` gadgets are the single glass tiles, so this kit never paints its own glass
// chrome on `#gadget-rail`, only layout (spacing / scroll / safe-area).
//
// ── Public API ────────────────────────────────────────────────────────────────────────
//   AppkitGadgetRailKit.create(opts?) -> AppkitGadgetRail
//     opts:
//       id             (default "gadget-rail") — also the cross-device sync id (matches
//                      the literal "gadget-rail" string `appkitGadget.js` already reserves).
//       title          (default "Gadgets") the rail head's plain-language label.
//       side           "left" | "right" (default "right") — which viewport edge a
//                      vertical rail docks to.
//       orientation    "vertical" | "horizontal" (default "vertical").
//       rearrangeable  (default true) show the "Rearrange" toggle enabling drag + keyboard
//                      (Alt+Arrow) reorder of the mounted cards.
//       container      mount parent (element or selector). Default: document.body.
//
//   AppkitGadgetRail#el     the root `#gadget-rail` element (built on first mount()).
//   AppkitGadgetRail#body   the `#gadget-rail-body` scroll host — the SAME element
//                           `AppkitGadget#mount()` already looks up by id, so any card
//                           built via `AppkitGadgetKit.create(...).mount()` lands here for
//                           free once this rail has been mounted first.
//   AppkitGadgetRail#mount()          -> el     idempotent build + insert.
//   AppkitGadgetRail#isEmpty()        -> boolean
//   AppkitGadgetRail#setSide(side)    -> this
//   AppkitGadgetRail#setOrientation(o)-> this
//   AppkitGadgetRail#setRearrangeable(bool) -> this
//   AppkitGadgetRail#destroy()        remove from DOM + drop every listener/observer.

(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function userKey() {
    try { return (document.body && document.body.dataset.user) || ''; } catch (_) { return ''; }
  }
  function orderStorageKey(id) { return 'appkit-gadget-rail-order:' + id + ':' + userKey(); }
  function sideStorageKey(id) { return 'appkit-gadget-rail-side:' + id + ':' + userKey(); }

  function loadJSON(key) {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (_) { return null; }
  }
  function saveJSON(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (_) {}
  }

  // ── the one CSS family — layout + a11y only; NEVER its own glass fill (Control Center
  // model — the cards are the glass tiles, this container stays transparent). ────────────
  function ensureCss() {
    if (document.getElementById('ogr-gadget-rail-css')) return;
    var st = document.createElement('style');
    st.id = 'ogr-gadget-rail-css';
    st.textContent =
      '#gadget-rail,.gadget-rail{' +
      'position:fixed;z-index:900;background:transparent;' +
      'display:flex;pointer-events:none}' +
      '#gadget-rail *,.gadget-rail *{pointer-events:auto}' +
      '.gadget-rail-vertical{' +
      'top:calc(60px + env(safe-area-inset-top,0px));' +
      'bottom:calc(12px + env(safe-area-inset-bottom,0px));' +
      'width:min(280px,88vw);flex-direction:column}' +
      '.gadget-rail-vertical.gadget-rail-side-right{right:10px}' +
      '.gadget-rail-vertical.gadget-rail-side-left{left:10px}' +
      '.gadget-rail-horizontal{' +
      'left:10px;right:10px;bottom:calc(12px + env(safe-area-inset-bottom,0px));' +
      'height:min(220px,40vh);flex-direction:row}' +
      '.gadget-rail-head{' +
      'flex:0 0 auto;display:flex;align-items:center;gap:var(--ow-space-2,8px);' +
      'padding:0 var(--ow-space-1,4px) var(--ow-space-2,8px)}' +
      '.gadget-rail-title{flex:1 1 auto;min-width:0;font-family:var(--ow-ui-font,sans-serif);' +
      'font-size:var(--ow-fs-heading,.8125rem);font-weight:var(--ow-fw-semibold,600);' +
      'letter-spacing:-.01em;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
      '.gadget-rail-rearrange{flex:0 0 auto}' +
      '.gadget-rail-body{' +
      'flex:1 1 auto;display:flex;gap:var(--ow-space-2,8px);overflow:auto;' +
      '-webkit-overflow-scrolling:touch;min-height:0}' +
      '.gadget-rail-vertical .gadget-rail-body{flex-direction:column}' +
      '.gadget-rail-horizontal .gadget-rail-body{flex-direction:row}' +
      '#gadget-rail.gadget-rail-empty{display:none}' +
      '.gadget-rail-rearranging .og-card{cursor:grab}' +
      '.gadget-rail-rearranging .og-card:active{cursor:grabbing}' +
      '.gadget-rail-card-dragging{opacity:.45}' +
      '@media (prefers-reduced-transparency:reduce){#gadget-rail,.gadget-rail{background:transparent!important}}' +
      '@media (max-width:768px){.gadget-rail-vertical{display:none}}'; // narrow tier: the mobile
      // drawer/sheet host owns this real estate (0054 contract); this kit stays desktop-only
      // for the fixed-rail presentation, matching the slot engine's own narrow stand-down.
    document.head.appendChild(st);
  }

  function isVisible(el) { return !!el && el.style.display !== 'none'; }

  function AppkitGadgetRail(opts) {
    if (!(this instanceof AppkitGadgetRail)) return new AppkitGadgetRail(opts);
    this.o = Object.assign({
      id: 'gadget-rail',
      title: 'Gadgets',
      side: 'right',
      orientation: 'vertical',
      rearrangeable: true,
      container: null,
    }, opts || {});
    var savedSide = loadJSON(sideStorageKey(this.o.id));
    if (savedSide === 'left' || savedSide === 'right') this.o.side = savedSide;
    this.el = null;
    this.head = null;
    this.titleEl = null;
    this.rearrangeBtn = null;
    this.body = null;
    this._rearranging = false;
    this._applyingOrder = false;
    this._applyingRemote = false;
    this._mo = null;
    this._dragId = null;
    this._onSyncedLayout = this._onSyncedLayout.bind(this);
  }

  AppkitGadgetRail.prototype._resolveContainer = function () {
    var c = this.o.container;
    if (typeof c === 'string') c = document.querySelector(c);
    return c || document.body;
  };

  AppkitGadgetRail.prototype._build = function () {
    ensureCss();
    var el = document.getElementById(this.o.id) || document.createElement('aside');
    el.id = this.o.id;
    el.setAttribute('aria-label', this.o.title);
    this.el = el;

    var head = document.createElement('div');
    head.className = 'gadget-rail-head';
    var title = document.createElement('span');
    title.className = 'gadget-rail-title';
    title.setAttribute('role', 'heading');
    title.setAttribute('aria-level', '2');
    title.textContent = this.o.title;
    head.appendChild(title);
    this.titleEl = title;

    if (this.o.rearrangeable) {
      var self = this;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'gadget-rail-rearrange ow-btn ow-btn-plain ow-btn-sm';
      btn.setAttribute('aria-pressed', 'false');
      btn.textContent = 'Rearrange';
      btn.addEventListener('click', function () { self.setRearranging(!self._rearranging); });
      head.appendChild(btn);
      this.rearrangeBtn = btn;
    }
    el.appendChild(head);
    this.head = head;

    var body = document.getElementById('gadget-rail-body') || document.createElement('div');
    body.id = 'gadget-rail-body';
    body.className = 'gadget-rail-body';
    body.setAttribute('role', 'group');
    body.setAttribute('aria-label', this.o.title + ' list');
    el.appendChild(body);
    this.body = body;

    this._applyOrientation();
    this._wireReorder();
    this._wireVisibilityObserver();
    this._wireSync();
    return el;
  };

  AppkitGadgetRail.prototype._applyOrientation = function () {
    if (!this.el) return;
    this.el.classList.remove('gadget-rail-vertical', 'gadget-rail-horizontal',
      'gadget-rail-side-left', 'gadget-rail-side-right');
    this.el.classList.add('gadget-rail',
      this.o.orientation === 'horizontal' ? 'gadget-rail-horizontal' : 'gadget-rail-vertical');
    if (this.o.orientation !== 'horizontal') {
      this.el.classList.add(this.o.side === 'left' ? 'gadget-rail-side-left' : 'gadget-rail-side-right');
    }
  };

  // ── empty-state auto-hide — the content-driven visibility contract `appkitGadget.js`'s
  // own header comment describes: a card's show()/hide() flips its inline display; the
  // rail watches for that and reveals/hides ITSELF so an all-hidden rail never floats an
  // empty head band over the page.
  AppkitGadgetRail.prototype._wireVisibilityObserver = function () {
    var self = this;
    var recompute = function () {
      var empty = self.isEmpty();
      self.el.classList.toggle('gadget-rail-empty', empty);
      self.el.setAttribute('aria-hidden', empty ? 'true' : 'false');
    };
    recompute();
    if (typeof MutationObserver === 'undefined') return;
    this._mo = new MutationObserver(function (muts) {
      if (self._applyingOrder) return; // don't fight our own reorder writes
      var relevant = muts.some(function (m) {
        return m.type === 'childList' || (m.type === 'attributes' &&
          (m.attributeName === 'style' || m.attributeName === 'class'));
      });
      if (relevant) recompute();
      if (!self._applyingOrder && muts.some(function (m) { return m.type === 'childList' && m.addedNodes.length; })) {
        self._applyPersistedOrder();
      }
    });
    this._mo.observe(this.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] });
  };

  AppkitGadgetRail.prototype.isEmpty = function () {
    if (!this.body) return true;
    return !Array.prototype.some.call(this.body.children, isVisible);
  };

  // ── order persistence + cross-device sync (the SAME "0064 layout store" convention
  // AppkitGadget/AppkitNotice use for their own state — `appkit:window-layout` out,
  // `appkit:layout-seed`/`appkit:layout-changed` in) — keyed on the bare rail id, matching
  // the literal "gadget-rail" sync id `appkitGadget.js` already reserves in its comments.
  AppkitGadgetRail.prototype._currentOrder = function () {
    return Array.prototype.map.call(this.body.children, function (c) { return c.id; }).filter(Boolean);
  };

  AppkitGadgetRail.prototype._saveOrder = function () {
    var order = this._currentOrder();
    saveJSON(orderStorageKey(this.o.id), order);
    if (this._applyingRemote) return;
    try {
      window.dispatchEvent(new CustomEvent('appkit:window-layout',
        { detail: { id: this.o.id, state: { order: order } } }));
    } catch (_) {}
  };

  AppkitGadgetRail.prototype._applyPersistedOrder = function (order) {
    order = order || loadJSON(orderStorageKey(this.o.id));
    if (!order || !order.length || !this.body) return;
    var current = Array.prototype.slice.call(this.body.children);
    var byId = {};
    current.forEach(function (c) { if (c.id) byId[c.id] = c; });
    var frag = document.createDocumentFragment();
    order.forEach(function (id) { if (byId[id]) { frag.appendChild(byId[id]); delete byId[id]; } });
    current.forEach(function (c) { if (c.id && byId[c.id]) frag.appendChild(c); else if (!c.id) frag.appendChild(c); });
    this._applyingOrder = true;
    try { this.body.appendChild(frag); } finally { this._applyingOrder = false; }
  };

  AppkitGadgetRail.prototype._onSyncedLayout = function (e) {
    var d = e && e.detail;
    if (!d || d.id !== this.o.id || !d.state || !d.state.order) return;
    this._applyingRemote = true;
    try {
      saveJSON(orderStorageKey(this.o.id), d.state.order);
      this._applyPersistedOrder(d.state.order);
    } finally { this._applyingRemote = false; }
  };

  AppkitGadgetRail.prototype._wireSync = function () {
    window.addEventListener('appkit:layout-seed', this._onSyncedLayout);
    window.addEventListener('appkit:layout-changed', this._onSyncedLayout);
    this._applyPersistedOrder();
  };

  // ── reorder — drag (mouse/touch via native DnD) + keyboard (Alt+Arrow), only while
  // "Rearrange" is toggled on. ────────────────────────────────────────────────────────────
  AppkitGadgetRail.prototype._wireReorder = function () {
    var self = this;
    this.body.addEventListener('dragstart', function (e) {
      var card = e.target.closest && e.target.closest('#gadget-rail-body > *');
      if (!self._rearranging || !card) return;
      self._dragId = card.id;
      card.classList.add('gadget-rail-card-dragging');
      try { e.dataTransfer.setData('text/plain', card.id); e.dataTransfer.effectAllowed = 'move'; } catch (_) {}
    });
    this.body.addEventListener('dragover', function (e) {
      if (!self._rearranging || !self._dragId) return;
      var target = e.target.closest && e.target.closest('#gadget-rail-body > *');
      if (!target || target.id === self._dragId) return;
      e.preventDefault();
      var dragging = document.getElementById(self._dragId);
      if (!dragging) return;
      var rect = target.getBoundingClientRect();
      var horizontal = self.o.orientation === 'horizontal';
      var before = horizontal
        ? (e.clientX - rect.left) < rect.width / 2
        : (e.clientY - rect.top) < rect.height / 2;
      self._applyingOrder = true;
      try {
        if (before) target.parentNode.insertBefore(dragging, target);
        else target.parentNode.insertBefore(dragging, target.nextSibling);
      } finally { self._applyingOrder = false; }
    });
    this.body.addEventListener('drop', function (e) { if (self._rearranging) e.preventDefault(); });
    this.body.addEventListener('dragend', function () {
      if (self._dragId) {
        var el = document.getElementById(self._dragId);
        if (el) el.classList.remove('gadget-rail-card-dragging');
      }
      self._dragId = null;
      self._saveOrder();
    });

    // Keyboard alternative (WCAG 2.1.1): Alt+Arrow swaps the focused card with its
    // sibling in the reorder direction while Rearrange is on.
    this.body.addEventListener('keydown', function (e) {
      if (!self._rearranging || !e.altKey) return;
      var horizontal = self.o.orientation === 'horizontal';
      var forwardKey = horizontal ? 'ArrowRight' : 'ArrowDown';
      var backKey = horizontal ? 'ArrowLeft' : 'ArrowUp';
      if (e.key !== forwardKey && e.key !== backKey) return;
      var card = e.target.closest && e.target.closest('#gadget-rail-body > *');
      if (!card) return;
      e.preventDefault();
      var sib = e.key === forwardKey ? card.nextElementSibling : card.previousElementSibling;
      if (!sib) return;
      self._applyingOrder = true;
      try {
        if (e.key === forwardKey) card.parentNode.insertBefore(sib, card);
        else card.parentNode.insertBefore(card, sib);
      } finally { self._applyingOrder = false; }
      var focusTarget = document.activeElement === document.body ? card : e.target;
      if (focusTarget && focusTarget.focus) focusTarget.focus();
      self._saveOrder();
    });
  };

  AppkitGadgetRail.prototype.setRearranging = function (on) {
    this._rearranging = !!on;
    if (this.rearrangeBtn) {
      this.rearrangeBtn.setAttribute('aria-pressed', this._rearranging ? 'true' : 'false');
      this.rearrangeBtn.textContent = this._rearranging ? 'Done' : 'Rearrange';
    }
    if (this.el) this.el.classList.toggle('gadget-rail-rearranging', this._rearranging);
    if (this.body) {
      Array.prototype.forEach.call(this.body.children, function (c) {
        if (this._rearranging) c.setAttribute('draggable', 'true'); else c.removeAttribute('draggable');
      }, this);
    }
    return this;
  };

  AppkitGadgetRail.prototype.setRearrangeable = function (on) {
    this.o.rearrangeable = !!on;
    if (this.rearrangeBtn) this.rearrangeBtn.style.display = on ? '' : 'none';
    if (!on) this.setRearranging(false);
    return this;
  };

  AppkitGadgetRail.prototype.setSide = function (side) {
    if (side !== 'left' && side !== 'right') return this;
    this.o.side = side;
    saveJSON(sideStorageKey(this.o.id), side);
    this._applyOrientation();
    return this;
  };

  AppkitGadgetRail.prototype.setOrientation = function (orientation) {
    if (orientation !== 'vertical' && orientation !== 'horizontal') return this;
    this.o.orientation = orientation;
    this._applyOrientation();
    return this;
  };

  // Idempotent build + insert. A persistent surface: mounting an ALREADY-mounted rail is a
  // no-op (never a re-animate/re-insert), matching the #752 persistent-surface policy.
  AppkitGadgetRail.prototype.mount = function () {
    if (this.el && this.el.isConnected) return this.el;
    var el = this.el || this._build();
    if (!el.isConnected) this._resolveContainer().appendChild(el);
    return el;
  };

  AppkitGadgetRail.prototype.destroy = function () {
    if (this._mo) { this._mo.disconnect(); this._mo = null; }
    window.removeEventListener('appkit:layout-seed', this._onSyncedLayout);
    window.removeEventListener('appkit:layout-changed', this._onSyncedLayout);
    if (this.el && this.el.isConnected) this.el.remove();
    this.el = null; this.head = null; this.titleEl = null; this.rearrangeBtn = null; this.body = null;
  };

  window.AppkitGadgetRailKit = {
    create: function (opts) { return new AppkitGadgetRail(opts); },
    esc: esc,
  };
  window.AppkitGadgetRail = AppkitGadgetRail;
})();
