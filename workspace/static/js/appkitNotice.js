// AppkitNotice — THE in-chat notification/affordance kit (#642). The THIRD DWE kit,
// sibling to the AppkitWindow kit (Lane F, floating window band) and the AppkitGadget
// kit (#640, control-room rail). This one owns the ABOVE-COMPOSER AFFORDANCE ZONE — the
// strip of in-chat affordances that are NOT chat messages (the game guide, narrator-
// proposed decisions, system notices, the Continue prompt). Each was hand-rolled with its
// own anchor/dismiss/animation/persistence; they collided on the same real estate above
// the composer and fought for the slot. The kit OWNS, in one place:
//
//   • CHROME + ANCHOR: ONE consistent stacked container (#appkit-notice-zone) anchored
//     directly above the composer (.chat-input-bar), with the .on-* CSS family. Affordances
//     are CHILDREN of that container — never each minting its own insertBefore(bar) — so
//     several present at once STACK deterministically (priority order) instead of fighting.
//   • KIND/SEVERITY: guide / decision / system-notice / continue — consistent styling +
//     semantics per kind. A `severity` (info / warn / error) tints the strip. Decisions are
//     HARD-STOP affordances: dismissible by the player, but NEVER auto-dismissed.
//   • DISMISS + A11Y: ONE dismiss affordance (the .on-dismiss × at the 44px touch floor),
//     aria-live per kind (assertive for system-notice/decision, polite for guide/continue),
//     reduced-motion-safe mount (rise+fade) / unmount (fade) — all motion stripped under
//     prefers-reduced-motion.
//   • PERSISTENCE + TWO-WINDOW MIRROR (#638): a notice's shown/dismissed state lives in the
//     SAME 0064 layout store under a synthetic id ("notice:<id>"), reusing the per-field LWW
//     merge + the `layout-changed` fan-out — so a dismissal survives a reload, follows the
//     player across devices, and mirrors realtime between two windows (exactly as the window
//     kit owns geometry sync and the gadget kit owns collapse). localStorage stays the
//     per-device offline/seed fallback. `persistDismiss:false` opts a transient notice out
//     (a connection banner should reappear if the problem recurs — it is not "dismissed
//     forever").
//
// BRIGHT LINE: this kit is for AFFORDANCES/NOTIFICATIONS, never narration/messages. Chat
// messages (incl. the in-stream `.msg-system` connection-error bubble and the in-stream
// Continue buttons) stay in the chat stream via the renderer; the reasoning/reply channel
// split is untouched. New ABOVE-COMPOSER affordances MUST compose this kit (the convention
// gate test_on_notice_kit.py pins it — the notice edition of the F-3 window ratchet).
//
// Vault-free by construction: the kit only paints chrome + tracks a shown/dismissed bool —
// it never touches game state. g15: it NEVER dispatches `appkit:gamechanged` (the single
// dispatcher stays in platform.js); it only emits the layout-sync event (an allowed seam).

