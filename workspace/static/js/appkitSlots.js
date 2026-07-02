// appkitSlots.js — AppKit named-content Slot Manager (design-audit "missing kit" #5).
//
// IMPORTANT — this is NOT the floating-window position/anchor engine. That engine already
// lives in `appkitWindow.js` as `window.AppkitSlots` (top-right/top-left/top-center/
// bottom-center/bottom-right VIEWPORT anchors for floating panels — geometry, drag offsets,
// viewport clamping). This kit is a different, complementary primitive: given ONE container
// element with named CHILD regions, it lets any number of independent consumers
// register/replace content into a named slot — declaratively, without reaching into each
// other's DOM — with clean render and clean teardown. Exposed as `window.AppkitSlotKit`
// (never `AppkitSlots`) so the two can never collide or be confused for one another.
//
// It builds on the ONE piece of residue the audit found: the `.appkit-slotted` CSS marker
// (`workspace/static/css/kit-themes.css`, "the-feed"/frost rules) that already opts an
// element into the shared kit frost/glass treatment. A slot HOST created by this kit
// carries that marker by default (`frost:false` opts out) — so a panel built purely out of
// named slots picks up the same glass chrome every other kit surface gets, for free.
//
// ── Public API ────────────────────────────────────────────────────────────────────────
//   AppkitSlotKit.create(hostEl, opts?) -> SlotHost
//     Scans `hostEl` for existing `[data-appkit-slot="name"]` children; any name listed in
//     `opts.names` with no matching child gets one CREATED (a plain
//     `<div class="appkit-slot" data-appkit-slot="name">`, appended in listed order).
//     opts: { names?: string[], frost?: boolean (default true) }
//
//   AppkitSlotKit.bind(hostEl) -> SlotHost
//     Like create(), but never builds a missing slot — use when the markup already
//     declares every named region and you just want the controller for it.
//
//   AppkitSlotKit.get(hostEl) -> SlotHost | null
//     Look up a host already created/bound for this element (idempotent — create()/bind()
//     on the same element return the SAME SlotHost instance).
//
//   SlotHost#slot(name)      -> HTMLElement | null   the raw slot element.
//   SlotHost#has(name)       -> boolean
//   SlotHost#names()         -> string[]              every known slot name, in DOM order.
//   SlotHost#render(name, content, opts?) -> HTMLElement | null
//     Clears the slot, then fills it. `content`: a Node, an HTML string (trusted author
//     markup — same convention as AppkitNotice#setBody / AppkitSheet#setBody), or a
//     function `(slotEl) => void` for full manual control. Unknown slot name -> null
//     (fails open — never throws, so a consumer racing a not-yet-declared slot is a no-op,
//     not a crash). `opts.append` (default false) skips the clear.
//   SlotHost#append(name, content) -> HTMLElement | null   render() with append:true.
//   SlotHost#clear(name)     -> void    empty one slot's content (the slot element stays).
//   SlotHost#clearAll()      -> void    empty every slot.
//   SlotHost#addSlot(name)   -> HTMLElement   declare + build a new named slot at runtime
//     (a no-op returning the existing element if the name is already registered).
//   SlotHost#teardown()      -> void    clearAll() + drop the host from the registry — call
//     from a consumer's own unmount/dispose path; idempotent, safe to call twice.

