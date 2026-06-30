// AppkitGadget — THE gadget kit. The sibling to the AppkitWindow kit (Lane F),
// for the control-room rail (0054) instead of the floating window band.
//
// One base class + one CSS family (.og-card / .og-head / .og-title / .og-actions /
// .og-body / .og-empty + state modifiers) that every RAIL GADGET composes — replacing
// the per-gadget hand-rolled card chrome (each module today does
// createElement("section") + an inline <style> + bespoke .xx-hd/.xx-body builders across
// various gadget modules). The asymmetry with AppkitWindow is exactly why gadget
// order/side/state didn't inherit sync — with no kit it had to be bolted onto the rail +
// each gadget. The kit OWNS, in one place:
//
//   • CHROME: a consistent card shell — header (icon + Title-Case title + optional
//     actions), body, and an empty-state — the .og-* family mirroring .ow-*.
//   • THE RAIL CONTRACT centralized: self-mount into #gadget-rail-body (sidebar → body
//     fallback for a degraded/headless DOM), the registry-row id contract, and
//     CONTENT-DRIVEN visibility self-gating (show()/hide() flip display so the rail's
//     own MutationObserver reveals/hides the rail) — so a gadget is declared once, not
//     hand-wired.
//   • ORDER + PANEL SIDE + cross-device sync are the RAIL's (appkitGadgetRail.js, #637) —
//     the kit DEFERS to it (one source of truth; never a second order scheme). A kit
//     gadget gets per-user order, drag-reorder, side, and the realtime mirror for FREE
//     by being a rail child with a registry row.
//   • PER-GADGET SYNCED STATE (#638): a gadget's COLLAPSED state lives in the SAME 0064
//     layout store under a synthetic id ("gadget:<id>"), reusing the per-field LWW merge +
//     the `layout-changed` fan-out — so collapse survives a reload, follows the player
//     across devices, and mirrors between two windows. localStorage stays the offline/
//     seed fallback (exactly the appkitGadgetRail order + sidebar side precedent).
//
// New gadgets MUST compose the kit (the convention gate test_og_gadget_kit.py pins it,
// the gadget edition of the F-3 window ratchet). Game-build only (the rail is).
//
// Vault-free by construction: the kit only paints chrome — it never touches game state.
// reduced-motion strips the only motion (the collapse chevron transition).