(function () {
  "use strict";

  // The single stacked container's id + the .on-* family.
  var ZONE_ID = "appkit-notice-zone";
  // The top system-banner host (a SEPARATE anchor for global outage signals — full-width,
  // position:fixed at the top of the viewport, NOT in the above-composer stack). Both
  // placements compose the SAME base (chrome/dismiss/a11y/animation/sync); only the anchor +
  // a few placement rules differ (#642 owner add-on).
  var BANNER_ID = "appkit-notice-banner";
  // The corner-toast host (#951) — a SEPARATE anchor for EPHEMERAL, auto-dismissing toasts
  // (the old `.toast` system: "Session archived", "Copied", an Undo affordance, etc.). Fixed at
  // the top-right corner of the viewport, OUT of the chat flow. Same .on-card chrome/icon/
  // dismiss/a11y/animation as every other notice — only the anchor, the slide-in axis, and the
  // auto-dismiss timer differ. This is what unifies the toast look onto the kit's `.on-*` family
  // (#951: all notifications share ONE chrome/icon/dismiss/motion/a11y contract).
  var TOAST_ID = "appkit-notice-toast";

  // Kind → ordering weight (lower mounts ABOVE, higher mounts at the BOTTOM, nearest the
  // composer). The decision card is the most action-demanding affordance, so it sits CLOSEST
  // to the composer (highest weight); the guide is the most ambient, so it floats to the top.
  // Several affordances present at once therefore stack in a DETERMINISTIC order, never
  // fighting for one slot. (Same kind ⇒ insertion order within the band.)
  var KIND_ORDER = { guide: 10, "system-notice": 20, continue: 30, decision: 40, toast: 25 };

  // aria-live per kind: the decision + a broken-engine system notice are consequential and
  // get an assertive announcement; the ambient guide + the Continue nudge are polite.
  var KIND_LIVE = {
    guide: "polite",
    "system-notice": "assertive",
    continue: "polite",
    decision: "assertive",
    // a toast is a brief confirmation/feedback line — polite (an error toast bumps to assertive
    // per its severity, mapped in _roleFor / the consumer; see ui.js showError).
    toast: "polite",
  };

  var REDUCED = function () {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  };

  // #764 — ONE consistent icon language for every notice + banner. The kit owns a single set of
  // Apple-style MONOCHROME glyphs (inline SVG, stroked in currentColor so they tint with the
  // severity, never a mix of full-colour emoji + text symbols). Consumers pass a SEMANTIC key via
  // the `icon` option (or none — a system-notice auto-derives its icon from `severity`), so the
  // icon language can never drift per-caller (the old bug: appkitEngineStatus baked "📡"/"⚠" into
  // the title string, so a colour emoji sat next to a mono symbol). An unknown `icon` string still
  // renders verbatim as text (back-compat for any bespoke glyph), but the named keys are the rule.
  // 20x20 viewBox, currentColor, aria-hidden (the title carries the meaning for SR/colour-blind).
  var _svg = function (paths) {
    return '<svg class="on-ic-svg" viewBox="0 0 20 20" width="1em" height="1em" fill="none" ' +
      'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" ' +
      'aria-hidden="true" focusable="false">' + paths + '</svg>';
  };
  var NOTICE_ICONS = {
    // a filled-circle "i" — neutral information
    info: _svg('<circle cx="10" cy="10" r="7.5"/><path d="M10 9v4.2"/><circle cx="10" cy="6.4" r=".4" fill="currentColor" stroke="none"/>'),
    // a triangle "!" — a warning / degraded state (amber tint via on-sev-warn)
    warn: _svg('<path d="M10 3.2 18 16.5H2L10 3.2Z"/><path d="M10 8.2v3.4"/><circle cx="10" cy="14.1" r=".5" fill="currentColor" stroke="none"/>'),
    // a circle "!" — an error / hard outage (red tint via on-sev-error)
    error: _svg('<circle cx="10" cy="10" r="7.5"/><path d="M10 6v4.6"/><circle cx="10" cy="13.6" r=".5" fill="currentColor" stroke="none"/>'),
    // a check-mark — a success confirmation (#951: the old toast's green check, now a mono glyph in
    // the kit's ONE icon language; the success colour is carried by the consumer's tint, not a glyph).
    success: _svg('<polyline points="4.5 10.5 8.5 14.5 15.5 6"/>'),
  };
  // system-notice / toast severity → icon key (a degraded/reconnecting banner reads as a warning, a
  // hard outage as an error; a toast success → check, error → error circle). One mapping, so every
  // notice/banner/toast shares the same icon family. (#951 adds the success key for toasts.)
  var SEVERITY_ICON = { info: "info", warn: "warn", error: "error", success: "success" };

  // #766 — ONLY ONE top banner may EVER be present. When a banner would overwrite another, severity
  // precedence decides: a higher-severity outage must never be silently clobbered by a low-priority
  // note. error/down (critical) > warn/degraded > info. Equal/higher ⇒ latest-wins (replace).
  var SEVERITY_RANK = { info: 1, warn: 2, error: 3 };
  function severityRank(sev) {
    return SEVERITY_RANK[sev] || SEVERITY_RANK.info;
  }

  // Resolve the icon HTML for a notice: an explicit named key wins; else a system-notice derives
  // it from severity; else nothing. Returns { html } for an SVG glyph, { text } for a raw glyph,
  // or null. (The raw-text branch keeps any bespoke caller glyph working unchanged.)
  function resolveIcon(opts) {
    var key = opts.icon;
    if (key && NOTICE_ICONS[key]) return { html: NOTICE_ICONS[key] };
    if (key) return { text: key };                       // a bespoke glyph string — render verbatim
    if (opts.kind === "system-notice" || opts.kind === "toast") {  // auto-derive from severity (banner/toast)
      var sk = SEVERITY_ICON[opts.severity || "info"];
      if (sk && NOTICE_ICONS[sk]) return { html: NOTICE_ICONS[sk] };
    }
    return null;
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ── the one CSS family ──────────────────────────────────────────────────────
  // Theme-token driven (the house themes 0052 + the frost layer paint it for free), with
  // literal fallbacks for before style.css loads — mirroring appkitWindow.js's ensureCss()
  // and appkitGadget.js's. Built by STRING CONCATENATION (never a backtick template) so a
  // stray backtick in a comment can't blow up the template literal (a prior PR's footgun).
  function ensureCss() {
    if (document.getElementById("on-notice-css")) return;
    var st = document.createElement("style");
    st.id = "on-notice-css";
    st.textContent =
      // The stacked container: a vertical column of notices anchored above the composer.
      // gap separates stacked affordances; it carries no chrome of its own (the cards do).
      "#" + ZONE_ID + " {" +
      "  display: flex; flex-direction: column; gap: var(--space-2, .45rem);" +
      "  margin: 0 auto var(--space-2, .45rem); width: 100%; max-width: 760px;" +
      "  pointer-events: none; }" +   // the column is inert; each card re-enables pointer events
      "#" + ZONE_ID + ":empty { display: none; margin: 0; }" +
      // A single notice card — the shared above-composer chrome. The visual language matches
      // the existing hand-rolled cards (panel bg, accent border, 12px radius, .85rem mono-ish
      // body) so a migrated affordance renders close to identically.
      ".on-card {" +
      "  position: relative; pointer-events: auto;" +
      "  border-radius: 12px; padding: .7rem .85rem;" +
      "  background: var(--panel, #111); color: var(--fg, #9cdef2);" +
      "  border: 1px solid var(--border, #355a66);" +
      // Shared type system (#709): sans family, body PRESET; the title row uses the title preset.
      "  font-family: var(--ow-ui-font); font-size: var(--ow-fs-body, .875rem); line-height: 1.5;" +
      "  box-shadow: var(--win-shadow, 0 8px 32px rgba(0,0,0,.45)); }" +
      // The header row: icon + title + the dismiss affordance.
      ".on-card .on-head { display: flex; align-items: baseline; gap: .5rem; }" +
      // #764: the icon is a MONOCHROME glyph (inline SVG in currentColor, or a bespoke text glyph).
      // Center it on the title's cap-height (the head is baseline-aligned) and size it to ~1.15em so
      // it reads as a peer of the title across the info/warn/error severities (which only retint it).
      ".on-card .on-icon { flex: 0 0 auto; opacity: .9; align-self: center; display: inline-flex;" +
      "  line-height: 0; font-size: 1.15em; }" +
      ".on-card .on-ic-svg { width: 1em; height: 1em; display: block; }" +
      ".on-card .on-title { flex: 1 1 auto; min-width: 0; font-size: var(--ow-fs-title, .875rem); font-weight: var(--ow-fw-semibold, 600); letter-spacing: -.01em; }" +
      ".on-card .on-body { margin-top: .35rem; }" +
      ".on-card .on-body:empty { display: none; }" +
      // The ONE dismiss affordance — the 44px touch floor (WCAG 2.5.5), positioned in the
      // top-right corner but kept LAST in DOM/tab order (the content comes first). It reuses
      // the look of the window kit's .ow-dismiss but is namespaced to the notice family.
      ".on-card .on-dismiss {" +
      "  position: absolute; top: .15rem; right: .2rem;" +
      "  min-width: 44px; min-height: 44px; padding: 0;" +
      "  display: inline-flex; align-items: center; justify-content: center;" +
      "  border: none; background: none; color: inherit; cursor: pointer;" +
      "  opacity: .65; border-radius: 8px; font: inherit; font-size: 1rem; }" +
      ".on-card .on-dismiss:hover, .on-card .on-dismiss:focus-visible {" +
      "  opacity: 1; background: rgba(255,255,255,.08); }" +
      // Make room for the corner × so a long title never slides under it.
      ".on-card .on-head { padding-right: 1.6rem; }" +
      // ── kind / severity skins ─────────────────────────────────────────────────
      // guide: the ambient, dashed, low-key orientation card (the premiere-tutorial look).
      ".on-card.on-guide {" +
      "  background: color-mix(in srgb, var(--fg, #9cdef2) 5%, transparent);" +
      "  border-style: dashed; border-color: color-mix(in srgb, var(--fg, #9cdef2) 30%, transparent);" +
      "  box-shadow: none; }" +
      // decision: the binding-decision card lifts off the stream (the accent border the
      // decision card already used). The risk skin for high-stakes kinds is layered by the
      // decision consumer via its own .odec-risk rules; the kit provides the base lift.
      ".on-card.on-decision { border-color: var(--accent, var(--red, #e06c75)); }" +
      // system-notice: an OOC operator signal. The severity tints carry the meaning; the icon
      // + title carry it for colorblind / SR users (color is never the only signal).
      ".on-card.on-system-notice { border-color: color-mix(in srgb, var(--fg, #9cdef2) 28%, transparent); }" +
      ".on-card.on-sev-warn {" +
      "  border-color: var(--color-warning, #f0ad4e);" +
      "  background: linear-gradient(0deg, color-mix(in srgb, var(--color-warning, #f0ad4e) 8%, transparent), color-mix(in srgb, var(--color-warning, #f0ad4e) 8%, transparent)), var(--panel, #111); }" +
      // CC-S2-4: tint the icon too (mirrors .on-sev-success .on-icon below) so a warn/error
      // notice reads as distinct from an info one on the glyph, not just the border/wash.
      ".on-card.on-sev-warn .on-icon { color: var(--color-warning, #f0ad4e); }" +
      ".on-card.on-sev-error {" +
      "  border-color: var(--color-error, var(--red, #e06c75));" +
      "  background: linear-gradient(0deg, color-mix(in srgb, var(--color-error, var(--red, #e06c75)) 10%, transparent), color-mix(in srgb, var(--color-error, var(--red, #e06c75)) 10%, transparent)), var(--panel, #111); }" +
      ".on-card.on-sev-error .on-icon { color: var(--color-error, var(--red, #e06c75)); }" +
      // success: a confirmation tint (the old toast's green check, now an .on-sev-* skin). Borders
      // green; the icon (check) tints with it. #951.
      ".on-card.on-sev-success { border-color: var(--green, #50fa7b); }" +
      ".on-card.on-sev-success .on-icon { color: var(--green, #50fa7b); }" +
      // toast: the ephemeral feedback card. Quiet by default (the accent left-edge the legacy toast
      // used), a left accent border so it reads as a peer of the old `.toast` look. #951.
      ".on-card.on-toast { border-left: 3px solid var(--accent, #e06c75); }" +
      // CC-S2-4: an error/warn TOAST looked identical to an info one — `.on-toast`'s
      // border-left above and `.on-sev-error`/`.on-sev-warn`'s border-color above it are
      // equal-specificity (two classes each), so whichever rule is LATER in this
      // stylesheet wins the cascade on the shared border-left-color, and `.on-toast`
      // (declared after) was clobbering the severity tint on exactly the edge users
      // notice most. These three-class overrides outrank both by specificity — order-
      // independent — so a severity toast's accent edge always reads as its own color.
      ".on-card.on-toast.on-sev-warn { border-left-color: var(--color-warning, #f0ad4e); }" +
      ".on-card.on-toast.on-sev-error { border-left-color: var(--color-error, var(--red, #e06c75)); }" +
      // continue: a quiet nudge to keep going.
      ".on-card.on-continue { border-color: color-mix(in srgb, var(--accent, #e06c75) 50%, var(--border, #355a66)); }" +
      // ── motion (reduced-motion stripped) ──────────────────────────────────────
      // mount: a gentle rise+fade; unmount: a fade. Both DRIVEN keyframes so the family
      // names the two motions. prefers-reduced-motion strips ALL of it.
      "@keyframes on-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }" +
      "@keyframes on-out { from { opacity: 1; transform: none; } to { opacity: 0; transform: translateY(4px); } }" +
      ".on-card.on-anim-in { animation: on-in .22s cubic-bezier(0.22,0.61,0.36,1) both; }" +
      ".on-card.on-anim-out { animation: on-out .2s ease both; }" +
      // ── top system-banner placement (#642 owner add-on) ───────────────────────
      // A global outage signal: full-width, fixed at the very top of the viewport, above
      // everything. Same .on-card chrome/dismiss/a11y/animation, different anchor. The host is
      // a thin fixed bar; the card inside spans it. The body padding-top compensation (so the
      // banner never occludes the chat top) is set by the JS via --on-banner-inset.
      "#" + BANNER_ID + " {" +
      "  position: fixed; top: 0; left: 0; right: 0; z-index: 11000;" +
      "  display: flex; flex-direction: column; pointer-events: none; }" +
      "#" + BANNER_ID + ":empty { display: none; }" +
      // A banner-placed card stretches edge-to-edge, squares its corners, and centres its row.
      "#" + BANNER_ID + " .on-card {" +
      "  border-radius: 0; border-left: none; border-right: none; border-top: none;" +
      "  box-shadow: 0 2px 10px rgba(0,0,0,.4); text-align: center;" +
      "  padding: .5rem 2.2rem .5rem .8rem; }" +   // room for the corner × on the right
      "#" + BANNER_ID + " .on-card .on-head { padding-right: 0; justify-content: center; align-items: center; }" +
      // Desktop: the banner respects the SAME side gutters the floating sidebar/dock do
      // (those float inset at left/right: 10px). So instead of bleeding true edge-to-edge,
      // inset the banner host by 10px on both sides and re-round / re-border the now-detached
      // side+bottom edges (top stays flush with the viewport top). Mobile keeps it full-bleed.
      "@media (min-width: 769px) {" +
      "  #" + BANNER_ID + " { left: 10px; right: 10px; }" +
      "  #" + BANNER_ID + " .on-card {" +
      "    border-left: 1px solid var(--border, #355a66); border-right: 1px solid var(--border, #355a66);" +
      "    border-bottom: 1px solid var(--border, #355a66);" +
      "    border-radius: 0 0 var(--ow-glass-radius, 14px) var(--ow-glass-radius, 14px); } }" +
      // The banner's slide-down entrance (reduced-motion stripped with the rest).
      "@keyframes on-banner-in { from { opacity: 0; transform: translateY(-100%); } to { opacity: 1; transform: none; } }" +
      ".on-card.on-anim-banner-in { animation: on-banner-in .22s ease-out both; }" +
      // ── corner-toast placement (#951) ─────────────────────────────────────────
      // The unified ephemeral-toast surface: the OLD `.toast` system, restyled onto the kit's
      // `.on-card` chrome so a success/error/undo toast shares the SAME icon + dismiss + a11y +
      // motion contract as every banner/notice. A fixed top-right host holding ≤1 card (one toast
      // at a time, like the old singleton #toast). Slides in from the RIGHT (matching the legacy
      // toast motion), auto-dismisses on a timer, OUT of the chat flow.
      "#" + TOAST_ID + " {" +
      "  position: fixed; top: 16px; right: 16px; left: auto; bottom: auto; z-index: 11000;" +
      "  display: flex; flex-direction: column; align-items: flex-end; pointer-events: none;" +
      "  max-width: min(360px, calc(100vw - 32px)); }" +
      "#" + TOAST_ID + ":empty { display: none; }" +
      // The toast card is a compact .on-card: a tighter row, a min size matching the old toast, and
      // its own slide-from-right entrance/exit (the zone uses rise+fade; the banner slides down).
      "#" + TOAST_ID + " .on-card {" +
      "  min-width: min(220px, calc(100vw - 32px)); max-width: 100%;" +
      "  padding: .55rem .75rem; }" +
      // A toast with NO title (the common case — just a message line) collapses the header row so the
      // message body leads; the icon (if any) floats beside it.
      "#" + TOAST_ID + " .on-card .on-head:has(.on-title:empty) { margin: 0; }" +
      "#" + TOAST_ID + " .on-card .on-body { margin-top: 0; }" +
      // The toast slide-in (from the right) + slide-out (to the left) — mirrors the legacy toast.
      "@keyframes on-toast-in { from { opacity: 0; transform: translateX(120%); } to { opacity: 1; transform: none; } }" +
      "@keyframes on-toast-out { from { opacity: 1; transform: none; } to { opacity: 0; transform: translateX(-120%); } }" +
      ".on-card.on-anim-toast-in { animation: on-toast-in .35s cubic-bezier(0.22,1,0.36,1) both; }" +
      ".on-card.on-anim-toast-out { animation: on-toast-out .3s cubic-bezier(0.22,1,0.36,1) both; }" +
      // Mobile: the host receives touches so the swipe-to-dismiss gesture works (desktop stays
      // pointer-events:none so a toast never blocks clicks; the card itself re-enables them).
      "@media (max-width: 768px) {" +
      "  #" + TOAST_ID + " { top: 12px; right: 12px; max-width: calc(100vw - 24px); }" +
      "  #" + TOAST_ID + " .on-card { pointer-events: auto; touch-action: pan-x; } }" +
      "@media (prefers-reduced-motion: reduce) {" +
      "  .on-card.on-anim-in, .on-card.on-anim-out, .on-card.on-anim-banner-in," +
      "  .on-card.on-anim-toast-in, .on-card.on-anim-toast-out { animation: none; } }" +
      // ── LIQUID GLASS (body.theme-frosted) ──────────────────────────────────────
      // Under the glass theme the notice card reads as the SAME ONE LIGHT GLASS as the
      // windows/sidebar — the kube music-player light fill. style.css now paints that light
      // glass for `body.theme-frosted .on-card` on BOTH tiers (Full = SVG refraction, Frosted
      // = CSS blur). Owner ruling: "there should be no old dark glass at all"; "the old dark
      // glass shouldn't be the frosted fallback". So the inline DARK-veil glass that used to
      // live here (and made the FROSTED fallback dark) is RETIRED — it must NOT re-introduce a
      // dark fill on top of the style.css light glass.
      //
      // The ONLY thing the static light-glass rule does NOT beat are the kit's OWN, more-
      // specific SOLID-bg skins (.on-sev-warn / .on-sev-error layer a solid var(--panel) wash;
      // .on-guide layers a faint solid wash + box-shadow:none). So we NEUTRALIZE just those
      // skins' solid backgrounds under theme-frosted (let the style.css light glass show
      // through); the severity/kind MEANING stays in the BORDER only (no accent-hued TEXT, no
      // solid fill). Applies to BOTH tiers (no :not(.glass-full) scope — the fill is uniform).
      // Wrapped in prefers-reduced-transparency:no-preference so these runtime-injected rules
      // (appended AFTER the linked stylesheet) NEVER override style.css's a11y OPAQUE fallback
      // under prefers-reduced-transparency:reduce.
      "@media (prefers-reduced-transparency: no-preference) {" +
      "body.theme-frosted .on-card.on-guide," +
      "body.theme-frosted .on-card.on-sev-warn," +
      "body.theme-frosted .on-card.on-sev-error {" +
      // Replace the skins' SOLID --panel fill with the ONE LIGHT GLASS (the kube fill, the same
      // tokens style.css paints on .on-card) so the skinned cards match the rest of the kit — NO
      // dark veil. The severity/kind MEANING stays in the BORDER (set by the skins above).
      "  background-color: var(--ow-glass-light-color) !important;" +
      "  background-image: var(--ow-glass-light-fill) !important; }" +
      // #725 SMUDGE FIX: post-#725 the notice card carries DARK ink on the LIGHT glass (style.css
      // dark-ink chrome list). The dark --ow-glass-text-shadow under dark ink reads as a dirty drop-
      // shadow SMUDGE; the correct legibility halo on dark-on-light is a LIGHT halo (matches the
      // style.css .on-card rule). This runtime rule is appended AFTER the stylesheet, so it must
      // itself carry the light halo or it re-introduces the smudge. (The dark shadow stays only on
      // genuinely light-on-dark text — chat bubbles, dock chips — which the notice card is NOT.)
      "body.theme-frosted .on-card { text-shadow: 0 1px 1px rgba(255,255,255,0.5); } }";
    document.head.appendChild(st);
  }

  // ── per-notice shown/dismissed state, synced (#638) ─────────────────────────
  // Mirrors the gadget kit's collapse-sync + the premiere-popup dismiss precedent: the SYNCED
  // value (the 0064 layout store, LWW, mirrored via `layout-changed`) is the source of truth;
  // localStorage is the per-device offline/seed fallback. The synthetic window id is
  // "notice:<id>" (windows use the bare id, gadgets "gadget:<id>", popups "popup:<id>").
  function syncId(id) { return "notice:" + id; }
  function dismissKey(id) {
    return "appkit-notice-dismissed:" + id + ":" + ((document.body && document.body.dataset.user) || "");
  }
  function loadDismissed(id) {
    try { return localStorage.getItem(dismissKey(id)) === "1"; } catch (_) { return false; }
  }
  function saveDismissed(id, applyingRemote) {
    try { localStorage.setItem(dismissKey(id), "1"); } catch (_) {}
    // Emit through the SAME capture event the window + gadget kits use — no parallel sync.
    // Suppressed while APPLYING a remote change (no echo loop). appkitLayoutSync debounces a
    // PATCH /api/appkit/layout; absent module ⇒ localStorage-only, fail-open.
    if (applyingRemote) return;
    try {
      window.dispatchEvent(new CustomEvent("appkit:window-layout",
        { detail: { id: syncId(id), state: { dismissed: true } } }));
    } catch (_) {}
  }

  // A live registry of mounted kit notices by id, so a synced dismiss arriving from the seed
  // (initial GET /layout) or a peer window (`layout-changed`) can reach the notice.
  var _byId = {};
  function _onSyncedLayout(e) {
    var d = e && e.detail;
    if (!d || !d.windowId || !d.state) return;
    if (String(d.windowId).indexOf("notice:") !== 0) return;
    var id = String(d.windowId).slice("notice:".length);
    if (d.state.dismissed === true) {
      // Remember it even if the notice isn't mounted right now, so a later show() honors it.
      try { localStorage.setItem(dismissKey(id), "1"); } catch (_) {}
      var n = _byId[id];
      if (n) n._applyRemoteDismiss();
    }
  }
  window.addEventListener("appkit:layout-seed", _onSyncedLayout);     // initial GET /layout
  window.addEventListener("appkit:layout-changed", _onSyncedLayout);  // a peer window / device

  // The single stacked container, created lazily above the composer. Fallback chain
  // (.chat-input-bar → #chat-bar → body) so a degraded/headless DOM still works.
  function ensureZone() {
    var zone = document.getElementById(ZONE_ID);
    if (zone) return zone;
    ensureCss();
    zone = document.createElement("div");
    zone.id = ZONE_ID;
    // The zone itself is a passive container; each card owns its own role/aria-live.
    var bar = document.querySelector(".chat-input-bar") || document.getElementById("chat-bar");
    if (bar && bar.parentNode) bar.parentNode.insertBefore(zone, bar);
    else document.body.appendChild(zone);
    return zone;
  }

  // The top system-banner host (a fixed full-width bar at the top of the viewport). Created
  // lazily on body. A SEPARATE anchor from the above-composer zone — same base chrome.
  //
  // #766 — the host holds EXACTLY ≤1 banner card (show() replaces any existing one; never stacks),
  // so the inset is simply that one card's height.
  // #758b — the reserved inset must still track that card's LIVE height: it changes for reasons no
  // show()/update()/hide() call catches — the copy wraps to more lines when the viewport WIDTH
  // shrinks, or the web-font swaps in late (font-display:swap) and re-wraps — and a stale inset let
  // the banner overlap content. A ResizeObserver on the host re-runs setBannerInset on EVERY
  // rendered-height change, so the inset always matches the live banner (and clears when it's gone).
  function ensureBannerHost() {
    var host = document.getElementById(BANNER_ID);
    if (host) return host;
    ensureCss();
    host = document.createElement("div");
    host.id = BANNER_ID;
    document.body.appendChild(host);
    if (typeof ResizeObserver !== "undefined") {
      try {
        new ResizeObserver(function () {
          // Re-measure on any height change; when the host has emptied (last banner gone) release
          // the inset entirely so we never leave phantom padding behind.
          if (host.children.length) setBannerInset(host);
          else clearBannerInset();
        }).observe(host);
      } catch (_) {}
    }
    return host;
  }

  // The corner-toast host (#951) — a fixed top-right bar holding the SINGLE live toast card. A
  // SEPARATE anchor from the above-composer zone and the top banner; same base chrome. Created
  // lazily on body. position:fixed so it never participates in the chat flow (no body inset — a
  // toast is transient and small, unlike the top banner which reserves height).
  function ensureToastHost() {
    var host = document.getElementById(TOAST_ID);
    if (host) return host;
    ensureCss();
    host = document.createElement("div");
    host.id = TOAST_ID;
    document.body.appendChild(host);
    return host;
  }

  // Body-inset compensation: a top banner is position:fixed, so without compensation it occludes
  // the top of the chat (worst exactly when connectivity is degraded). Reserve its height as body
  // padding-top while shown, release it when gone. A CSS var carries the value (a reduced-motion-
  // safe transition can hook it later). Mirrors the old appkitEngineStatus --oes-inset behaviour.
  // #758b: measure via getBoundingClientRect (sub-pixel, the SAME box the FE consumers read) and
  // round UP, so a fractional line-height can never leave a 1px sliver of banner over the content.
  function setBannerInset(host) {
    try {
      var rect = host && host.getBoundingClientRect ? host.getBoundingClientRect() : null;
      var h = rect ? Math.ceil(rect.height) : ((host && host.offsetHeight) || 0);
      document.body.style.setProperty("--on-banner-inset", h + "px");
      document.body.style.paddingTop = h + "px";
      _emitBannerInset(h);
    } catch (_) {}
  }
  function clearBannerInset() {
    try {
      document.body.style.removeProperty("--on-banner-inset");
      document.body.style.paddingTop = "";
      _emitBannerInset(0);
    } catch (_) {}
  }
  // #758: a top banner is position:fixed, so the body padding-top above only re-flows the
  // IN-FLOW content (the chat column + the relative-flow desktop sidebar/rail). The FIXED-chrome
  // layer (kit windows + the slot engine, the mobile rail/sidebar drawers, the top corner
  // controls) must ALSO reserve the banner's height and COMPRESS below it — they read
  // --on-banner-inset, but a CSS-var change fires no event, so broadcast a tiny window signal on
  // every set/clear. The window kit's slot/clamp math + the gadget rail listen for it and re-place
  // (resize already covers the height-change path; this covers banner show/hide and copy changes).
  function _emitBannerInset(h) {
    try {
      window.dispatchEvent(new CustomEvent("appkit:banner-inset", { detail: { inset: h } }));
    } catch (_) {}
  }

  // Insert `card` into the zone at the DETERMINISTIC position for its kind weight (lower
  // weight = higher up; equal weight = insertion order). One stacking authority — no
  // affordance picks its own neighbour.
  function insertByOrder(zone, card, weight) {
    card.dataset.onOrder = String(weight);
    var children = zone.children;
    for (var i = 0; i < children.length; i++) {
      var w = parseInt(children[i].dataset.onOrder || "0", 10);
      if (weight < w) { zone.insertBefore(card, children[i]); return; }
    }
    zone.appendChild(card);
  }

  function AppkitNotice(opts) {
    if (!(this instanceof AppkitNotice)) return new AppkitNotice(opts);
    this.o = Object.assign({
      // id        — stable per-notice id (the element id + the "notice:<id>" sync id).
      // kind       — guide | decision | system-notice | continue (drives skin/order/aria-live).
      // title      — the heading text.
      // icon       — a decorative glyph before the title (aria-hidden).
      // severity   — info | warn | error (an extra tint on system-notice; default info).
      // role       — the card's ARIA role (default per kind: 'note' for guide/continue,
      //              'form' for decision, 'alert' for system-notice).
      // dismissible (default true) — render the × dismiss affordance.
      // persistDismiss (default true) — persist + sync the dismissal (notice:<id>, #638). A
      //              transient notice (a connection banner) sets false so it reappears if the
      //              problem recurs and never writes a "dismissed forever" bit.
      // onDismiss(reason) — fired after a dismiss ('user' | 'remote' | 'api').
      // placement — "above-composer" (default, the stacked zone above the composer),
      //              "top-banner" (a full-width fixed bar at the top of the viewport, for a
      //              GLOBAL outage signal — same base chrome/dismiss/a11y/anim/sync, different
      //              anchor; reserves body padding-top so it never occludes the chat), #642, or
      //              "toast" (#951: a fixed top-right corner card for an EPHEMERAL, auto-dismissing
      //              confirmation/feedback toast — same base chrome/icon/dismiss/a11y, a slide-from-
      //              right entrance, an auto-dismiss timer, and swipe-to-dismiss on touch).
      // autoDismissMs — for a toast (or any notice): auto-dismiss after N ms (0/undefined ⇒ none).
      //              A toast is ephemeral, so showToast/showError set this; a banner never does.
      kind: "guide",
      severity: "info",
      dismissible: true,
      persistDismiss: true,
      placement: "above-composer",
      autoDismissMs: 0,
      onDismiss: null,
    }, opts || {});
    // id is required; title is optional (a hint is just a text line, a banner sets it via update()).
    if (!this.o.id) throw new Error("AppkitNotice needs an id");
    if (this.o.title == null) this.o.title = "";
    this.el = null;
    this.head = null;
    this.body = null;
    this._applyingRemote = false;
  }

  AppkitNotice.prototype._roleFor = function () {
    if (this.o.role) return this.o.role;
    if (this.o.kind === "decision") return "form";
    if (this.o.kind === "system-notice") return "alert";
    // #951: an error/warn toast is a consequential status → role=alert; a plain/success toast is a
    // passive confirmation → role=status (a polite live region).
    if (this.o.kind === "toast") {
      return (this.o.severity === "error" || this.o.severity === "warn") ? "alert" : "status";
    }
    return "note";
  };

  // The aria-live politeness for this notice. Per kind by default; a toast escalates to assertive
  // for error/warn severities (matching its role), polite otherwise. #951.
  AppkitNotice.prototype._liveFor = function () {
    if (this.o.kind === "toast") {
      return (this.o.severity === "error" || this.o.severity === "warn") ? "assertive" : "polite";
    }
    return KIND_LIVE[this.o.kind] || "polite";
  };

  // #764: render (or refresh, or remove) the leading icon from the kit's ONE monochrome set —
  // an explicit semantic key, else severity-derived for a system-notice. Idempotent: it reuses
  // the existing .on-icon node, creates it as the FIRST child of .on-head when newly needed, and
  // removes it when the resolution yields nothing. No-op if the head isn't built yet.
  AppkitNotice.prototype._renderIcon = function () {
    var head = this.head;
    if (!head) return;
    var spec = resolveIcon(this.o);
    var ic = head.querySelector(".on-icon");
    if (!spec) { if (ic) ic.remove(); return; }
    if (!ic) {
      ic = document.createElement("span");
      ic.className = "on-icon"; ic.setAttribute("aria-hidden", "true");
      head.insertBefore(ic, head.firstChild);   // lead the title row
    }
    if (spec.html) ic.innerHTML = spec.html; else { ic.textContent = spec.text; }
  };

  AppkitNotice.prototype._build = function () {
    ensureCss();
    var kind = this.o.kind;
    var el = document.createElement("section");
    el.id = this.o.id;
    el.className = "on-card on-" + kind +
      ((kind === "system-notice" || kind === "toast") && this.o.severity ? " on-sev-" + this.o.severity : "");
    el.setAttribute("data-on-notice", "");
    el.setAttribute("data-on-kind", kind);
    el.setAttribute("role", this._roleFor());
    if (this.o.title) el.setAttribute("aria-label", this.o.title);
    // aria-live per kind — a consequential notice announces assertively; an ambient one politely.
    // #951: a toast bumps to assertive when its severity is error/warn (an error toast is
    // consequential), polite otherwise — so the spoken urgency tracks the severity.
    el.setAttribute("aria-live", this._liveFor());

    var head = document.createElement("div");
    head.className = "on-head";
    this.head = head;
    // #764: the icon comes from the kit's ONE monochrome set (semantic key or severity-derived),
    // never a baked-in title glyph — so every notice + banner shares one icon language. Rendered
    // FIRST so it leads the title row (the helper prepends into .on-head).
    this._renderIcon();
    // A titled notice gets a heading; a title-less one (a hint) just keeps an empty head row
    // (its content lives in the body). update() can fill the title later (the banner pattern).
    var title = document.createElement("span");
    title.className = "on-title";
    title.setAttribute("role", "heading");
    title.setAttribute("aria-level", "3");
    title.textContent = this.o.title;
    head.appendChild(title);

    var body = document.createElement("div");
    body.className = "on-body";

    el.appendChild(head);
    el.appendChild(body);

    // The ONE dismiss affordance, appended LAST (so it is the final tab stop — content first,
    // WCAG 2.4.3). CSS positions it back into the corner. Decisions are HARD-STOP: still
    // dismissible (the player may decide in conversation instead), but NEVER auto-dismissed.
    if (this.o.dismissible) {
      var x = document.createElement("button");
      x.type = "button"; x.className = "on-dismiss";
      x.textContent = "×";
      x.title = "Dismiss";
      x.setAttribute("aria-label", "Dismiss — " + this.o.title);
      var self = this;
      x.addEventListener("click", function () { self.dismiss("user"); });
      el.appendChild(x);
      this.dismissBtn = x;
    }

    this.el = el; this.head = head; this.body = body;
    return el;
  };

  AppkitNotice.prototype._isBanner = function () { return this.o.placement === "top-banner"; };
  AppkitNotice.prototype._isToast = function () { return this.o.placement === "toast"; };

  // Arm (or re-arm) the auto-dismiss timer for an ephemeral notice/toast. A no-op when
  // autoDismissMs is falsy. Cleared on dismiss/hide so a re-shown card never double-fires.
  AppkitNotice.prototype._armAutoDismiss = function () {
    this._clearAutoDismiss();
    var ms = this.o.autoDismissMs;
    if (!ms) return;
    var self = this;
    this._autoTimer = setTimeout(function () {
      self._autoTimer = null;
      // A toast is transient: it auto-hides WITHOUT persisting a dismissal (persistDismiss:false),
      // so the same id can show again next time. hide() is the no-persist exit.
      self.hide();
    }, ms);
  };
  AppkitNotice.prototype._clearAutoDismiss = function () {
    if (this._autoTimer) { clearTimeout(this._autoTimer); this._autoTimer = null; }
  };

  // Wire swipe-to-dismiss on a toast card (touch only — desktop uses the × / auto-dismiss). Mirrors
  // the legacy ui.js _wireToastSwipe: a horizontal drag past the threshold flings the card off and
  // hides it early; less snaps back. Runs once per card.
  AppkitNotice.prototype._wireSwipe = function () {
    var el = this.el;
    if (!el || el._onSwipeWired) return;
    el._onSwipeWired = true;
    var self = this, DISMISS_PX = 70, startX = 0, curX = 0, swiping = false;
    el.addEventListener("touchstart", function (e) {
      var t = e.touches && e.touches[0]; if (!t) return;
      startX = curX = t.clientX; swiping = true;
      el.style.transition = "none";
    }, { passive: true });
    el.addEventListener("touchmove", function (e) {
      if (!swiping) return;
      var t = e.touches && e.touches[0]; if (!t) return;
      curX = t.clientX; var dx = curX - startX;
      el.style.transform = "translateX(" + dx + "px)";
      el.style.opacity = String(Math.max(0.2, 1 - Math.abs(dx) / 200));
    }, { passive: true });
    var end = function () {
      if (!swiping) return; swiping = false;
      var dx = curX - startX; el.style.transition = "";
      if (Math.abs(dx) > DISMISS_PX) {
        el.style.transform = "translateX(" + (dx > 0 ? "120%" : "-120%") + ")";
        el.style.opacity = "0";
        self._clearAutoDismiss();
        setTimeout(function () { self.hide(); }, 180);
      } else { el.style.transform = ""; el.style.opacity = ""; }
    };
    el.addEventListener("touchend", end);
    el.addEventListener("touchcancel", end);
  };

  // Mount the notice into its anchor (the stacked above-composer zone, or the top banner host).
  // Honors a persisted/synced dismissal: a notice the player dismissed before (and that persists)
  // won't re-mount. Idempotent.
  AppkitNotice.prototype.show = function () {
    if (this.o.persistDismiss && loadDismissed(this.o.id)) return null;
    // A toast already up just re-arms its timer (a re-show with fresh content keeps the same card,
    // no flicker) — the consumer (showToast) refreshes the body/icon before calling show().
    if (this.el && this.el.isConnected) {
      if (this._isToast()) { this._armAutoDismiss(); }
      return this.el;
    }
    var el = this.el || this._build();
    var self = this;
    if (this._isToast()) {
      // #951: the unified ephemeral toast. A SINGLE corner host holding ≤1 card (the legacy toast
      // was a singleton element). Replace any existing toast card (latest-wins — a toast is the most
      // recent feedback line), slide in from the right, arm the auto-dismiss timer, wire swipe.
      var thost = ensureToastHost();
      var prior = thost.firstElementChild;
      if (prior && prior !== el) {
        var priorNotice = _byId[prior.id];
        if (priorNotice && typeof priorNotice.hide === "function") priorNotice.hide();
        else prior.remove();
        while (thost.firstElementChild && thost.firstElementChild !== el) thost.firstElementChild.remove();
      }
      thost.appendChild(el);
      _byId[this.o.id] = this;
      this._wireSwipe();
      if (!REDUCED()) {
        el.classList.add("on-anim-toast-in");
        el.addEventListener("animationend", function handler() {
          el.classList.remove("on-anim-toast-in");
          el.removeEventListener("animationend", handler);
        }, { once: true });
      }
      this._armAutoDismiss();
      return el;
    }
    if (this._isBanner()) {
      var host = ensureBannerHost();
      // #766 — ONLY ONE top banner may EVER be present. If another notice's banner card is already
      // mounted in the host, the new one REPLACES it (never stack) — but a lower-severity note must
      // not silently clobber a higher-severity outage. Compare the incoming severity to the existing
      // card's: incoming rank ≥ existing ⇒ replace (latest-wins at equal rank); strictly lower ⇒
      // refuse (keep the critical banner up). The host therefore holds exactly ≤1 card, always.
      var existing = host.firstElementChild;
      if (existing && existing !== el) {
        var existingNotice = _byId[existing.id];
        var existingRank = existingNotice ? severityRank(existingNotice.o.severity) : 0;
        if (severityRank(this.o.severity) < existingRank) {
          return null;  // a lower-priority banner never displaces a higher-severity outage
        }
        // Replace: tear the current banner down (its own hide() path clears _byId + the inset) so
        // there is never a moment with two cards in the host.
        if (existingNotice && typeof existingNotice.hide === "function") existingNotice.hide();
        else existing.remove();
        // hide() may animate-out asynchronously; force-remove any leftover so the host is empty now.
        while (host.firstElementChild && host.firstElementChild !== el) host.firstElementChild.remove();
      }
      host.appendChild(el);
      _byId[this.o.id] = this;
      if (!REDUCED()) {
        el.classList.add("on-anim-banner-in");
        el.addEventListener("animationend", function handler() {
          el.classList.remove("on-anim-banner-in");
          el.removeEventListener("animationend", handler);
        }, { once: true });
      }
      setBannerInset(host);   // reserve its height so it never occludes the chat top
      return el;
    }
    var zone = ensureZone();
    insertByOrder(zone, el, KIND_ORDER[this.o.kind] != null ? KIND_ORDER[this.o.kind] : 50);
    _byId[this.o.id] = this;
    if (!REDUCED()) {
      el.classList.add("on-anim-in");
      el.addEventListener("animationend", function handler() {
        el.classList.remove("on-anim-in");
        el.removeEventListener("animationend", handler);
      }, { once: true });
    }
    return el;
  };

  // Ensure built + mounted; return the .on-body for the consumer to fill with its own content.
  AppkitNotice.prototype.ensure = function () {
    this.show();
    return this.body;
  };

  // Set the body content (string ⇒ innerHTML for trusted author markup; Node ⇒ append).
  AppkitNotice.prototype.setBody = function (content) {
    if (!this.body) this._build();
    if (content instanceof Node) { this.body.innerHTML = ""; this.body.appendChild(content); }
    else this.body.innerHTML = content == null ? "" : String(content);
    return this;
  };

  AppkitNotice.prototype.isShown = function () {
    return !!(this.el && this.el.isConnected);
  };

  // Re-skin a live notice in place (title / severity / body) without a remount — used by a
  // long-lived banner that transitions between states (down → reconnecting → holding). Keeps
  // the same element (no flicker), updates the severity tint + aria-label, and re-measures the
  // body inset for a banner (its height may change with the copy). #642.
  AppkitNotice.prototype.update = function (patch) {
    patch = patch || {};
    if (!this.el) this._build();
    var iconDirty = false;
    // #951: severity tinting applies to a system-notice (the banner) AND a toast (an error toast
    // reads red, a success toast green) — both wear the .on-sev-* skins. Other kinds ignore it.
    if (patch.severity != null && (this.o.kind === "system-notice" || this.o.kind === "toast")) {
      this.el.classList.remove("on-sev-info", "on-sev-warn", "on-sev-error", "on-sev-success");
      this.o.severity = patch.severity;
      this.el.classList.add("on-sev-" + patch.severity);
      iconDirty = true;   // #764: a system-notice's icon is severity-derived — refresh it too
      // #951: a toast's role/aria-live track severity (error/warn → alert/assertive) — keep them
      // in sync when a reused toast card switches between a success line and an error line.
      if (this.o.kind === "toast" && !this.o.role) {
        this.el.setAttribute("role", this._roleFor());
        this.el.setAttribute("aria-live", this._liveFor());
      }
    }
    if (patch.title != null) {
      this.o.title = patch.title;
      var t = this.el.querySelector(".on-title");
      if (t) t.textContent = patch.title;
      this.el.setAttribute("aria-label", patch.title);
      if (this.dismissBtn) this.dismissBtn.setAttribute("aria-label", "Dismiss — " + patch.title);
    }
    if (patch.icon != null) { this.o.icon = patch.icon; iconDirty = true; }
    // #764: re-render the icon from the kit's ONE monochrome set (explicit key, else severity-
    // derived) so a state transition (degraded → down) keeps a consistent icon language — never a
    // baked-in title glyph. Creates the .on-icon node if the notice had none before.
    if (iconDirty) this._renderIcon();
    if (patch.body != null) this.setBody(patch.body);
    if (this._isBanner() && this.el.isConnected) {
      var host = document.getElementById(BANNER_ID);
      if (host) setBannerInset(host);
    }
    return this;
  };

  // Remove the notice from the zone WITHOUT persisting a dismissal (a content gate closing it,
  // e.g. the premiere week ending). reduced-motion-safe fade-out.
  AppkitNotice.prototype.hide = function () {
    this._clearAutoDismiss();   // #951: a manual/swipe hide cancels any pending auto-dismiss
    var el = this.el;
    if (!el || !el.isConnected) { if (this.el === el) this.el = null; return; }
    var self = this;
    var banner = this._isBanner();
    var done = function () {
      if (el.isConnected) el.remove();
      delete _byId[self.o.id];
      // Release the reserved top-banner space once the banner is gone (no other banner card up).
      if (banner) {
        var host = document.getElementById(BANNER_ID);
        if (!host || !host.children.length) clearBannerInset();
      }
    };
    if (REDUCED()) { done(); return; }
    // The toast slides off to the LEFT (its own keyframe), matching the legacy toast exit; every
    // other placement uses the shared fade-out.
    el.classList.add(this._isToast() ? "on-anim-toast-out" : "on-anim-out");
    el.addEventListener("animationend", done, { once: true });
    setTimeout(done, 260);  // belt: fire even if animationend is missed
  };

  // Dismiss: hide AND (when persisting) record + sync the dismissal so it survives a reload,
  // crosses devices, and mirrors between two windows (#638). reason ∈ {'user','remote','api'}.
  AppkitNotice.prototype.dismiss = function (reason) {
    if (this.o.persistDismiss) saveDismissed(this.o.id, this._applyingRemote);
    this.hide();
    if (typeof this.o.onDismiss === "function") {
      try { this.o.onDismiss(reason || "user"); } catch (_) {}
    }
  };

  // Apply a dismiss arriving from another device / window (or the seed). Sets _applyingRemote
  // so the resulting state change doesn't re-emit (no echo loop) — but DOES land in localStorage.
  AppkitNotice.prototype._applyRemoteDismiss = function () {
    this._applyingRemote = true;
    try { this.dismiss("remote"); } finally { this._applyingRemote = false; }
  };

  // The seam every consumer + the convention gate use (mirrors window.AppkitWindowKit /
  // window.AppkitGadgetKit).
  window.AppkitNoticeKit = {
    create: function (opts) { return new AppkitNotice(opts); },
    esc: esc,
    // expose the zone ensurer for consumers that need the anchor directly (rare).
    ensureZone: ensureZone,
  };
  window.AppkitNotice = AppkitNotice;
})();
