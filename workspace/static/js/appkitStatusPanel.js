// appkitStatusPanel.js — AppKit Status Panel kit (design-audit "missing kit" #4).
//
// A small, reusable glass panel for surfacing "is the engine alive, and what is it doing"
// style state anywhere in the front-door (a settings page, inside a gadget-rail card body,
// a sidebar strip, …) — a status object in, a consistent panel out. It is a live region:
// every label/detail change is announced to assistive tech (`aria-live="polite"`), and a
// live/paused dot signals state WITHOUT color being the only signal (the dot is paired
// with the text label — never color-only).
//
// Composes the existing AppkitElements button primitives (`.ow-btn-plain`/`.ow-btn-icon`)
// for its optional refresh action rather than hand-rolling new button chrome, and the
// shared design tokens (`--chrome-ink`, `--sys-blue`, `--sys-green`, `--border`,
// `--ow-fs-*`, `--ow-space-*`) — no new hue, per the "no accent hue on text" rule: the
// ONLY colored pixel is the live/paused state dot (system green / neutral), matching the
// audit's "Activity live dot ... use --sys-green live / neutral paused" finding.
//
// Sibling kits: AppkitWindowKit, AppkitGadgetKit, AppkitNoticeKit, AppkitSheetKit — same
// shape: a constructor + `window.AppkitStatusPanelKit = { create }`, an idempotent
// `ensureCss()`, `mount()`/`ensure()` returning the panel (or its detail host).
//
// ── Public API ────────────────────────────────────────────────────────────────────────
//   AppkitStatusPanelKit.create(opts) -> AppkitStatusPanel
//     opts:
//       id            (required) stable element id.
//       title         panel heading (e.g. "Automation"). Optional.
//       label         (default "") the primary status line, e.g. "Working on 3 applications".
//       live          (default false) true = active/"alive" (green dot), false = paused/idle
//                     (neutral dot). Purely a state flag — the label carries the real meaning.
//       detail        (optional) a secondary line under the status (e.g. "Next check in 4m").
//       lastUpdated   (optional) Date | epoch ms | ISO string — rendered as a relative
//                     "updated Xs/m/h/d ago" meta line, kept fresh on a timer.
//       autoRefreshMs (default 30000; 0 disables) how often the relative "updated …" text
//                     re-renders on its own (no announcement — only the initial change to
//                     label/detail/live is spoken, so this never spams a screen reader).
//       onRefresh(evt)  when provided, renders a small icon refresh action in the header.
//       container     mount parent (element or selector). Default: document.body.
//
//   AppkitStatusPanel#el              the root `.osp-panel` element (null until mount()).
//   AppkitStatusPanel#mount(container?) -> el     idempotent build + insert.
//   AppkitStatusPanel#ensure()        -> el       mount() alias (kit convention parity).
//   AppkitStatusPanel#update(patch)   -> this     patch: { label?, live?, detail?, lastUpdated? }.
//   AppkitStatusPanel#setLive(bool)   -> this
//   AppkitStatusPanel#setLabel(text)  -> this
//   AppkitStatusPanel#setDetail(text) -> this
//   AppkitStatusPanel#destroy()       remove from DOM + stop the refresh timer.