(function () {
  "use strict";

  // The one CSS family. Mirrors appkitWindow.js's ensureCss(): theme-token driven so the
  // house themes (0052) + the frost layer paint it for free, with literal fallbacks for
  // before style.css loads. The card visual language is the EXACT one every hand-rolled
  // gadget used (margin/padding/bg-mix/border/radius/mono/fs-xs) — so a migrated gadget
  // renders byte-identically; the per-gadget inline <style> blocks keep ONLY their
  // gadget-specific inner rules.
  function ensureCss() {
    if (document.getElementById("og-gadget-css")) return;
    var st = document.createElement("style");
    st.id = "og-gadget-css";
    st.textContent =
      // The card shell — the shared rail-gadget chrome. display:none by default; the
      // consuming gadget flips it via show()/hide() (content-driven, the rail observes).
      // #797: gadget INSETS ride the --ow-space-* scale for clean, even, Apple-grade alignment
      // across every gadget kind (no ad-hoc rem values): --ow-space-3 (12px) horizontal padding,
      // --ow-space-2 (8px) vertical padding + margin + inner gaps, --ow-space-1 (4px) tightest gaps.
      // Kept in lock-step with the source-of-truth copy in style.css (.og-* family).
      ".og-card {" +
      "  display: none;" +
      "  margin: var(--ow-space-2, 8px) var(--ow-space-2, 8px) 0;" +
      "  padding: var(--ow-space-2, 8px) var(--ow-space-3, 12px);" +
      "  background: color-mix(in srgb, var(--panel, #111) 70%, transparent);" +
      "  color: var(--fg, #9cdef2);" +
      "  border: 1px solid var(--border, #355a66); border-radius: 10px;" +
      // Shared type system (#709): sans family + label PRESET for gadget rows.
      "  font-family: var(--ow-ui-font, sans-serif);" +
      "  font-size: var(--ow-fs-label, .8125rem); line-height: 1.5; }" +
      // The header: icon + Title-Case title + optional actions. Uses the heading PRESET +
      // the semibold weight token (the title colour mixed toward the panel). The whole
      // header is the collapse affordance when collapsible (role=button on it).
      ".og-card .og-head {" +
      "  display: flex; align-items: center; gap: var(--ow-space-2, 8px); margin: 0 0 var(--ow-space-2, 8px);" +
      "  font-size: var(--ow-fs-heading, .8125rem); font-weight: var(--ow-fw-semibold, 600); letter-spacing: -.01em; }" +
      ".og-card.og-collapsible .og-head { cursor: pointer; user-select: none; -webkit-user-select: none; }" +
      // #729: the gadget-header focus ring is NEUTRAL (system-blue), never the theme red/accent —
      // the glass chrome carries no accent HUE. system-blue is the one sanctioned focus tint.
      ".og-card .og-head:focus-visible { outline: 2px solid var(--ow-ios-blue, #0a84ff); outline-offset: 2px; border-radius: 4px; }" +
      ".og-card .og-icon { flex: 0 0 auto; display: inline-flex; }" +
      ".og-card .og-title {" +
      "  flex: 1 1 auto; min-width: 0;" +
      "  color: color-mix(in srgb, var(--fg, #9cdef2) 78%, var(--panel, #111));" +
      "  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }" +
      ".og-card .og-actions { flex: 0 0 auto; display: inline-flex; align-items: center; gap: var(--ow-space-1, 4px); }" +
      // An action button (Open / Un-pin …) — the gadget-scale affordance at the 24px tap floor
      // the kit-window controls use (J5 bumps coarse pointers).
      ".og-card .og-act {" +
      "  flex: 0 0 auto; background: rgba(255,255,255,.06);" +
      "  border: 1px solid var(--border, #355a66); color: inherit; cursor: pointer;" +
      "  border-radius: 6px; font: inherit; font-size: .68rem;" +
      "  min-height: 24px; padding: 0 var(--ow-space-2, 8px); opacity: .8; }" +
      ".og-card .og-act:hover, .og-card .og-act:focus-visible {" +
      "  opacity: 1; background: rgba(255,255,255,.12); }" +
      // The collapse chevron — only when collapsible. Reduced-motion strips its transition.
      ".og-card .og-chev { flex: 0 0 auto; opacity: .55; margin-left: var(--ow-space-1, 4px); transition: transform .15s; }" +
      ".og-card.og-collapsed .og-chev { transform: rotate(-90deg); }" +
      ".og-card.og-collapsed .og-body { display: none; }" +
      // The body holds the gadget's own content (its existing inner markup unchanged).
      ".og-card .og-body { overflow-wrap: anywhere; }" +
      // The shared empty-state treatment (the quiet italic the gadgets already used).
      ".og-card .og-empty { opacity: .6; font-style: italic; }" +
      "@media (prefers-reduced-motion: reduce) { .og-card .og-chev { transition: none; } }";
    document.head.appendChild(st);
  }

  // ── per-gadget COLLAPSED state, synced (#638) ──────────────────────────────
  // Mirrors the appkitGadgetRail order + sidebar side + premiere-popup dismiss precedent:
  // the SYNCED value (the 0064 layout store, LWW, mirrored via `layout-changed`) is the
  // source of truth; localStorage is the per-device offline/seed fallback. The synthetic
  // window id is "gadget:<id>" (the rail order uses "gadget-rail", popups use "popup:…").
  function syncId(id) { return "gadget:" + id; }
  function collapseKey(id) {
    return "appkit-gadget-collapsed:" + id + ":" + ((document.body && document.body.dataset.user) || "");
  }
  function loadCollapsed(id) {
    try { return localStorage.getItem(collapseKey(id)) === "1"; } catch (_) { return false; }
  }
  function saveCollapsed(id, on, applyingRemote) {
    try { localStorage.setItem(collapseKey(id), on ? "1" : ""); } catch (_) {}
    // Emit through the SAME capture event the window kit + the rail order use — no parallel
    // sync. Suppressed while APPLYING a remote change (no echo loop). AppkitLayoutSync
    // debounces a PATCH /api/appkit/layout; absent module ⇒ localStorage-only, fail-open.
    if (applyingRemote) return;
    try {
      window.dispatchEvent(new CustomEvent("appkit:window-layout",
        { detail: { id: syncId(id), state: { collapsed: !!on } } }));
    } catch (_) {}
  }

  // A live registry of mounted kit gadgets by id, so a synced collapse arriving from the
  // seed (initial GET /layout) or a peer window (`layout-changed`) can reach the gadget.
  var _byId = {};
  function _onSyncedLayout(e) {
    var d = e && e.detail;
    if (!d || !d.windowId || !d.state) return;
    if (String(d.windowId).indexOf("gadget:") !== 0) return;
    var id = String(d.windowId).slice("gadget:".length);
    var g = _byId[id];
    if (g && typeof d.state.collapsed === "boolean") g._applyRemoteCollapsed(d.state.collapsed);
  }
  window.addEventListener("appkit:layout-seed", _onSyncedLayout);     // initial GET /layout
  window.addEventListener("appkit:layout-changed", _onSyncedLayout);  // a peer window / device

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function AppkitGadget(opts) {
    if (!(this instanceof AppkitGadget)) return new AppkitGadget(opts);
    this.o = Object.assign({
      // id        — the gadget's element id in #gadget-rail-body (the registry-row contract).
      // title     — Title-Case label.
      // icon      — a glyph shown before the title (decorative; aria-hidden).
      // role      — the section's ARIA role (default "group").
      // ariaLabel — the section's accessible name (defaults to the title).
      // collapsible — render a collapse chevron + (by default) persist/sync the collapsed state (#638).
      collapsible: false,
      // persistCollapsed (default true): the kit owns the collapse persistence — a per-user
      // localStorage key + the 0064 synced "gadget:<id>" collapsed field (#638). Set false when a
      // consumer owns a RICHER scoping the kit can't express (the status panel's E71 per-user+GAME
      // key): the kit still renders the chevron + wires the toggle + flips the DOM state, but
      // delegates persistence to the consumer — which listens via onCollapse(on) and persists there.
      persistCollapsed: true,
      // onCollapse(on): fired AFTER every collapse change (a header toggle / a remote apply), so a
      // persistCollapsed:false consumer can write its own scoped key. Not fired for the kit's own
      // persistence (that's saveCollapsed's job).
      onCollapse: null,
      role: "group",
    }, opts || {});
    if (!this.o.id || !this.o.title) throw new Error("AppkitGadget needs id + title");
    this.el = null;
    this.head = null;
    this.body = null;
    this.actions = null;
    this._collapsed = false;
    this._applyingRemote = false;
  }

  AppkitGadget.prototype._build = function () {
    ensureCss();
    var el = document.createElement("section");
    el.id = this.o.id;
    el.className = "og-card" + (this.o.collapsible ? " og-collapsible" : "");
    el.setAttribute("data-og-gadget", "");
    el.setAttribute("role", this.o.role);
    el.setAttribute("aria-label", this.o.ariaLabel || this.o.title);

    var head = document.createElement("div");
    head.className = "og-head";
    if (this.o.icon) {
      var ic = document.createElement("span");
      ic.className = "og-icon"; ic.setAttribute("aria-hidden", "true");
      ic.textContent = this.o.icon;
      head.appendChild(ic);
    }
    var title = document.createElement("span");
    title.className = "og-title";
    // The heading is the section's accessible heading (mirrors the old role=heading rows).
    title.setAttribute("role", "heading");
    title.setAttribute("aria-level", "3");
    title.textContent = this.o.title;
    head.appendChild(title);

    var actions = document.createElement("span");
    actions.className = "og-actions";
    head.appendChild(actions);
    this.actions = actions;

    if (this.o.collapsible) {
      var chev = document.createElement("span");
      chev.className = "og-chev"; chev.setAttribute("aria-hidden", "true");
      chev.textContent = "▾";
      head.appendChild(chev);
      // The whole header toggles collapse (keyboard-accessible). Escape is NOT handled here
      // (the F-3 ratchet forbids per-surface Escape — collapse is not a dismiss).
      head.setAttribute("role", "button");
      head.setAttribute("tabindex", "0");
      head.setAttribute("aria-expanded", "true");
      var self = this;
      head.addEventListener("click", function (e) {
        // An action button click must not also toggle the card.
        if (e.target && e.target.closest && e.target.closest(".og-actions")) return;
        self.toggleCollapsed();
      });
      head.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); self.toggleCollapsed(); }
      });
    }

    var body = document.createElement("div");
    body.className = "og-body";

    el.appendChild(head);
    el.appendChild(body);
    this.el = el; this.head = head; this.body = body;
    return el;
  };

  // Mount into the rail body, with the SAME fallback chain every gadget used
  // (#gadget-rail-body → #sidebar → body) so a degraded/headless DOM still works.
  // `anchorId` (optional): insert directly AFTER that gadget when both share the rail
  // body — preserving the legacy in-DOM ordering some gadgets relied on (the registry
  // `order` is the real stacking authority; this just keeps a sane base DOM order).
  AppkitGadget.prototype.mount = function (anchorId) {
    if (this.el && this.el.isConnected) return this.el;
    var el = this.el || this._build();
    var rail = document.getElementById("gadget-rail-body");
    var sidebar = document.getElementById("sidebar");
    var anchor = anchorId ? document.getElementById(anchorId) : null;
    if (rail && anchor && anchor.parentElement === rail) rail.insertBefore(el, anchor.nextSibling);
    else if (rail) rail.appendChild(el);
    else if (anchor && anchor.parentElement) anchor.parentElement.insertBefore(el, anchor.nextSibling);
    else if (sidebar) sidebar.appendChild(el);
    else document.body.appendChild(el);
    _byId[this.o.id] = this;
    if (this.o.collapsible) this._restoreCollapsed();
    return el;
  };

  // Ensure built + mounted; return the .og-body for the gadget to fill with its own content.
  AppkitGadget.prototype.ensure = function (anchorId) {
    this.mount(anchorId);
    return this.body;
  };

  // Add an action button (Open / Un-pin …) to the header. Returns the button.
  AppkitGadget.prototype.addAction = function (cfg) {
    cfg = cfg || {};
    if (!this.actions) this.mount();
    var b = document.createElement("button");
    b.type = "button"; b.className = "og-act";
    if (cfg.label) b.textContent = cfg.label;
    if (cfg.title) b.title = cfg.title;
    if (cfg.ariaLabel) b.setAttribute("aria-label", cfg.ariaLabel);
    if (cfg.dataset) Object.keys(cfg.dataset).forEach(function (k) { b.dataset[k] = cfg.dataset[k]; });
    if (typeof cfg.onClick === "function") b.addEventListener("click", cfg.onClick);
    this.actions.appendChild(b);
    return b;
  };

  // CONTENT-DRIVEN visibility — flip display so the rail's MutationObserver reveals/hides
  // the rail (the 0054 contract; no gamechanged dispatch needed — g15 stays one dispatcher).
  AppkitGadget.prototype.show = function () { if (!this.el) this.mount(); this.el.style.display = "block"; };
  AppkitGadget.prototype.hide = function () { if (this.el) this.el.style.display = "none"; };
  AppkitGadget.prototype.isShown = function () {
    return !!(this.el && this.el.style.display !== "none");
  };

  // ── collapse (collapsible gadgets only) ────────────────────────────────────
  AppkitGadget.prototype._setCollapsedDom = function (on) {
    if (!this.el) return;
    this._collapsed = !!on;
    this.el.classList.toggle("og-collapsed", !!on);
    if (this.head) {
      this.head.setAttribute("aria-expanded", on ? "false" : "true");
      this.head.setAttribute("aria-label", on ? ("Expand " + this.o.title) : ("Collapse " + this.o.title));
      this.head.setAttribute("title", on ? "Expand" : "Collapse");
    }
  };

  AppkitGadget.prototype.setCollapsed = function (on) {
    this._setCollapsedDom(on);
    // The kit owns persistence unless a consumer opted out (persistCollapsed:false — it keeps a
    // richer per-game scoping itself, via the onCollapse hook). Either way the DOM state is the kit's.
    if (this.o.persistCollapsed) saveCollapsed(this.o.id, !!on, this._applyingRemote);
    if (typeof this.o.onCollapse === "function") { try { this.o.onCollapse(!!on); } catch (_) {} }
  };

  AppkitGadget.prototype.toggleCollapsed = function () { this.setCollapsed(!this._collapsed); };

  AppkitGadget.prototype.isCollapsed = function () { return !!this._collapsed; };

  // Restore the persisted collapsed state on mount (localStorage; the synced seed lands
  // via _applyRemoteCollapsed when AppkitLayoutSync re-dispatches the GET /layout blob).
  // A consumer that owns its own persistence (persistCollapsed:false) restores it itself.
  AppkitGadget.prototype._restoreCollapsed = function () {
    if (this.o.persistCollapsed) this._setCollapsedDom(loadCollapsed(this.o.id));
  };

  // Apply a collapse arriving from another device / window. Sets _applyingRemote so the
  // resulting state change doesn't re-emit (no echo loop) — but DOES land in localStorage.
  AppkitGadget.prototype._applyRemoteCollapsed = function (on) {
    if (!this.o.collapsible) return;
    this._applyingRemote = true;
    try { this.setCollapsed(!!on); } finally { this._applyingRemote = false; }
  };

  // The seam every consumer + the convention gate use (mirrors window.AppkitWindowKit).
  window.AppkitGadgetKit = {
    create: function (opts) { return new AppkitGadget(opts); },
    esc: esc,
  };
  window.AppkitGadget = AppkitGadget;
})();