(function () {
  'use strict';

  var ATTR = 'data-appkit-slot';

  // hostEl -> SlotHost, so create()/bind()/get() on the same element are idempotent without
  // minting a synthetic id (mirrors the WeakMap-free registries the other kits use, but this
  // kit has no natural string id to key on — the host element itself IS the key).
  var _registry = typeof WeakMap === 'function' ? new WeakMap() : null;
  var _fallbackRegistry = []; // [{el, host}] — only used where WeakMap is unavailable.

  function registryGet(el) {
    if (_registry) return _registry.get(el) || null;
    for (var i = 0; i < _fallbackRegistry.length; i++) if (_fallbackRegistry[i].el === el) return _fallbackRegistry[i].host;
    return null;
  }
  function registrySet(el, host) {
    if (_registry) { _registry.set(el, host); return; }
    _fallbackRegistry.push({ el: el, host: host });
  }
  function registryDelete(el) {
    if (_registry) { _registry.delete(el); return; }
    for (var i = 0; i < _fallbackRegistry.length; i++) if (_fallbackRegistry[i].el === el) { _fallbackRegistry.splice(i, 1); return; }
  }

  // Minimal layout-agnostic CSS: the kit imposes NO layout of its own (a slot host's
  // arrangement — row/column/grid — is the consuming surface's call), only an empty-slot
  // affordance so an unrendered slot collapses cleanly instead of leaving a visible gap.
  function ensureCss() {
    if (document.getElementById('appkit-slots-css')) return;
    var st = document.createElement('style');
    st.id = 'appkit-slots-css';
    st.textContent =
      '.appkit-slot:empty{display:none}' +
      '@media (prefers-reduced-motion:no-preference){' +
      '.appkit-slot[data-appkit-slot-animate]{transition:opacity .15s ease}}' +
      '@media (prefers-reduced-motion:reduce){' +
      '.appkit-slot{transition:none!important}}';
    document.head.appendChild(st);
  }

  function SlotHost(hostEl, opts) {
    this.host = hostEl;
    this.o = Object.assign({ frost: true }, opts || {});
    this._slots = {}; // name -> element, insertion order preserved by object key order (ES2015+)
    if (this.o.frost) hostEl.classList.add('appkit-slotted');
    hostEl.setAttribute('data-appkit-slot-host', '');
    this._scan();
  }

  SlotHost.prototype._scan = function () {
    var found = this.host.querySelectorAll('[' + ATTR + ']');
    for (var i = 0; i < found.length; i++) {
      var name = found[i].getAttribute(ATTR);
      if (name) this._slots[name] = found[i];
    }
  };

  SlotHost.prototype.addSlot = function (name) {
    if (this._slots[name]) return this._slots[name];
    ensureCss();
    var el = document.createElement('div');
    el.className = 'appkit-slot';
    el.setAttribute(ATTR, name);
    this.host.appendChild(el);
    this._slots[name] = el;
    return el;
  };

  SlotHost.prototype.slot = function (name) { return this._slots[name] || null; };
  SlotHost.prototype.has = function (name) { return !!this._slots[name]; };
  SlotHost.prototype.names = function () { return Object.keys(this._slots); };

  SlotHost.prototype.render = function (name, content, opts) {
    var el = this._slots[name];
    if (!el) return null; // fail open — an undeclared slot is a no-op, never a throw
    var append = !!(opts && opts.append);
    if (!append) el.innerHTML = '';
    if (content == null) return el;
    if (typeof content === 'function') { content(el); return el; }
    if (content instanceof Node) { el.appendChild(content); return el; }
    // string -> trusted author HTML (same convention as AppkitNotice#setBody / AppkitSheet#setBody).
    if (append) el.insertAdjacentHTML('beforeend', String(content));
    else el.innerHTML = String(content);
    return el;
  };

  SlotHost.prototype.append = function (name, content) {
    return this.render(name, content, { append: true });
  };

  SlotHost.prototype.clear = function (name) {
    var el = this._slots[name];
    if (el) el.innerHTML = '';
  };

  SlotHost.prototype.clearAll = function () {
    var self = this;
    this.names().forEach(function (n) { self.clear(n); });
  };

  SlotHost.prototype.teardown = function () {
    this.clearAll();
    this.host.removeAttribute('data-appkit-slot-host');
    registryDelete(this.host);
  };

  function bindOrCreate(hostEl, opts, build) {
    if (!hostEl || !hostEl.nodeType) throw new Error('AppkitSlotKit needs a host element');
    var existing = registryGet(hostEl);
    if (existing) return existing;
    var host = new SlotHost(hostEl, opts);
    if (build && opts && Array.isArray(opts.names)) {
      opts.names.forEach(function (n) { if (!host.has(n)) host.addSlot(n); });
    }
    registrySet(hostEl, host);
    return host;
  }

  window.AppkitSlotKit = {
    create: function (hostEl, opts) { return bindOrCreate(hostEl, opts, true); },
    bind: function (hostEl) { return bindOrCreate(hostEl, null, false); },
    get: function (hostEl) { return registryGet(hostEl); },
  };
  window.AppkitSlotHost = SlotHost;
})();