(function () {
  'use strict';

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function relativeTime(ts) {
    if (ts == null) return '';
    var t = ts instanceof Date ? ts.getTime() : (typeof ts === 'string' ? Date.parse(ts) : Number(ts));
    if (!isFinite(t)) return '';
    var diff = Date.now() - t;
    if (diff < 0) diff = 0;
    var s = Math.floor(diff / 1000);
    if (s < 5) return 'Updated just now';
    if (s < 60) return 'Updated ' + s + 's ago';
    var m = Math.floor(s / 60);
    if (m < 60) return 'Updated ' + m + 'm ago';
    var h = Math.floor(m / 60);
    if (h < 24) return 'Updated ' + h + 'h ago';
    var d = Math.floor(h / 24);
    return 'Updated ' + d + 'd ago';
  }

  // ── the one CSS family — theme-token driven, mirrors every other kit's ensureCss(). ────
  function ensureCss() {
    if (document.getElementById('osp-status-panel-css')) return;
    var st = document.createElement('style');
    st.id = 'osp-status-panel-css';
    st.textContent =
      '.osp-panel{' +
      'display:block;max-width:340px;' +
      'padding:var(--ow-space-3,12px);border-radius:var(--ow-glass-radius-inner,12px);' +
      'background:color-mix(in srgb,var(--panel,#111) 70%,transparent);' +
      'border:1px solid var(--border,#355a66);color:var(--chrome-ink,var(--fg,#eef1f4));' +
      'font-family:var(--ow-ui-font,sans-serif);font-size:var(--ow-fs-body,.875rem);line-height:1.45}' +
      '.osp-head{display:flex;align-items:center;gap:var(--ow-space-2,8px);' +
      'margin-bottom:var(--ow-space-1,4px)}' +
      '.osp-dot{flex:0 0 auto;width:8px;height:8px;border-radius:50%;' +
      'background:color-mix(in srgb,var(--chrome-ink-3,var(--border,#355a66)) 100%,transparent)}' +
      '.osp-dot.osp-dot-live{background:var(--sys-green,#30d158)}' +
      '@media (prefers-reduced-motion:no-preference){' +
      '@keyframes osp-pulse{0%,100%{opacity:1}50%{opacity:.35}}' +
      '.osp-dot.osp-dot-live{animation:osp-pulse 1.8s ease-in-out infinite}}' +
      '.osp-title{flex:1 1 auto;min-width:0;font-size:var(--ow-fs-heading,.8125rem);' +
      'font-weight:var(--ow-fw-semibold,600);letter-spacing:-.01em;overflow:hidden;' +
      'text-overflow:ellipsis;white-space:nowrap}' +
      '.osp-refresh{flex:0 0 auto}' +
      '.osp-status-line{font-size:var(--ow-fs-body,.875rem);font-weight:var(--ow-fw-semibold,600)}' +
      '.osp-detail{margin-top:2px;font-size:var(--ow-fs-label,.8125rem);' +
      'color:var(--chrome-ink-2,rgba(238,241,244,.68))}' +
      '.osp-detail:empty{display:none}' +
      '.osp-meta{margin-top:var(--ow-space-2,8px);font-size:var(--ow-fs-caption,.75rem);' +
      'color:var(--chrome-ink-3,rgba(238,241,244,.45))}' +
      '.osp-meta:empty{display:none}' +
      '@media (prefers-reduced-transparency:reduce){' +
      '.osp-panel{background:var(--panel,#111)!important;backdrop-filter:none!important}}' +
      '@media (prefers-contrast:more),(forced-colors:active){' +
      '.osp-panel{border-width:2px!important;border-color:var(--fg,CanvasText)!important}' +
      '.osp-dot{outline:1px solid var(--fg,CanvasText)}}';
    document.head.appendChild(st);
  }

  function AppkitStatusPanel(opts) {
    if (!(this instanceof AppkitStatusPanel)) return new AppkitStatusPanel(opts);
    this.o = Object.assign({
      id: null,
      title: '',
      label: '',
      live: false,
      detail: '',
      lastUpdated: null,
      autoRefreshMs: 30000,
      onRefresh: null,
      container: null,
    }, opts || {});
    if (!this.o.id) throw new Error('AppkitStatusPanel needs an id');
    this.el = null;
    this.dot = null;
    this.statusLine = null;
    this.detailEl = null;
    this.metaEl = null;
    this._timer = null;
  }

  AppkitStatusPanel.prototype._build = function () {
    ensureCss();
    var el = document.createElement('section');
    el.id = this.o.id;
    el.className = 'osp-panel';
    el.setAttribute('role', 'group');
    el.setAttribute('aria-label', this.o.title || 'Status');

    var head = document.createElement('div');
    head.className = 'osp-head';
    var dot = document.createElement('span');
    dot.className = 'osp-dot';
    dot.setAttribute('aria-hidden', 'true');
    head.appendChild(dot);
    this.dot = dot;

    var title = document.createElement('span');
    title.className = 'osp-title';
    title.setAttribute('role', 'heading');
    title.setAttribute('aria-level', '3');
    title.textContent = this.o.title || '';
    head.appendChild(title);

    if (typeof this.o.onRefresh === 'function') {
      var btn = document.createElement('button');
      btn.type = 'button';
      // Composes the existing AppkitElements button primitives — no hand-rolled chrome.
      btn.className = 'osp-refresh ow-btn ow-btn-plain ow-btn-icon';
      btn.setAttribute('aria-label', 'Refresh' + (this.o.title ? ' — ' + this.o.title : ' status'));
      btn.title = 'Refresh';
      btn.textContent = '↻'; // ↻
      var self = this;
      btn.addEventListener('click', function (e) { self.o.onRefresh(e); });
      head.appendChild(btn);
    }
    el.appendChild(head);

    var statusLine = document.createElement('div');
    statusLine.className = 'osp-status-line';
    statusLine.setAttribute('role', 'status');
    statusLine.setAttribute('aria-live', 'polite');
    statusLine.textContent = this.o.label || '';
    el.appendChild(statusLine);

    var detail = document.createElement('div');
    detail.className = 'osp-detail';
    detail.textContent = this.o.detail || '';
    el.appendChild(detail);

    var meta = document.createElement('div');
    meta.className = 'osp-meta';
    meta.textContent = relativeTime(this.o.lastUpdated);
    el.appendChild(meta);

    this.el = el; this.statusLine = statusLine; this.detailEl = detail; this.metaEl = meta;
    this._applyLive();
    this._armTimer();
    return el;
  };

  AppkitStatusPanel.prototype._resolveContainer = function () {
    var c = this.o.container;
    if (typeof c === 'string') c = document.querySelector(c);
    return c || document.body;
  };

  AppkitStatusPanel.prototype._applyLive = function () {
    if (!this.dot) return;
    this.dot.classList.toggle('osp-dot-live', !!this.o.live);
  };

  AppkitStatusPanel.prototype._armTimer = function () {
    this._clearTimer();
    if (!this.o.autoRefreshMs || !this.o.lastUpdated) return;
    var self = this;
    this._timer = setInterval(function () {
      if (self.metaEl) self.metaEl.textContent = relativeTime(self.o.lastUpdated);
    }, this.o.autoRefreshMs);
  };

  AppkitStatusPanel.prototype._clearTimer = function () {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  };

  // Idempotent build + insert into the DOM.
  AppkitStatusPanel.prototype.mount = function (container) {
    if (container) this.o.container = container;
    if (this.el && this.el.isConnected) return this.el;
    var el = this.el || this._build();
    this._resolveContainer().appendChild(el);
    return el;
  };

  // Kit-convention parity with the other kits' ensure(); a status panel has no separate
  // content host (its own body IS the content), so this is a mount() alias.
  AppkitStatusPanel.prototype.ensure = function () { return this.mount(); };

  AppkitStatusPanel.prototype.setLabel = function (text) {
    this.o.label = text || '';
    if (this.statusLine) this.statusLine.textContent = this.o.label;
    return this;
  };

  AppkitStatusPanel.prototype.setDetail = function (text) {
    this.o.detail = text || '';
    if (this.detailEl) this.detailEl.textContent = this.o.detail;
    return this;
  };

  AppkitStatusPanel.prototype.setLive = function (on) {
    this.o.live = !!on;
    this._applyLive();
    return this;
  };

  // Merge-update every field at once (a single DOM write pass, one aria-live announcement
  // for the label if it changed).
  AppkitStatusPanel.prototype.update = function (patch) {
    patch = patch || {};
    if (!this.el) this._build();
    if (patch.label != null) this.setLabel(patch.label);
    if (patch.detail != null) this.setDetail(patch.detail);
    if (patch.live != null) this.setLive(patch.live);
    if (patch.lastUpdated !== undefined) {
      this.o.lastUpdated = patch.lastUpdated;
      if (this.metaEl) this.metaEl.textContent = relativeTime(this.o.lastUpdated);
      this._armTimer();
    }
    return this;
  };

  AppkitStatusPanel.prototype.destroy = function () {
    this._clearTimer();
    if (this.el && this.el.isConnected) this.el.remove();
    this.el = null; this.dot = null; this.statusLine = null; this.detailEl = null; this.metaEl = null;
  };

  window.AppkitStatusPanelKit = {
    create: function (opts) { return new AppkitStatusPanel(opts); },
    esc: esc,
  };
  window.AppkitStatusPanel = AppkitStatusPanel;
})();
