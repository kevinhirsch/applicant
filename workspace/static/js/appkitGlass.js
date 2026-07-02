// appkitGlass.js — Liquid Glass SVG-refraction + Adaptive Glass legibility kit (FR-UIKIT-1).
// Bundled from two modules: the SVG-refraction engine (Chromium-only, progressive enhancement)
// and the adaptive legibility layer (runs on every engine).
// See style.css (`body.theme-frosted` / `body.glass-full`) for the CSS glass-tier
// classes — theme.js `applyGlassTier` is the sole writer of both.

// liquidGlass.js — real SVG-refraction "liquid glass" as a PROGRESSIVE-ENHANCEMENT
// layer over the shipped CSS blur-glass baseline (body.theme-frosted .ow-window etc.).
//
// Technique (adapted from https://kube.io/blog/liquid-glass-css-svg/): an SVG
// <filter> with <feImage href="<displacement-map dataURL>"> feeding a
// <feDisplacementMap in="SourceGraphic" in2="…" xChannelSelector="R"
// yChannelSelector="G" scale=N>. The displacement map is a generated RGBA image
// whose R channel encodes x-displacement and G channel encodes y-displacement
// (128 = neutral). It ramps near the rounded-rect EDGES with a SQUIRCLE edge
// profile so the backdrop bends/lenses at the perimeter and stays neutral
// (undistorted, crisp) in the center. Applied via
//   backdrop-filter: url(#id) blur(...) saturate(...)
// so the refraction composites over whatever is behind the surface.
//
// ── HARD CONSTRAINT: Chromium-only ───────────────────────────────────────────
// SVG-filter backdrop-filter is supported ONLY by Chrome/Chromium. Everywhere
// else this module is a NO-OP and the shipped CSS blur-glass (style.css
// body.theme-frosted rules) stands unchanged — the documented graceful fallback.
// We feature-detect BOTH `CSS.supports('backdrop-filter','url(#x)')` AND a
// Chromium engine check (Firefox/Safari report partial support but do NOT honor
// an SVG-filter reference in backdrop-filter), and bail on anything else.
//
// ── PERF POSTURE (this is GPU-heavy) ─────────────────────────────────────────
//   • One displacement map is GENERATED PER UNIQUE SIZE (Wx Hx R bucket, rounded
//     to a coarse grid) and SHARED by every same-size surface — not one per
//     element. Filters are cached by that bucket key, so N windows of the same
//     size cost ONE map + ONE filter.
//   • Element count is CAPPED (MAX_LIVE_SURFACES). The big draggable windows, the
//     composer and the sidebar take priority; the small gadget cards (.og-card)
//     are refracted only if there is headroom under the cap (they share size
//     buckets, so a rail of identical cards is cheap).
//   • Size changes are watched with ONE shared, debounced ResizeObserver — never
//     a poll. A debounce (RESIZE_DEBOUNCE_MS) coalesces a resize-drag burst into
//     a single re-map.
//   • prefers-reduced-motion: we never ANIMATE the scale (the effect is static
//     refraction, no motion), and on reduced-motion we additionally DROP the
//     scale to a calmer value so the lensing is gentle. Fully fail-soft: any
//     error anywhere leaves the CSS blur-glass in place.
//   • Active ONLY under body.glass-full (the Full Glass tier: theme-frosted +
//     glass-full). The Frosted tier (theme-frosted alone) gets the CSS glass
//     material but NOT the Chromium SVG refraction, which gates on glass-full.
//     A tier/theme change is
//     observed via a MutationObserver on <body class> (no new event needed — this
//     respects the g15 "one appkit:gamechanged dispatcher" rule; we add no
//     CustomEvent of our own).

(function () {
  "use strict";

  // ── Tunable constants (top-of-file, per the brief) ──────────────────────────
  // SCALE      — px of MAX edge displacement (feDisplacementMap `scale`). Higher
  //              = stronger lensing at the rim. The article's sweet spot is modest;
  //              we keep it low so center text never smears.
  // RADIUS     — corner radius (px) the squircle profile is built around; tracks the
  //              Apple-tuned --ow-glass-radius (style.css, now 26px — bumped from the
  //              22px this was originally tuned against, "very rounded, Apple") so the
  //              lens band hugs the real very-rounded corner (slightly under, to sit
  //              inside the visible radius, not outside it).
  // EDGE       — width (px) of the refraction band inward from each edge. Beyond
  //              this the map is neutral (128,128) → crisp, undistorted center.
  // SQUIRCLE_N — squircle exponent for the edge falloff surface profile (the
  //              article's convex squircle y = ⁴√(1−(1−x)⁴) ⇒ n=4). Higher = a
  //              softer flat→curve transition (avoids a hard interior seam).
  // SATURATE/BLUR — paired with the displacement in the backdrop-filter so the
  //              glass keeps the baseline's frosted character under the refraction.
  // ── RETUNED to the kube.io "Liquid Glass" MUSIC-PLAYER preset ────────────────
  // The owner's instruction: rip the music-player technique and match its
  // PARAMETERS panel exactly so Full Glass reads as CLEAR, strongly-REFRACTIVE
  // glass (the lensing does the work) — NOT fog. The literal music-player SVG
  // filter chain in the saved article (filter id="parallax-image-hero-filter"):
  //   feGaussianBlur stdDeviation="0.2"  → blurred_source        (BLUR LEVEL 1.0 — near-zero)
  //   feImage displacement-map (150×150) → displacement_map
  //   feDisplacementMap scale="133.97"   → displaced              (REFRACTION 1.00 — strong)
  //   feColorMatrix saturate values="6"  → displaced_saturated    (SATURATION 6)
  //   feImage specular-map               → specular_layer
  //   feComposite operator="in" + feComponentTransfer feFuncA slope="0.2"
  //   feBlend normal ×2                  → lit                    (SPECULAR OPACITY 0.40)
  // Our map is generated at the element's OWN pixel resolution (1:1, userSpaceOnUse),
  // not stretched from a 150px reference, so the kube `scale=133.97` does NOT port
  // verbatim — it is calibrated against a 150px map. The value below is tuned BY
  // RENDER to give the music player's strong-but-not-smeared lensing in OUR px units:
  // the rim clearly bends the backdrop, the center stays crisp.
  var SCALE = 58;            // px max displacement at the rim — REFRACTION 1.00 (strong lensing)
  var SCALE_REDUCED = 30;    // calmer lensing under prefers-reduced-motion
  var RADIUS = 22;           // corner radius the lens hugs — tracks style.css --ow-glass-radius
                             // (26px); kept slightly under so the band sits INSIDE the visible
                             // corner rather than outside it (was 18, stale against the old 22px).
  var EDGE = 26;             // refraction band width inward from each edge (px) — a touch wider
                             // so the stronger displacement has room to ramp (no hard interior seam)
  var SQUIRCLE_N = 4;        // squircle exponent (4 ⇒ the article's convex profile)
  // EDGE-BLEED CLAMP (the "ring" fix). The squircle profile is MAXIMAL right at the very
  // perimeter (t=0 ⇒ push=1.0), so feDisplacementMap at the outermost row/col samples the
  // backdrop up to `scale` px BEYOND the surface — at the rounded corners that pulls content
  // from OUTSIDE the visible shape into the rim, rendering a faint refraction halo/ring past
  // the corners. The kube article's own constraint: displacement is symmetric around the
  // bezel and must fall to NEUTRAL (128,128) AT the outer edge so it never samples beyond the
  // surface. So we WINDOW the magnitude to ZERO at the very edge and ramp it up over the
  // outermost EDGE_NEUTRAL fraction of the band — the peak just moves a few px inward, the
  // in-bounds lensing strength is preserved, and the perimeter pixels are byte-neutral (no
  // out-of-bounds sample → no bleed ring). EDGE_NEUTRAL is a small fraction (the ramp is a
  // thin ~3-4px lead-in at EDGE=26), so it removes the halo without softening the lens band.
  var EDGE_NEUTRAL = 0.16;   // fraction of the bezel band that ramps 0→peak from the very edge inward
  // IN-FILTER blur — BLUR LEVEL 1.0 (the music player's stdDeviation="0.2"). This is
  // the FOG FIX: the prior 16px gaussian smeared the backdrop into milk. Near-zero
  // gaussian keeps the glass CLEAR so the wallpaper reads THROUGH it, lensed at the
  // rim. We use ~2px (not 0.2) because our map is at full element resolution and a
  // hair of blur hides the per-pixel displacement-map stairstepping; the look is
  // still crisp/transparent, not frosted.
  var FILTER_BLUR = 2;       // px — stdDeviation of the in-filter <feGaussianBlur> (music-player low)
  var CSS_BLUR_FALLBACK = 0; // px — NO extra CSS blur; the clear glass must not re-fog
  // SATURATION — kube's chain runs `feColorMatrix saturate="6"` on the displaced layer
  // (their "glass dispersion" pop). At 6× it OVER-saturates whatever shows through and
  // throws a HUE CAST (warm sky → yellow on the sidebar, warm foreground → red on the
  // composer), which violates the colorless-material mandate ("glass has no hue of its
  // own; it takes color from content"). A gentle lift (~1.4×) keeps the Apple vibrancy
  // without casting a colour — the glass stays neutral and merely carries the content's
  // own colour through. (Owner: "odd yellow hue over the sidebar / red on the chatbar".)
  var FILTER_SATURATE = 1.4;  // feColorMatrix saturate on the displaced layer (neutralized from kube's 6)
  var BACKDROP_SAT = 100;    // % CSS backdrop saturate — neutral (the saturate now lives IN-filter,
                             // exactly like the music player; CSS adds none on top)
  // The music player has NO tint/lift wash — its character is refraction + saturation +
  // a faded specular rim, over a CLEAR backdrop. A slope<1 tint wash would darken/fog the
  // glass (the opposite of the goal), so the tint pass is DISABLED (slope=1, intercept=0 ⇒
  // the feComponentTransfer pass is skipped entirely). The light glass FILL is supplied by
  // CSS (body.glass-full light translucent fill), not by an in-filter darkening transfer.
  var TINT_SLOPE = 1;        // 1 ⇒ no per-channel softening (clear, music-player)
  var TINT_INTERCEPT = 0;    // 0 ⇒ no lift; the pass is skipped (byte-clear backdrop)
  // SPECULAR RIM HIGHLIGHT (the kube.io feBlend layer — the "lit edge" that makes the
  // glass read as lit, the most "creative" part per the article). It's a rim light:
  // a SECOND generated image (white, alpha = specular intensity) loaded as its own
  // <feImage> and feBlend mode="screen"'d OVER the refracted+blurred+tinted backdrop,
  // so a bright thin highlight rides the edge where the surface normal faces a fixed
  // light. Intensity = max(0, outwardNormal · lightDir)^POWER, confined to the rim by
  // the squircle edge band. Set SPEC_ENABLE=false to drop the whole layer (byte-identical
  // to before). All artistic — tune ANGLE/POWER/GAIN against the Apple refs.
  var SPEC_ENABLE = true;
  var SPEC_ANGLE_DEG = -60;  // light direction (the article's diagram default; upper-leftish rim)
  // Apple's specular RESPONDS TO GEOMETRY as a THIN bright edge on the lit side — NOT a
  // wide glossy band. On a large flat surface (the composer bar) a wide/bright rim pools
  // into a harsh horizontal streak; keep it a hairline that hugs the very edge and stays
  // subtle, so it reads as a reflective edge, not a wash.
  var SPEC_POWER = 6.0;      // exponent — higher = tighter/sharper highlight arc (collapse the
                             // bright part to the lit corner/edge instead of smearing the top)
  var SPEC_GAIN = 1.0;       // multiply the raw specular before clamping (brightness of the rim)
  var SPEC_ALPHA_MAX = 0.40; // SPECULAR OPACITY = 0.40 (the music-player PARAMETERS value). A crisp
                             // bright hairline reads "lit"; a dim wide one reads "glossy".
  var SPEC_BAND = 0.10;      // fraction of EDGE band the rim occupies — ~2px hairline, not a 6-10px
                             // band (Apple's lit edge in the refs is 1-2px)
  // The music-player chain ALSO lays a SECOND, faded copy of the whole specular map back
  // over the result (feComponentTransfer feFuncA type="linear" slope="0.2" → feBlend),
  // a soft full-surface specular sheen UNDER the crisp rim. Ported as an extra screen
  // pass of the specular at this alpha slope. 0 ⇒ skip (just the crisp rim).
  var SPEC_FADE = 0.2;       // feFuncA slope on the soft specular sheen pass (kube slope="0.2")

  // ── SWITCH-THUMB glass (ripped from the kube.io #switch section) ─────────────
  // kube.io (https://kube.io/blog/liquid-glass-css-svg/) "Switch": the thumb uses
  //   backdrop-filter:url(#thumb-filter); background-color:rgba(255,255,255,1);
  //   box-shadow:0 4px 22px rgba(0,0,0,0.1)
  // and the article notes Apple's Switch is the ONE component that is NOT convex:
  //   "This uses a LIP BEZEL, which makes the surface convex on the outside and
  //    CONCAVE in the middle. This makes the center slider zoomed out, while the
  //    edges refract the inside." (kube #switch; cf. Apple HIG slider/segmented
  //    "knob becomes glass on interaction" — lg_hig_slider_poster.png).
  // We port a CONCAVE radial profile for a round knob: the displacement points
  // OUTWARD from the center (vs our convex builder's INWARD push), so the backdrop
  // appears pushed away from the middle — the "zoomed-out center, refracted edge"
  // lip-bezel read. It is a SEPARATE, STATIC filter (id THUMB_FILTER_ID) generated
  // once at THUMB_MAP_RES and applied to the knob pseudo-elements by CSS (the knob
  // is a ::before/::after, not a JS-selectable node). Gated on body.glass-full by
  // the CSS; the non-glass / non-Chromium fallback keeps the clean white knob.
  var THUMB_FILTER_ID = "owlg-thumb";
  var THUMB_MAP_RES = 64;    // px resolution the round concave map is generated at (stretched to the knob)
  var THUMB_SCALE = 14;      // px max radial displacement at the knob rim (the knob is tiny; keep modest)
  var THUMB_LIP = 0.34;      // fraction of the radius that is the convex OUTER lip (rim); inside it is concave
  var THUMB_BLUR = 0.6;      // px in-filter gaussian (a hair, to hide map stairstep on the small knob)

  // Perf caps. Mobile gets a HARD-LOWER cap (small GPUs; the refraction is the most
  // expensive thing on the page). collectTargets() reads activeMaxSurfaces() so the
  // cap follows the viewport live (a rotate/resize re-evaluates on the next pass).
  // Prioritize big/visible-first; the rest fall back to the CSS frosted approximation.
  // Bubbles are NOT refracted (content layer, HIG), so the live set is just chrome +
  // open menus — comfortably under this cap on a normal desktop view.
  var MAX_LIVE_SURFACES = 20;        // desktop hard cap on simultaneously-refracted elements
  var MAX_LIVE_SURFACES_MOBILE = 8;  // small-screen hard cap (GPU-cheap; CSS glass for the rest)
  var MOBILE_W = 768;                // ≤ this viewport width ⇒ the mobile cap applies
  var SIZE_BUCKET = 8;               // (legacy) coarse size grid — NO LONGER USED by the rounded-rect
                                     // path: the map is now generated at the element's EXACT px W×H and
                                     // applied 1:1 (the non-square fix), so the cache keys on exact size.
                                     // Same-size gadget cards still collide on one map; off-grid unique
                                     // elements get their own exact-fit filter (correct — stretching a
                                     // bucketed map to a non-square box was the bug). Kept for reference.
  var RESIZE_DEBOUNCE_MS = 140;      // coalesce a resize-drag burst into one re-map
  var MAP_RES_CAP = 1024;            // cap a map's canvas dimension (perf + the SVG res ceiling)

  // The surfaces that get refraction, in PRIORITY order (the cap fills from the top).
  // Same selectors CSS-glassed in style.css (body.theme-frosted …) so the aesthetic
  // is coherent across every glass surface. #appkit-headshot is a GATING dialog —
  // kept OPAQUE in CSS and EXCLUDED here (never refracted). The big draggable windows,
  // composer, sidebar, modals and the Control-Center dock take priority; the smaller
  // notice + gadget cards come last (they share size buckets, so a rail of identical
  // cards is cheap) and are dropped first when the cap bites on a small screen.
  // Apple HIG (docs/design/liquid-glass/LIQUID_GLASS_REFERENCE.md): "Liquid Glass forms a
  // distinct FUNCTIONAL layer for controls and navigation elements — like tab bars and
  // sidebars — that floats ABOVE the content layer" and "Don't use Liquid Glass in the
  // CONTENT layer." So the refraction belongs ONLY on the functional/chrome layer:
  // sidebar/rail, composer, top bar, model picker, window chrome, the dock, menus/popovers,
  // gadget chrome, and the functional notice cards — NAVIGATION + CONTROLS. The CHAT MESSAGE
  // BUBBLES are the CONTENT layer and are deliberately EXCLUDED (a refractive pane on the
  // content is what made them read as fog — and it's the HIG anti-pattern). Bubbles get the
  // restrained content treatment in CSS instead (the wallpaper shows in the gaps between
  // bubbles; the glass chrome floats above). Ordered big/visible-first; the CSS frosted blur
  // is the graceful perf fallback for the overflow past the cap, mobile, and non-Chromium.
  var SELECTORS = [
    ".ow-window",
    "#minimized-dock.ow-has-rows", // the iOS Control-Center dock module
    "#sidebar",
    ".icon-rail",                  // the collapsed floating sidebar rail (frosted theme)
    ".chat-input-bar",
    ".modal-content",
    ".admin-card",                 // settings / theme / memory / integrations panels
    ".chat-top-bar",
    ".model-picker-menu",
    ".toast",
    ".og-card",                    // the control-room gadget cards
    // Transient menus & popovers: small + short-lived, so they refract when open and
    // share size buckets (one map per size). watchMounts() schedules a pass when they mount.
    ".dropdown",
    ".overflow-menu",
    ".cp-popover",
    ".on-card",                    // the notice kit (functional affordance)
    // ── GLASS BUTTONS (kube.io demos the refraction on PILL BUTTONS — the authentic
    // look). The high-emphasis glass variants get the SAME feImage→feDisplacementMap
    // refraction + specular rim as the chrome, applied via backdrop-filter (refracts the
    // backdrop BEHIND the button, NEVER the label/glyph — see applyTo). They are LAST in
    // priority so the big chrome panels always win the cap, and they SHARE the per-size
    // filter cache (identical buttons → ONE filter, so a row of same-size buttons is
    // cheap). The .ow-btn-group is the ONE glass-sampling surface for its members
    // (NSGlassEffectContainerView analogue, style.css) — its members carry no backdrop
    // of their own and are EXCLUDED below. EXCLUSIONS (isRefractableButton): .ow-btn-plain
    // (borderless, no glass material), the opaque .ow-btn-destructive-solid plate, and
    // grouped members (they ride the group's single sample) never refract.
    ".ow-btn-prominent",
    ".ow-btn-secondary",
    ".ow-btn-icon",
    ".ow-btn-group",               // the segmented group = ONE shared backdrop sample
    ".ow-btn",                     // any remaining glass .ow-btn (plain/solid/grouped excluded)
  ];
  // Glass-button variants that must NEVER refract: borderless plain (no glass material),
  // the opaque solid-destructive plate, and grouped members (they ride the group's single
  // backdrop sample — refracting a member would be glass-on-glass + a wrong-size filter).
  var BTN_NO_REFRACT = ".ow-btn-plain, .ow-btn-destructive-solid, .ow-btn-group > .ow-btn";
  function isRefractableButton(el) {
    try {
      if (!el.matches || !el.matches(".ow-btn, .ow-btn-group")) return true; // not a button → no extra gate
      return !el.matches(BTN_NO_REFRACT);
    } catch (_) {
      return true;
    }
  }
  var EXCLUDE_IDS = { "appkit-headshot": 1 };

  function activeMaxSurfaces() {
    try {
      return (window.innerWidth || 1280) <= MOBILE_W ? MAX_LIVE_SURFACES_MOBILE : MAX_LIVE_SURFACES;
    } catch (_) {
      return MAX_LIVE_SURFACES;
    }
  }

  // ── Feature detection: Chromium + SVG-filter backdrop-filter ────────────────
  function supported() {
    try {
      if (!window.CSS || typeof window.CSS.supports !== "function") return false;
      // SVG-filter reference in backdrop-filter — the precise capability.
      var ok =
        CSS.supports("backdrop-filter", "url(#x)") ||
        CSS.supports("-webkit-backdrop-filter", "url(#x)");
      if (!ok) return false;
      // Chromium-only: Firefox/Safari may report support for the property but do
      // NOT honor an SVG-filter reference in backdrop-filter. The decisive test is
      // a CHROMIUM engine; the decisive EXCLUSION is the engines that lie about
      // support — Firefox ("Firefox/") and Safari ("Safari" without "Chrome").
      // Chromium forks (Edge/Brave/Opera) all carry "Chrome" in the UA and DO
      // honor the filter, so they're intentionally included.
      var ua = navigator.userAgent || "";
      var isGecko = /Firefox\//.test(ua);
      var isSafari = /Safari\//.test(ua) && !/Chrome|Chromium|CriOS/.test(ua);
      if (isGecko || isSafari) return false;
      return /Chrome|Chromium|CriOS/.test(ua);
    } catch (_) {
      return false;
    }
  }

  function reducedMotion() {
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    } catch (_) {
      return false;
    }
  }

  // Apple HIG accessibility: prefers-reduced-transparency means SOLID surfaces —
  // no translucency/blur/refraction. When set, the module is a NO-OP and the CSS
  // (which forces a solid panel fill under the same query) is the whole render.
  // Applying our inline backdrop-filter here would defeat that solid fallback.
  function reducedTransparency() {
    try {
      return !!(window.matchMedia && window.matchMedia("(prefers-reduced-transparency: reduce)").matches);
    } catch (_) {
      return false;
    }
  }

  // ── Displacement-map generation ─────────────────────────────────────────────
  // Build an RGBA map for a WxH rounded rect with corner `radius`. R encodes x-
  // displacement, G encodes y-displacement (128 = neutral). The displacement
  // points INWARD (the lens pulls the backdrop toward the center) and ramps from
  // 0 at the inner boundary of the edge band to its max at the very edge, shaped
  // by the squircle profile so the flat→curve transition is soft.
  //
  // For a pixel at signed distance `d` from the nearest edge (0 at edge, growing
  // inward), within the EDGE band we compute t = d / EDGE in [0,1] and a profile
  // p(t) via the squircle: closeness c = 1 - t, profile = (1 - c^N)^(1/N) gives a
  // convex falloff; the displacement magnitude is SCALE * (1 - profile-ish). We
  // direct it along the inward normal (toward center) per axis.
  function squircleProfile(t) {
    // t in [0,1]: 0 at the very edge, 1 at the inner band boundary.
    // Convex squircle falloff: strong near the edge, easing to 0 inward.
    var tc = Math.min(1, Math.max(0, t));
    var c = 1 - tc; // closeness to the edge
    // (1 - (1-c)^N)^(1/N) is the article's convex squircle; we want the
    // MAGNITUDE to be high at the edge (c→1) and 0 inward (c→0).
    var n = SQUIRCLE_N;
    var prof = Math.pow(1 - Math.pow(1 - c, n), 1 / n); // 0→1 as c 0→1
    // EDGE-BLEED CLAMP: window the magnitude to 0 at the VERY edge (t=0) and ramp it up
    // over the outermost EDGE_NEUTRAL fraction of the band, so the perimeter pixels are
    // neutral (128,128) and feDisplacementMap never samples beyond the surface (no halo
    // ring past the rounded corners). Smoothstep the lead-in so the rim has no hard seam;
    // beyond the lead-in (t >= EDGE_NEUTRAL) the squircle profile is untouched, preserving
    // the in-bounds lensing strength. EDGE_NEUTRAL=0 ⇒ byte-identical to the old behavior.
    if (EDGE_NEUTRAL > 0 && tc < EDGE_NEUTRAL) {
      var u = tc / EDGE_NEUTRAL;          // 0 at edge → 1 at lead-in inner
      prof *= u * u * (3 - 2 * u);        // smoothstep ramp 0→1 (neutral at the very edge)
    }
    return prof; // magnitude weight at this depth
  }

  // ── FIXED-PX-BAND, MIDDLE-STRETCHED displacement map (the kube fix) ────────────
  // The article's key constraint: the displacement magnitude is SYMMETRIC around
  // the bezel and ORTHOGONAL to the border — computed once on a radial "half-slice"
  // and reused around the perimeter ("Circles let us form rounded rectangles by
  // STRETCHING THE MIDDLE"). So for a rounded RECTANGLE the bezel ramp must be a
  // FIXED PIXEL WIDTH on all four sides, and only the flat NEUTRAL (128,128) center
  // is stretched. The previous build coupled the band to BOTH axes
  // (`band = min(EDGE, min(cw,ch)/2)`) and the filter then STRETCHED the bucketed
  // map to the element via objectBoundingBox — which warped the ramps on non-square
  // elements (the short top banner became all-ramp with no neutral center; the tall
  // sidebar smeared the backdrop). The fix here:
  //   • The map is generated at the element's EXACT pixel W×H (see filterFor) and the
  //     filter region is userSpaceOnUse at that exact size, so it maps 1:1 — NO
  //     aspect-warping stretch. (filterFor keeps the rim at the true edge.)
  //   • The bezel ramp is a FIXED-PX width per axis (bandX/bandY, each = EDGE),
  //     INDEPENDENT of the other axis, so all four sides ramp over the same physical
  //     px on a wide, tall, or square element alike.
  //   • Each band is CLAMPED so it can never exceed just-under half that axis — a
  //     flat neutral center ALWAYS remains (the ramps never meet). A very short or
  //     narrow element keeps a crisp undistorted middle with only thin rim lensing.
  // Corners blend the two axes' inward pushes; the squircle profile shapes each
  // axis's falloff (Apple's convex squircle, SQUIRCLE_N=4).
  function buildMapDataUrl(w, h, radius, scale) {
    var cw = Math.min(MAP_RES_CAP, Math.max(8, Math.round(w)));
    var ch = Math.min(MAP_RES_CAP, Math.max(8, Math.round(h)));
    var canvas = document.createElement("canvas");
    canvas.width = cw;
    canvas.height = ch;
    var ctx = canvas.getContext("2d");
    var img = ctx.createImageData(cw, ch);
    var data = img.data;
    // FIXED-PX bands per axis, clamped so a neutral center always survives. The
    // 0.5px back-off (and the 1px floor) guarantee bandX < cw/2, bandY < ch/2:
    // the left+right ramps never meet, the top+bottom ramps never meet → there is
    // always at least one neutral column AND one neutral row in the middle. On a
    // short banner the vertical ramps stay a thin EDGE-wide rim; the wide middle
    // stays crisp. (For the MAP_RES_CAP-shrunk axis the band scales with it so the
    // ramp stays a fixed FRACTION of the element, still leaving a neutral center.)
    var sx = cw / Math.max(1, Math.round(w)); // canvas px per element px on X (≤1 only if capped)
    var sy = ch / Math.max(1, Math.round(h));
    var bandX = Math.max(1, Math.min(EDGE * sx, cw / 2 - 0.5));
    var bandY = Math.max(1, Math.min(EDGE * sy, ch / 2 - 0.5));

    // Specular rim map (white, alpha = highlight intensity), built in the SAME loop.
    var specCanvas = null, specData = null, lx = 0, ly = 0;
    if (SPEC_ENABLE) {
      specCanvas = document.createElement("canvas");
      specCanvas.width = cw; specCanvas.height = ch;
      var simg = specCanvas.getContext("2d").createImageData(cw, ch);
      specData = simg.data;
      var ang = (SPEC_ANGLE_DEG * Math.PI) / 180;
      lx = Math.cos(ang); ly = Math.sin(ang); // fixed light direction (unit)
    }

    for (var y = 0; y < ch; y++) {
      // Per-row vertical depth/push, fixed-px from the nearer of top/bottom.
      var distY = Math.min(y, ch - 1 - y);          // px from nearer horizontal edge
      var tY = distY < bandY ? distY / bandY : 1;    // 0 at edge → 1 at band inner
      var pushY = distY < bandY ? squircleProfile(tY) : 0; // 0..1 magnitude
      var dirY = y < ch / 2 ? 1 : -1;                // inward (toward center)
      for (var x = 0; x < cw; x++) {
        // Per-column horizontal depth/push, fixed-px from the nearer of left/right.
        var distX = Math.min(x, cw - 1 - x);
        var tX = distX < bandX ? distX / bandX : 1;
        var pushX = distX < bandX ? squircleProfile(tX) : 0;
        var dirX = x < cw / 2 ? 1 : -1;

        var dr = 0; // x displacement (signed, -1..1 before *scale)
        var dg = 0; // y displacement

        if (pushX > 0 || pushY > 0) {
          // Inward normal: each axis contributes its own fixed-px ramp magnitude;
          // corners blend both (a true rounded-rect inward push), edges are
          // single-axis. Normalize the direction, keep the magnitude = the stronger
          // (edge-closest) of the two axis ramps so a corner isn't double-bright.
          var nx = dirX * pushX;
          var ny = dirY * pushY;
          var len = Math.sqrt(nx * nx + ny * ny) || 1;
          var mag = Math.max(pushX, pushY); // squircle magnitude weight at this depth
          dr = (nx / len) * mag;
          dg = (ny / len) * mag;

          // Specular rim: OUTWARD unit normal is -(inward), confined to the OUTER
          // SPEC_BAND fraction of the edge band so it reads as a thin lit line. The
          // rim depth uses the SAME nearest-edge fraction (min tX/tY for the axis in
          // play) so the highlight hugs the very edge on every side, square or not.
          if (specData) {
            var tEdge = Math.min(pushX > 0 ? tX : 1, pushY > 0 ? tY : 1);
            if (tEdge < SPEC_BAND) {
              var ux = -(nx / len), uy = -(ny / len);
              var ndotl = ux * lx + uy * ly;
              if (ndotl > 0) {
                var rim = 1 - tEdge / SPEC_BAND;            // 1 at edge → 0 at band inner
                // Match the displacement EDGE-BLEED CLAMP: fade the lit hairline to 0 at the
                // very perimeter so it rides JUST inside the edge (clip-safe, and consistent
                // with the now-neutral outer displacement rim — no bright pixel on the
                // un-clipped corner). Same smoothstep lead-in as squircleProfile.
                if (EDGE_NEUTRAL > 0 && tEdge < SPEC_BAND * EDGE_NEUTRAL) {
                  var ue = tEdge / (SPEC_BAND * EDGE_NEUTRAL);
                  rim *= ue * ue * (3 - 2 * ue);
                }
                var s = Math.pow(ndotl, SPEC_POWER) * rim * SPEC_GAIN;
                var a = Math.max(0, Math.min(SPEC_ALPHA_MAX, s));
                var si = (y * cw + x) * 4;
                specData[si] = 255; specData[si + 1] = 255; specData[si + 2] = 255;
                specData[si + 3] = Math.round(a * 255);
              }
            }
          }
        }

        var i = (y * cw + x) * 4;
        // 128 = neutral; ±127 full range. dr/dg in [-1,1].
        data[i] = Math.max(0, Math.min(255, Math.round(128 + dr * 127)));     // R = x-displacement
        data[i + 1] = Math.max(0, Math.min(255, Math.round(128 + dg * 127))); // G = y-displacement
        data[i + 2] = 128; // B unused
        data[i + 3] = 255; // A opaque
      }
    }
    ctx.putImageData(img, 0, 0);
    var out = { url: canvas.toDataURL("image/png"), w: cw, h: ch, specUrl: null };
    if (specCanvas && specData) {
      specCanvas.getContext("2d").putImageData(new ImageData(specData, cw, ch), 0, 0);
      out.specUrl = specCanvas.toDataURL("image/png");
    }
    return out;
  }

  // ── SVG filter host (ONE shared inline <svg> with a <filter> per size bucket) ─
  var SVG_NS = "http://www.w3.org/2000/svg";
  var XLINK_NS = "http://www.w3.org/1999/xlink";
  var hostSvg = null;
  var filterCache = {}; // bucketKey -> { id }
  var filterCount = 0;

  function ensureHost() {
    if (hostSvg && hostSvg.isConnected) return hostSvg;
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("id", "appkit-liquid-glass-host");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    // colorInterpolationFilters=sRGB (the article): keep the displacement-map
    // channels linear-free so 128 is true neutral.
    svg.setAttribute("color-interpolation-filters", "sRGB");
    svg.style.cssText =
      "position:absolute;width:0;height:0;overflow:hidden;pointer-events:none;";
    (document.body || document.documentElement).appendChild(svg);
    hostSvg = svg;
    return svg;
  }

  // The map is now generated at the element's EXACT px size and the filter region is
  // userSpaceOnUse at that SAME size (1:1, no stretch — the non-square fix). So the
  // cache key is the exact rounded W×H: many same-size gadget cards still collide on
  // ONE map/filter (a rail of identical cards stays cheap), while a unique large
  // element (sidebar/banner/composer/window) gets its own exact-fit filter — which is
  // correct, since stretching a bucketed map to a non-square box is exactly the bug.
  function bucketKey(w, h, scale) {
    return Math.round(w) + "x" + Math.round(h) + "x" + RADIUS + "x" + scale;
  }

  // ── Concave round-knob displacement map (the kube.io switch "lip bezel") ──────
  // A CIRCULAR map for the toggle thumb. Unlike the convex rounded-rect builder
  // (displacement points INWARD), this is the switch's LIP BEZEL: a thin convex
  // OUTER lip (rim, fraction THUMB_LIP of the radius) that refracts the inside,
  // wrapping a CONCAVE interior whose displacement points OUTWARD from the center
  // (so the middle reads "zoomed out"). R/G encode x/y displacement (128 neutral),
  // direction = radial. Returns a PNG dataURL stretched to the knob via 100%×100%.
  function buildThumbMapDataUrl() {
    var n = THUMB_MAP_RES;
    var canvas = document.createElement("canvas");
    canvas.width = n; canvas.height = n;
    var ctx = canvas.getContext("2d");
    var img = ctx.createImageData(n, n);
    var data = img.data;
    var cx = (n - 1) / 2, cy = (n - 1) / 2;
    var R = n / 2; // knob radius in map px
    for (var y = 0; y < n; y++) {
      for (var x = 0; x < n; x++) {
        var vx = x - cx, vy = y - cy;
        var dist = Math.sqrt(vx * vx + vy * vy);
        var t = Math.min(1, dist / R); // 0 center → 1 rim
        var dr = 0, dg = 0;
        if (t > 0.001 && t <= 1) {
          var ux = vx / (dist || 1), uy = vy / (dist || 1); // outward radial unit
          var mag; // signed radial magnitude in [-1,1]: + = outward (concave), - = inward (convex lip)
          if (t >= 1 - THUMB_LIP) {
            // OUTER LIP — convex: pull the backdrop INWARD (negative radial), peaking
            // at the very rim and easing to 0 at the lip's inner boundary.
            var lt = (t - (1 - THUMB_LIP)) / THUMB_LIP; // 0 at lip inner → 1 at rim
            mag = -Math.pow(lt, 1.6);
          } else {
            // INNER FIELD — concave: push OUTWARD (positive radial), gentle ramp from
            // 0 at the center to its max at the lip boundary (the "zoomed-out" middle).
            var ct = t / (1 - THUMB_LIP); // 0 center → 1 at lip boundary
            mag = Math.pow(ct, 1.4);
          }
          dr = ux * mag;
          dg = uy * mag;
        }
        var i = (y * n + x) * 4;
        data[i] = Math.max(0, Math.min(255, Math.round(128 + dr * 127)));     // R = x-displacement
        data[i + 1] = Math.max(0, Math.min(255, Math.round(128 + dg * 127))); // G = y-displacement
        data[i + 2] = 128;
        data[i + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
    return canvas.toDataURL("image/png");
  }

  var thumbBuilt = false;
  function ensureThumbFilter() {
    if (thumbBuilt && document.getElementById(THUMB_FILTER_ID)) return;
    var svg = ensureHost();
    // Drop any stale copy (e.g. host was re-created) before rebuilding.
    var prev = document.getElementById(THUMB_FILTER_ID);
    if (prev && prev.parentNode) prev.parentNode.removeChild(prev);
    var url = buildThumbMapDataUrl();
    var filter = document.createElementNS(SVG_NS, "filter");
    filter.setAttribute("id", THUMB_FILTER_ID);
    // objectBoundingBox so the round map stretches to the knob's exact box (any size).
    filter.setAttribute("filterUnits", "objectBoundingBox");
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    filter.setAttribute("width", "1");
    filter.setAttribute("height", "1");
    filter.setAttribute("color-interpolation-filters", "sRGB");

    var feImage = document.createElementNS(SVG_NS, "feImage");
    feImage.setAttribute("x", "0");
    feImage.setAttribute("y", "0");
    feImage.setAttribute("width", "100%");
    feImage.setAttribute("height", "100%");
    feImage.setAttribute("preserveAspectRatio", "none");
    feImage.setAttribute("result", "thumb_map");
    feImage.setAttributeNS(XLINK_NS, "xlink:href", url);
    feImage.setAttribute("href", url);
    filter.appendChild(feImage);

    var feDisp = document.createElementNS(SVG_NS, "feDisplacementMap");
    feDisp.setAttribute("in", "SourceGraphic");
    feDisp.setAttribute("in2", "thumb_map");
    feDisp.setAttribute("scale", String(reducedMotion() ? Math.round(THUMB_SCALE * 0.6) : THUMB_SCALE));
    feDisp.setAttribute("xChannelSelector", "R");
    feDisp.setAttribute("yChannelSelector", "G");
    feDisp.setAttribute("result", "thumb_refracted");
    filter.appendChild(feDisp);

    if (THUMB_BLUR > 0) {
      var feBlur = document.createElementNS(SVG_NS, "feGaussianBlur");
      feBlur.setAttribute("in", "thumb_refracted");
      feBlur.setAttribute("stdDeviation", String(THUMB_BLUR));
      filter.appendChild(feBlur);
    }

    svg.appendChild(filter);
    thumbBuilt = true;
  }

  // Get (or build) a filter for a given content-box size; returns its DOM id.
  function filterFor(w, h, scale) {
    var key = bucketKey(w, h, scale);
    if (filterCache[key]) return filterCache[key].id;
    var svg = ensureHost();
    var map = buildMapDataUrl(w, h, RADIUS, scale);
    var id = "owlg-" + (filterCount++);
    var filter = document.createElementNS(SVG_NS, "filter");
    filter.setAttribute("id", id);
    // ── NON-SQUARE / EDGE-ALIGNMENT FIX (1:1 exact-size map, no aspect stretch) ──
    // A previous edit set the region to objectBoundingBox(0,0,1,1) + feImage 100%×100%
    // (preserveAspectRatio="none") to fix a composer right-edge seam. That STRETCHES
    // the (then bucketed) displacement map to the element box — which WARPS the bezel
    // ramps on non-square elements: the short top banner became all-ramp (no neutral
    // center) and the tall sidebar smeared the backdrop instead of clean rim lensing.
    //
    // Fix: the map is now generated at the element's EXACT px W×H (buildMapDataUrl /
    // bucketKey) with FIXED-PX bezel bands + a stretched neutral middle, and the filter
    // region + feImage are sized in userSpaceOnUse to those SAME exact px dimensions and
    // pinned at x=0,y=0. So the map maps 1:1 onto the element with NO aspect-warping
    // stretch: the rim band is a fixed px width on all four sides, the neutral center is
    // crisp, and the rim still hugs the TRUE edge (map dims == element dims, re-mapped on
    // resize via applyTo) — keeping the composer right-edge alignment win without the
    // inward seam. primitiveUnits stays the default (userSpaceOnUse) ⇒ feDisplacementMap
    // `scale` remains in px (unchanged). map.w/map.h already honor MAP_RES_CAP.
    var fw = map.w, fh = map.h;
    filter.setAttribute("filterUnits", "userSpaceOnUse");
    filter.setAttribute("x", "0");
    filter.setAttribute("y", "0");
    filter.setAttribute("width", String(fw));
    filter.setAttribute("height", String(fh));
    filter.setAttribute("color-interpolation-filters", "sRGB");

    var feImage = document.createElementNS(SVG_NS, "feImage");
    feImage.setAttribute("x", "0");
    feImage.setAttribute("y", "0");
    feImage.setAttribute("width", String(fw));
    feImage.setAttribute("height", String(fh));
    feImage.setAttribute("result", "displacement_map");
    feImage.setAttribute("preserveAspectRatio", "none");
    feImage.setAttributeNS(XLINK_NS, "xlink:href", map.url);
    feImage.setAttribute("href", map.url); // modern + legacy

    var feDisp = document.createElementNS(SVG_NS, "feDisplacementMap");
    feDisp.setAttribute("in", "SourceGraphic");
    feDisp.setAttribute("in2", "displacement_map");
    feDisp.setAttribute("scale", String(scale));
    feDisp.setAttribute("xChannelSelector", "R");
    feDisp.setAttribute("yChannelSelector", "G");
    feDisp.setAttribute("result", "refracted");

    filter.appendChild(feImage);
    filter.appendChild(feDisp);

    // IN-FILTER blur (CodePen refinement #2): compose the frost INTO the same pass
    // as the displacement so a single backdrop-filter url(#id) yields blur+lens.
    var lastResult = "refracted";
    if (FILTER_BLUR > 0) {
      var feBlur = document.createElementNS(SVG_NS, "feGaussianBlur");
      feBlur.setAttribute("in", lastResult);
      feBlur.setAttribute("stdDeviation", String(FILTER_BLUR));
      feBlur.setAttribute("result", "blurred");
      filter.appendChild(feBlur);
      lastResult = "blurred";
    }

    // IN-FILTER SATURATE (ported LITERALLY from the music-player chain:
    // `feColorMatrix type="saturate" values="6"` on the displaced layer). This is the
    // glass-dispersion "pop" — the lensed backdrop gets saturated so the refraction
    // reads as real glass, not a smudge. Runs IN the chain (like kube), not as a CSS
    // backdrop-filter saturate. Skipped when FILTER_SATURATE === 1.
    if (FILTER_SATURATE !== 1) {
      var feSat = document.createElementNS(SVG_NS, "feColorMatrix");
      feSat.setAttribute("in", lastResult);
      feSat.setAttribute("type", "saturate");
      feSat.setAttribute("values", String(FILTER_SATURATE));
      feSat.setAttribute("result", "saturated");
      filter.appendChild(feSat);
      lastResult = "saturated";
    }

    // Optional per-channel linear transfer (kept for compatibility; DISABLED in the
    // music-player preset — slope=1/intercept=0 ⇒ skipped, the glass stays clear).
    if (TINT_SLOPE !== 1 || TINT_INTERCEPT !== 0) {
      var feCT = document.createElementNS(SVG_NS, "feComponentTransfer");
      feCT.setAttribute("in", lastResult);
      ["feFuncR", "feFuncG", "feFuncB"].forEach(function (fn) {
        var f = document.createElementNS(SVG_NS, fn);
        f.setAttribute("type", "linear");
        f.setAttribute("slope", String(TINT_SLOPE));
        f.setAttribute("intercept", String(TINT_INTERCEPT));
        feCT.appendChild(f);
      });
      feCT.setAttribute("result", "tinted");
      filter.appendChild(feCT);
      lastResult = "tinted";
    }

    // SPECULAR (the kube.io specular-map + feBlend layers). kube generates a dedicated
    // specular-map and lays it over the saturated/displaced result in TWO passes:
    //   1) the crisp specular (composited `in` with the saturated layer) — our white
    //      rim map screened over the result is the equivalent "lit edge".
    //   2) a SECOND, alpha-FADED copy of the whole specular (feFuncA slope="0.2"),
    //      blended back as a soft full-surface sheen UNDER the crisp rim.
    // We reproduce both from our single generated rim/spec map. mode="screen" lightens
    // only where the spec has alpha (transparent center = identity = clear glass).
    if (SPEC_ENABLE && map.specUrl) {
      var feSpec = document.createElementNS(SVG_NS, "feImage");
      feSpec.setAttribute("x", "0");
      feSpec.setAttribute("y", "0");
      // Exact-px (matches the displacement feImage, userSpaceOnUse) so the specular
      // rim maps 1:1 to the element and hugs the true edge on every side — see the
      // NON-SQUARE / EDGE-ALIGNMENT FIX note. The specular pass stays ON for EVERY
      // refracted surface (SPEC_ENABLE): "without specular highlight, it's not glass."
      feSpec.setAttribute("width", String(fw));
      feSpec.setAttribute("height", String(fh));
      feSpec.setAttribute("preserveAspectRatio", "none");
      feSpec.setAttribute("result", "specular_layer");
      feSpec.setAttributeNS(XLINK_NS, "xlink:href", map.specUrl);
      feSpec.setAttribute("href", map.specUrl);
      filter.appendChild(feSpec);

      // Pass 1: the crisp specular rim screened over the result (the "lit edge").
      var feBlend = document.createElementNS(SVG_NS, "feBlend");
      feBlend.setAttribute("in", lastResult);
      feBlend.setAttribute("in2", "specular_layer");
      feBlend.setAttribute("mode", "screen");
      feBlend.setAttribute("result", "lit");
      filter.appendChild(feBlend);
      lastResult = "lit";

      // Pass 2: the kube feFuncA-faded soft sheen — fade the specular's alpha by the
      // slope, then screen it back for a gentle full-surface glass sheen under the rim.
      if (SPEC_FADE > 0) {
        var feFade = document.createElementNS(SVG_NS, "feComponentTransfer");
        feFade.setAttribute("in", "specular_layer");
        var fa = document.createElementNS(SVG_NS, "feFuncA");
        fa.setAttribute("type", "linear");
        fa.setAttribute("slope", String(SPEC_FADE));
        feFade.appendChild(fa);
        feFade.setAttribute("result", "specular_faded");
        filter.appendChild(feFade);

        var feBlend2 = document.createElementNS(SVG_NS, "feBlend");
        feBlend2.setAttribute("in", lastResult);
        feBlend2.setAttribute("in2", "specular_faded");
        feBlend2.setAttribute("mode", "screen");
        feBlend2.setAttribute("result", "lit2");
        filter.appendChild(feBlend2);
        lastResult = "lit2";
      }
    }

    svg.appendChild(filter);
    filterCache[key] = { id: id };
    return id;
  }

  // ── Applying / clearing refraction on a surface ─────────────────────────────
  var liveEls = new Set(); // elements currently carrying a live filter
  var ro = null; // shared ResizeObserver
  var resizeTimer = 0;
  var pendingResize = new Set();

  function activeScale() {
    return reducedMotion() ? SCALE_REDUCED : SCALE;
  }

  function applyTo(el) {
    try {
      if (!el || !el.isConnected) return;
      if (el.id && EXCLUDE_IDS[el.id]) return;
      if (!isRefractableButton(el)) { clearFrom(el); return; } // never refract plain/solid/grouped-member buttons
      var r = el.getBoundingClientRect();
      if (r.width < 24 || r.height < 24) return; // too small to bother
      var id = filterFor(r.width, r.height, activeScale());
      // The SVG filter already does blur + tint in-chain; the thin CSS blur is a
      // belt-and-suspenders softener, and saturate keeps the baseline's lively glass.
      var val =
        "url(#" + id + ") blur(" + CSS_BLUR_FALLBACK + "px) saturate(" + BACKDROP_SAT + "%)";
      // Layer OVER the CSS baseline. CRITICAL: the frosted CSS sets
      // `backdrop-filter: blur(..) !important` on these same surfaces (style.css
      // body.theme-frosted .ow-window etc.), and a plain inline style LOSES to a
      // CSS !important — so the SVG refraction must be set with `important`
      // priority to actually win the cascade (an inline !important outranks a
      // stylesheet !important). Without this the url(#filter) is silently
      // overridden by the blur and the whole liquid-glass layer never renders.
      // Non-Chromium never reaches here (supported() gate), so its CSS blur-glass
      // fallback is untouched.
      el.style.setProperty("backdrop-filter", val, "important");
      el.style.setProperty("-webkit-backdrop-filter", val, "important");
      el.setAttribute("data-liquid-glass", "1");
      liveEls.add(el);
      if (ro) {
        try { ro.observe(el); } catch (_) {}
      }
    } catch (_) {
      clearFrom(el); // fail-soft: drop our override, leave the CSS glass
    }
  }

  function clearFrom(el) {
    try {
      if (!el) return;
      el.style.removeProperty("backdrop-filter");
      el.style.removeProperty("-webkit-backdrop-filter");
      el.removeAttribute("data-liquid-glass");
      liveEls.delete(el);
      if (ro) {
        try { ro.unobserve(el); } catch (_) {}
      }
    } catch (_) {}
  }

  function clearAll() {
    Array.prototype.slice.call(liveEls).forEach(clearFrom);
    // Belt-and-suspenders: sweep any stray marker the live set missed (e.g. a node
    // re-added by an observer mid-teardown) so the fallback is provably clean.
    try {
      var stray = document.querySelectorAll("[data-liquid-glass]");
      for (var i = 0; i < stray.length; i++) clearFrom(stray[i]);
    } catch (_) {}
  }

  // Collect candidate surfaces in priority order, de-duped, excluding the gating
  // dialog and anything not eligible, capped at MAX_LIVE_SURFACES.
  function collectTargets() {
    var seen = new Set();
    var out = [];
    var cap = activeMaxSurfaces();
    for (var s = 0; s < SELECTORS.length; s++) {
      var nodes;
      try {
        nodes = document.querySelectorAll(SELECTORS[s]);
      } catch (_) {
        continue;
      }
      for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (seen.has(el)) continue;
        if (el.id && EXCLUDE_IDS[el.id]) continue;
        if (!isRefractableButton(el)) continue; // plain/solid/grouped-member buttons never refract
        if (el.offsetParent === null && getComputedStyle(el).position !== "fixed") continue; // hidden
        seen.add(el);
        out.push(el);
        if (out.length >= cap) return out;
      }
    }
    return out;
  }

  // Refraction is the FULL GLASS tier only. The body carries `theme-frosted` for
  // BOTH glass tiers (CSS material) and `glass-full` ONLY for Full Glass — which is
  // what gates the Chromium SVG refraction. So this checks `glass-full`, not
  // `theme-frosted`: the Frosted tier keeps the CSS blur-glass with no refraction.
  function isFrosted() {
    return !!(document.body && document.body.classList.contains("glass-full"));
  }

  // The public re-apply pass: only under the frosted theme + Chromium support.
  // Clears any surface no longer eligible, applies to the current target set.
  var applyScheduled = false;
  function scheduleApply() {
    if (applyScheduled) return;
    applyScheduled = true;
    (window.requestAnimationFrame || function (fn) { return setTimeout(fn, 16); })(function () {
      applyScheduled = false;
      applyPass();
    });
  }

  var _forceDisabled = false; // verification harness latch (_disable) — never set in prod
  function applyPass() {
    // Apple HIG: reduced-transparency ⇒ solid surfaces. Drop every override so the
    // CSS solid fallback stands; do NOT refract.
    if (_forceDisabled || !isFrosted() || reducedTransparency()) {
      clearAll();
      return;
    }
    var targets = collectTargets();
    var targetSet = new Set(targets);
    // Drop surfaces that fell out of the set (closed window, theme of card hidden).
    Array.prototype.slice.call(liveEls).forEach(function (el) {
      if (!targetSet.has(el) || !el.isConnected) clearFrom(el);
    });
    targets.forEach(applyTo);
    // Keep the single pointer-reactive rim in sync with tier/focus changes (a theme
    // flip to non-glass / reduced-transparency clears it; a flip back re-picks it).
    try { refreshSpecTarget(); } catch (_) {}
  }

  // ── ResizeObserver (debounced) — re-map a surface whose size changed ─────────
  function onResizeEntries(entries) {
    for (var i = 0; i < entries.length; i++) pendingResize.add(entries[i].target);
    if (resizeTimer) return;
    resizeTimer = setTimeout(function () {
      resizeTimer = 0;
      if (!isFrosted()) { pendingResize.clear(); return; }
      var els = Array.prototype.slice.call(pendingResize);
      pendingResize.clear();
      els.forEach(function (el) {
        if (liveEls.has(el)) applyTo(el); // re-pick a filter for the new size
      });
    }, RESIZE_DEBOUNCE_MS);
  }

  // ── Theme-change watch (no new event — observe body class; respects g15) ─────
  function watchTheme() {
    try {
      var mo = new MutationObserver(function () { scheduleApply(); });
      mo.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    } catch (_) {}
  }

  // ── Window-open hook: re-apply when a kit window mounts/opens ────────────────
  // The kit doesn't emit an open event, so we observe body child additions for a
  // new .ow-window / .og-card and schedule a pass (debounced via rAF). Cheap: the
  // observer only fires on subtree structure changes, and scheduleApply coalesces.
  function watchMounts() {
    try {
      var mo = new MutationObserver(function (muts) {
        for (var i = 0; i < muts.length; i++) {
          var m = muts[i];
          for (var j = 0; j < m.addedNodes.length; j++) {
            var n = m.addedNodes[j];
            if (n.nodeType !== 1) continue;
            var sel = ".ow-window, .chat-input-bar, .og-card, .on-card, .modal-content, #minimized-dock, .minimized-dock-chip, .dropdown, .overflow-menu, .cp-popover, .ow-btn, .ow-btn-group";
            if (
              n.matches &&
              (n.matches(sel) || (n.querySelector && n.querySelector(sel)))
            ) {
              scheduleApply();
              return;
            }
          }
        }
      });
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (_) {}
  }

  // ── POINTER-REACTIVE SPECULAR (Genius #21) ──────────────────────────────────
  // A thin pointer-tracking rim-light on the ONE currently-focused surface. As the
  // pointer moves over that surface, a subtle moving specular highlight shifts to
  // track it — "a hint of life", Apple-restrained, NEVER multiple at once.
  //
  // Mechanics (kept dead-simple + cheap):
  //   • We track exactly ONE active surface (the FOCUSED one): the composer when it
  //     holds focus (focus-within on .chat-input-bar), else the focused window
  //     (.ow-window.ow-focused). Focus changes swap the active surface; the previous
  //     one is cleared so there is provably never more than one live at a time.
  //   • pointermove over the active surface writes two CSS custom properties on it —
  //     --ow-spec-x / --ow-spec-y, the 0..1 pointer position within the surface — and
  //     sets data-ow-spec="1". The CSS (the dedicated pointer-specular region in
  //     style.css, body.glass-full only) consumes them in a radial-gradient ::after
  //     specular sheen whose CENTER tracks the pointer. The hue is OKLCH-normalized to
  //     neutral so no accent creeps onto the colorless glass.
  //   • rAF-throttled: pointermove only stashes the latest coords; one rAF flushes them
  //     to the CSS vars. No layout thrash, no per-event style write storm.
  //   • prefers-reduced-motion ⇒ NO pointer tracking. We set data-ow-spec="static" so
  //     the CSS renders a fixed (top-edge) rim-light instead of a moving one — the
  //     surface still reads as lit glass, it just doesn't chase the pointer.
  //   • Full-Glass tier only (isFrosted() == body.glass-full) and Chromium only
  //     (this whole module no-ops otherwise) and never under reduced-transparency.
  var specActive = null;         // the single surface currently carrying the pointer rim
  var specRaf = 0;               // pending rAF id (0 = none)
  var specPending = null;        // latest {el,x,y} awaiting flush
  var specBound = false;         // listeners attached once

  function specEligible() {
    // The pointer-reactive rim is Full-Glass + Chromium + transparency-on only. (Caller
    // already guards Chromium via supported(); these are the live-toggleable gates.)
    return isFrosted() && !reducedTransparency() && !_forceDisabled;
  }

  // The single FOCUSED surface that should carry the rim, or null. Composer focus wins
  // over a focused window (it's the active input); STRICTLY one is returned.
  function focusedSurface() {
    try {
      var bar = document.querySelector(".chat-input-bar");
      if (bar && bar.isConnected && bar.matches(":focus-within")) return bar;
      var win = document.querySelector(".ow-window.ow-focused");
      if (win && win.isConnected) return win;
      return null;
    } catch (_) {
      return null;
    }
  }

  function clearSpec(el) {
    if (!el) return;
    try {
      el.removeAttribute("data-ow-spec");
      el.style.removeProperty("--ow-spec-x");
      el.style.removeProperty("--ow-spec-y");
    } catch (_) {}
  }

  // Promote `el` (or null) to the SOLE pointer-rim surface, clearing any previous one.
  function setSpecActive(el) {
    if (el === specActive) return;
    if (specActive) clearSpec(specActive);
    specActive = el || null;
    if (!specActive) return;
    // Reduced-motion ⇒ a STATIC rim (no pointer chase). Otherwise mark it live and seed
    // the highlight at the top-center until the pointer moves over it.
    if (reducedMotion()) {
      specActive.setAttribute("data-ow-spec", "static");
    } else {
      specActive.setAttribute("data-ow-spec", "1");
      try {
        specActive.style.setProperty("--ow-spec-x", "0.5");
        specActive.style.setProperty("--ow-spec-y", "0");
      } catch (_) {}
    }
  }

  // Re-evaluate which single surface is focused and own the rim accordingly.
  function refreshSpecTarget() {
    if (!specEligible()) { setSpecActive(null); return; }
    setSpecActive(focusedSurface());
  }

  function flushSpec() {
    specRaf = 0;
    var p = specPending;
    specPending = null;
    if (!p || p.el !== specActive || !specActive) return;
    if (reducedMotion()) return; // static rim ignores the pointer
    try {
      specActive.style.setProperty("--ow-spec-x", p.x.toFixed(4));
      specActive.style.setProperty("--ow-spec-y", p.y.toFixed(4));
    } catch (_) {}
  }

  function onSpecPointerMove(e) {
    if (!specActive || reducedMotion() || !specEligible()) return;
    // Only track when the pointer is actually over the active surface (one at a time).
    var el = specActive;
    var r;
    try { r = el.getBoundingClientRect(); } catch (_) { return; }
    if (r.width <= 0 || r.height <= 0) return;
    var x = (e.clientX - r.left) / r.width;
    var y = (e.clientY - r.top) / r.height;
    if (x < 0 || x > 1 || y < 0 || y > 1) return; // pointer left the surface
    specPending = { el: el, x: Math.min(1, Math.max(0, x)), y: Math.min(1, Math.max(0, y)) };
    if (!specRaf) {
      specRaf = (window.requestAnimationFrame || function (fn) { return setTimeout(fn, 16); })(flushSpec);
    }
  }

  function bindSpec() {
    if (specBound) return;
    specBound = true;
    try {
      // Focus changes re-pick the single active surface (focusin/out bubble).
      document.addEventListener("focusin", refreshSpecTarget, true);
      document.addEventListener("focusout", function () {
        // defer so focus has settled on the new target before we re-pick
        (window.requestAnimationFrame || function (fn) { return setTimeout(fn, 0); })(refreshSpecTarget);
      }, true);
      // A window raise (.ow-focused swap) happens on pointerdown, so a deferred re-pick
      // on pointerdown keeps the focused-window rim in sync without a new observer.
      document.addEventListener("pointerdown", function () {
        (window.requestAnimationFrame || function (fn) { return setTimeout(fn, 0); })(refreshSpecTarget);
      }, true);
      document.addEventListener("pointermove", onSpecPointerMove, { passive: true });
      // a11y prefs flip live → re-evaluate static vs. tracking (drop + re-pick so the
      // new data-ow-spec mode is applied to whatever is focused now).
      try {
        ["(prefers-reduced-motion: reduce)", "(prefers-reduced-transparency: reduce)"].forEach(function (q) {
          var mq = window.matchMedia(q);
          var on = function () { setSpecActive(null); refreshSpecTarget(); };
          if (mq.addEventListener) mq.addEventListener("change", on);
          else if (mq.addListener) mq.addListener(on);
        });
      } catch (_) {}
    } catch (_) {}
    refreshSpecTarget();
  }

  // ── Boot ────────────────────────────────────────────────────────────────────
  function init() {
    if (!supported()) {
      // NO-OP on non-Chromium: the CSS blur-glass baseline stands. Expose a marker
      // for tests/debug; do NOT touch any surface.
      try { window.AppkitLiquidGlass = { supported: false, refresh: function () {} }; } catch (_) {}
      return;
    }
    try {
      ensureHost();
      // Build the static switch-thumb filter once (the toggle knobs reference it by
      // id from CSS, gated on body.glass-full). Chromium-only path (supported() above).
      try { ensureThumbFilter(); } catch (_) {}
      if (window.ResizeObserver) ro = new ResizeObserver(onResizeEntries);
      watchTheme();
      watchMounts();
      window.addEventListener("resize", scheduleApply);
      // Re-run a pass when the a11y preferences flip live (reduced-transparency
      // toggles solid↔glass; reduced-motion changes the scale).
      try {
        ["(prefers-reduced-transparency: reduce)", "(prefers-reduced-motion: reduce)", "(prefers-contrast: more)"].forEach(
          function (q) {
            var mq = window.matchMedia(q);
            var on = function () { scheduleApply(); };
            if (mq.addEventListener) mq.addEventListener("change", on);
            else if (mq.addListener) mq.addListener(on);
          }
        );
      } catch (_) {}
      applyPass();
      // Pointer-reactive specular (Genius #21): bind the single-surface pointer rim.
      try { bindSpec(); } catch (_) {}
      window.AppkitLiquidGlass = {
        supported: true,
        refresh: scheduleApply,
        clear: clearAll,
        // exposed for the visual-verification harness: force the fallback look
        // (drop our overrides) so the CSS blur-glass can be screenshotted alone.
        _disable: function () { _forceDisabled = true; clearAll(); setSpecActive(null); },
        _enable: function () { _forceDisabled = false; scheduleApply(); },
        _scale: function () { return activeScale(); },
        // the single surface currently carrying the pointer rim (verification harness).
        _specSurface: function () { return specActive; },
      };
    } catch (_) {
      // Any boot failure → leave the CSS glass entirely intact.
      clearAll();
      try { window.AppkitLiquidGlass = { supported: false, refresh: function () {} }; } catch (_) {}
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

// ── adaptiveGlass — dynamic legibility layer (composites over liquidGlass) ─────
// adaptiveGlass.js — DYNAMIC legibility for Liquid Glass over ANY background.
//
// Apple's Regular variant "blurs AND adjusts the luminosity of background content to
// maintain legibility" — the material is more muted over BRIGHT content and stays
// translucent/lit over DARK content, so foreground text/controls stay readable on any
// backdrop (a photo, a light theme, a gradient, the dark chat). A single static veil
// can't do that: tuned translucent for dark, it fails over a bright photo; tuned opaque
// for bright, it reads as a heavy slab over dark.
//
// So this module is the "smart" layer: for each glass surface it SAMPLES the backdrop
// luminance directly behind that surface and scales the surface's neutral veil opacity
// to it — gentle over dark, stronger over bright — keeping the theme's --fg text legible
// regardless of what's behind. It is theme-correct by construction: the veil is the
// theme's own --panel (dark panel on dark themes, light panel on light themes), which is
// already the right contrast for the theme's --fg, so it floors contrast in EITHER
// polarity. It runs on EVERY engine (not Chromium-gated) and composes with the SVG
// refraction (that sets backdrop-filter; this sets background-color — no conflict).

(function () {
  "use strict";

  // Surfaces that carry the glass material (mirror style.css's frosted set + liquidGlass).
  // Adaptive legibility runs under BOTH glass tiers (keyed on theme-frosted), so this
  // list must cover EVERY newly-glassed surface — chrome, chat bubbles, transient
  // indicators — or those surfaces lose adaptive ink/veil. #appkit-headshot is excluded
  // (gating dialog, kept opaque in CSS).
  var SURFACES = [
    // — Chrome / large panels (no flip → mute) —
    ".ow-window", "#sidebar", ".icon-rail", ".modal-content", ".admin-card",
    ".chat-top-bar", ".model-picker-menu", ".og-card", ".on-card", ".toast",
    ".appkit-chat-hint", ".attach-card", ".dropdown", ".overflow-menu", ".cp-popover",
    // — Chat bubbles (large → mute, no flip) —
    ".msg-ai", ".msg-user", ".msg-ooc",
    // — Small bars / transient pills (flip ink) —
    ".chat-input-bar", "#minimized-dock.ow-has-rows", ".thinking-section", ".tool-indicator",
  ].join(", ");
  var EXCLUDE_IDS = { "appkit-headshot": 1 };

  // The ONLY surfaces that adapt under the glass theme: the RECEIVED chat bubbles. Apple's
  // Messages received bubble flips polarity with the wallpaper — a LIGHT frost + DARK ink
  // over a bright wall, a DARK frost + LIGHT ink over a dark one. Chrome does NOT adapt (it
  // is a FIXED light glass; the old per-surface dark veil is retired and must not return),
  // and the SENT (blue) bubble never adapts (always blue + white). So this is just .msg-ai.
  var BUBBLE_ADAPTIVE = ".msg-ai";
  // ── #763 — the WELCOME HERO over the bare wallpaper ───────────────────────────
  // The hero (the big welcome wordmark, the subtitle, the inline "type /setup" link)
  // sits DIRECTLY over the wallpaper (#__wp) — NOT over the light glass chrome. So a
  // single fixed ink (the old light var(--fg)) is light-on-light over a LIGHT wallpaper
  // (~1.13:1, invisible). Like Apple's monochrome labels over content and like the
  // .msg-ai bubbles above, the hero must FLIP polarity with the wallpaper. Unlike a
  // bubble there is NO frost plate, so the ink sits on the wallpaper DIRECTLY: we pick
  // polarity at the linear-Y flip point, then verify APCA(ink ↔ wallpaper) clears the
  // floor, and ESCALATE the ink toward pure black / pure white (not a scrim — a free
  // wordmark over a photo wants a halo, not a plate) plus a contrasting halo backstop.
  // Ink-only + halo; no veil/background is ever painted (it's not a glass surface).
  var HERO_ADAPTIVE = "#welcome-screen .welcome-name, #welcome-screen .welcome-sub";
  var HERO_INK_DARK = [22, 25, 31];        // #16191f — the dark ink (matches the CSS default + chrome)
  var HERO_INK_LIGHT = [238, 241, 244];    // #eef1f4 — the light ink over a dark wallpaper
  var HERO_HALO_LIGHT = "0 1px 2px rgba(255,255,255,0.60), 0 0 3px rgba(255,255,255,0.50)"; // under DARK ink
  var HERO_HALO_DARK = "0 1px 2px rgba(0,0,0,0.62), 0 0 3px rgba(0,0,0,0.52)";              // under LIGHT ink
  // the LIGHT frost a received bubble takes over a BRIGHT backdrop (Apple's light received
  // bubble) — a near-white translucent material that reads with the dark INK_DARK label.
  // The DARK frost (over a dark/mid wall) is the CSS default (rgba(56,60,68,a)); its alpha
  // is the CSS var --ai-scrim-alpha so we can ESCALATE it per-bubble (see #744 below).
  var BUBBLE_LIGHT_RGB = [245, 246, 248];   // near-white frost tint over a BRIGHT wall
  var BUBBLE_DARK_RGB = [56, 60, 68];       // neutral dark frost tint (matches style.css default)

  // ── #744 — APCA legibility floor for the RECEIVED transcript ──────────────────
  // The chat transcript IS the game (read for hours) and is the most-cited legibility gap.
  // Polarity-flip ALONE (a dark-ink/light-ink choice at a single Y threshold) is not enough:
  // over a BUSY or SATURATED MID-TONE wallpaper neither pure-dark nor pure-white ink clears a
  // real contrast floor through a thin frost. So after we pick ink polarity we measure the
  // ACTUAL perceptual contrast with APCA (the algorithm WCAG 3 / the bronze guidance use), and
  // if it fails we ESCALATE this ONE bubble's scrim toward opaque until it clears. This is a
  // LOCAL per-bubble escalation (the CSS var --ai-scrim-alpha on that element) — NOT a global
  // theme-tinted body state (#739, blocked on #730); we stay strictly local and Vault-free.
  //
  // FLOOR = Lc 60. APCA "bronze" puts Lc 60 as the floor for fluent body text (the next rung,
  // Lc 75/90, is for fine/small text). The transcript is body prose read for a long sitting, so
  // 60 is the defensible minimum — high enough to never be the cited gap, low enough that a clear
  // wallpaper still reads as glass rather than a solid plate. (APCA Lc is unsigned-magnitude here;
  // we take |Lc| because polarity is already chosen.)
  var APCA_FLOOR = 60;
  // Per-bubble scrim escalation band: start at the CSS default and climb toward near-opaque.
  var SCRIM_BASE = 0.46;     // mirrors the style.css --ai-scrim-alpha default (worst-case floor)
  var SCRIM_MAX = 0.92;      // near-opaque cap — still a frost, never a flat solid slab
  var SCRIM_STEP = 0.06;     // climb granularity when APCA fails for this bubble's backdrop

  // Apple's adaptation is SIZE-DEPENDENT (WWDC25 219 + HIG Color):
  //   • SMALL bars/tiles (toolbars, tab bars — our composer bar, gadget tiles, the dock):
  //     the glass stays CLEAR and the SYMBOLS FLIP light↔dark to mirror the backdrop
  //     ("symbols and glyphs … flip from light to dark and vice versa … to maximize
  //     contrast"). No darkening of the glass.
  //   • LARGE surfaces (sidebars, windows, modals, menus): they "don't flip from light to
  //     dark — their surface area is too big and transitions would be distracting." Instead
  //     the Regular glass continuously "blurs AND adjusts the luminosity of background
  //     content to maintain legibility" — so we keep LIGHT --fg symbols and let a stronger
  //     adaptive veil mute a bright backdrop just enough to keep them legible.
  // The only darkening Apple sanctions is the Clear variant's literal 35% dimmer over bright
  // media (not used here — our surfaces carry text, so Regular is correct).
  var VEIL_MIN = 14;             // % --panel at a dark backdrop (translucent/lit) — both sizes
  var VEIL_MAX_SMALL = 22;       // small bars stay genuinely CLEAR (the symbol flip does the legibility work)
  var VEIL_MAX_LARGE = 48;       // large surfaces don't flip → glass mutes, but stays translucent (no opaque slab)
  // Linear-Y at which each veil reaches its cap. Small bars cross over WITH the ink flip
  // (steeper); large surfaces ramp gently so a bright backdrop still shows through the glass
  // ("adjusted luminosity," not a wall — Apple Regular over light content).
  var VEIL_FULL_AT_SMALL = 0.35;
  var VEIL_FULL_AT_LARGE = 0.62;
  // Small bars/tiles that FLIP (everything else in SURFACES is treated as large / no-flip).
  // The composer bar, gadget tiles, the dock, and the small transient pills (the
  // typing/thinking indicator, the tool-indicator chip) are small bars → flip the ink.
  // Large surfaces (windows, sidebar, modals, admin-card, toasts, chat bubbles, menus)
  // are NOT here → they mute via the adaptive veil and keep light --fg.
  var FLIP_SET = ".chat-input-bar, .og-card, #minimized-dock.ow-has-rows, .thinking-section, .tool-indicator";
  // LINEAR-Y flip point: backdrop above this ⇒ DARK ink. The WCAG black-vs-white crossover is
  // L≈0.18; the small bar's own veil darkens the effective background a touch, so the flip
  // sits just above it at 0.22 (≈ perceptual mid-grey sRGB≈0.5). 0.36 fired far too late —
  // surfaces over a perceptually half-bright backdrop kept light ink and washed out.
  var INK_THRESHOLD = 0.22;
  var INK_DARK = "#11151c";   // dark symbol/label colour over bright backdrops
  var DEBOUNCE_MS = 120;
  var SAMPLE_GRID = 5;        // NxN samples across the surface's backdrop region

  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  // Proper relative luminance: sRGB → linear, then Rec.709 weights (matches Apple/WCAG).
  function _lin(c) { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function relLum(r, g, b) { return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b); }

  // ── APCA (Accessible Perceptual Contrast Algorithm, the WCAG 3 / SAPC-APCA model) ──
  // A faithful, dependency-free port of the APCA-W3 0.1.9 core (the public-domain reference by
  // Andrew Somers / Myndex). We use it for the #744 transcript legibility floor: unlike WCAG 2's
  // luminance-ratio (which over/under-states contrast on mid-tones and for light-on-dark), APCA
  // models perceived lightness contrast and is polarity-aware — the right tool for "does this ink
  // clear a floor over THIS backdrop." Returns Lc (lightness contrast); sign encodes polarity, so
  // callers take Math.abs() when polarity is already chosen.
  function _apcaY(r, g, b) {
    // sRGB → screen luminance (APCA uses simple ^2.4 on 0..1, NOT the WCAG piecewise curve).
    var Rs = Math.pow(r / 255, 2.4), Gs = Math.pow(g / 255, 2.4), Bs = Math.pow(b / 255, 2.4);
    return 0.2126729 * Rs + 0.7151522 * Gs + 0.0721750 * Bs;
  }
  function apcaContrast(txt, bg) {
    // txt/bg = [r,g,b]. Constants are the APCA-W3 0.1.9 published values.
    var Ytxt = _apcaY(txt[0], txt[1], txt[2]);
    var Ybg = _apcaY(bg[0], bg[1], bg[2]);
    var BLK_THRS = 0.022, BLK_CLMP = 1.414;
    var SCALE_BoW = 1.14, SCALE_WoB = 1.14;
    var LO_CLIP = 0.1, DELTA_MIN = 0.0005;
    // soft-clamp blacks
    Ytxt = Ytxt > BLK_THRS ? Ytxt : Ytxt + Math.pow(BLK_THRS - Ytxt, BLK_CLMP);
    Ybg = Ybg > BLK_THRS ? Ybg : Ybg + Math.pow(BLK_THRS - Ybg, BLK_CLMP);
    if (Math.abs(Ybg - Ytxt) < DELTA_MIN) return 0;
    var out;
    if (Ybg > Ytxt) {            // normal polarity: dark text on lighter bg
      out = (Math.pow(Ybg, 0.56) - Math.pow(Ytxt, 0.57)) * SCALE_BoW;
      out = out < LO_CLIP ? 0 : out - 0.027;
    } else {                     // reverse polarity: light text on darker bg
      out = (Math.pow(Ybg, 0.65) - Math.pow(Ytxt, 0.62)) * SCALE_WoB;
      out = out > -LO_CLIP ? 0 : out + 0.027;
    }
    return out * 100;            // Lc
  }
  // Composite an opaque scrim (tint at alpha) over an opaque backdrop → the effective bubble
  // surface the ink actually sits on (standard src-over alpha blend; backdrop alpha = 1).
  function compositeOver(tint, alpha, backdrop) {
    var a = clamp(alpha, 0, 1);
    return [
      Math.round(tint[0] * a + backdrop[0] * (1 - a)),
      Math.round(tint[1] * a + backdrop[1] * (1 - a)),
      Math.round(tint[2] * a + backdrop[2] * (1 - a)),
    ];
  }
  function prefersContrast() {
    try { return !!(window.matchMedia && window.matchMedia("(prefers-contrast: more)").matches); } catch (_) { return false; }
  }

  // ── unified backdrop canvas (image OR gradient OR solid — composited) ─────────
  // The "background" can be ANYTHING: a solid theme colour, faint CSS pattern
  // gradients, a full-viewport wallpaper image, or any combination. A url()-only
  // path missed gradients entirely (they carry no url), so we paint ONE downscaled
  // viewport canvas from the page's actual backdrop layers — base colour, then each
  // background-image gradient, then any wallpaper image (back-to-front) — and sample
  // regions of it per surface. That makes the adaptation correct over a photo, a
  // light theme, a gradient theme, the dark chat, or a layered mix of them.
  var BACKDROP_MAXW = 96;   // downscaled viewport-canvas width (cheap to getImageData)
  var _bd = { cv: null, ctx: null, w: 0, h: 0, sig: "", base: null, tainted: false };
  var _imgCache = {};       // url -> { img } | 'pending' | 'failed'

  function clamp255(x) { return Math.max(0, Math.min(255, Math.round(parseFloat(x)))); }
  function parseAlpha(x) { x = String(x).trim(); return x.indexOf("%") >= 0 ? parseFloat(x) / 100 : parseFloat(x); }
  function rgbaStr(c) { return "rgba(" + c[0] + "," + c[1] + "," + c[2] + "," + (c[3] == null ? 1 : c[3]) + ")"; }

  // Parse a CSS colour (computed values resolve var()/color-mix() → rgb/rgba). Returns [r,g,b,a] or null.
  function parseColor(s) {
    if (!s) return null; s = String(s).trim();
    if (s === "transparent") return [0, 0, 0, 0];
    var m = s.match(/^rgba?\(([^)]+)\)/i);
    if (m) {
      var p = m[1].split(/[,\/\s]+/).filter(function (x) { return x !== ""; });
      if (p.length >= 3) return [clamp255(p[0]), clamp255(p[1]), clamp255(p[2]), p[3] !== undefined ? parseAlpha(p[3]) : 1];
    }
    var h = s.match(/^#([0-9a-fA-F]{3,8})$/);
    if (h) {
      var x = h[1];
      if (x.length === 3) x = x[0] + x[0] + x[1] + x[1] + x[2] + x[2];
      if (x.length >= 6) {
        var a = x.length >= 8 ? parseInt(x.slice(6, 8), 16) / 255 : 1;
        return [parseInt(x.slice(0, 2), 16), parseInt(x.slice(2, 4), 16), parseInt(x.slice(4, 6), 16), a];
      }
    }
    return null;
  }

  // Split on a top-level separator only (commas inside rgb()/gradient() are kept).
  function splitTopLevel(s, sep) {
    var out = [], depth = 0, cur = "";
    for (var i = 0; i < s.length; i++) {
      var c = s[i];
      if (c === "(") depth++; else if (c === ")") depth--;
      if (c === sep && depth === 0) { out.push(cur); cur = ""; } else cur += c;
    }
    if (cur.trim() !== "") out.push(cur);
    return out;
  }

  function parseAngle(h) {
    h = h.trim().toLowerCase();
    if (h.indexOf("deg") >= 0) return parseFloat(h);
    if (h.indexOf("turn") >= 0) return parseFloat(h) * 360;
    if (h.indexOf("grad") >= 0) return parseFloat(h) * 0.9;
    if (h.indexOf("rad") >= 0) return parseFloat(h) * 180 / Math.PI;
    var map = { "to top": 0, "to right": 90, "to bottom": 180, "to left": 270,
      "to top right": 45, "to right top": 45, "to bottom right": 135, "to right bottom": 135,
      "to bottom left": 225, "to left bottom": 225, "to top left": 315, "to left top": 315 };
    return map[h] != null ? map[h] : 180;
  }

  // Colour stops from the gradient body parts; fill missing positions by interpolation.
  function parseStops(parts) {
    var stops = [];
    for (var i = 0; i < parts.length; i++) {
      var t = parts[i].trim();
      // colour first, then an OPTIONAL position (% only — px positions are ignored).
      var cm = t.match(/^(rgba?\([^)]*\)|#[0-9a-fA-F]+|[a-zA-Z]+)(?:\s+([-\d.]+)%)?/);
      if (!cm) continue;
      var col = parseColor(cm[1]); if (!col) continue;
      var pos = cm[2] !== undefined ? parseFloat(cm[2]) / 100 : null;
      stops.push({ col: col, pos: pos });
    }
    if (!stops.length) return stops;
    if (stops[0].pos == null) stops[0].pos = 0;
    if (stops[stops.length - 1].pos == null) stops[stops.length - 1].pos = 1;
    for (var j = 1; j < stops.length - 1; j++) {
      if (stops[j].pos != null) continue;
      var prev = j - 1, next = j + 1;
      while (next < stops.length && stops[next].pos == null) next++;
      var p0 = stops[prev].pos, p1 = stops[next].pos != null ? stops[next].pos : 1;
      stops[j].pos = p0 + (p1 - p0) * ((j - prev) / (next - prev));
    }
    return stops;
  }

  function avgColor(stops) {
    var r = 0, g = 0, b = 0, a = 0;
    for (var i = 0; i < stops.length; i++) { r += stops[i].col[0]; g += stops[i].col[1]; b += stops[i].col[2]; a += (stops[i].col[3] == null ? 1 : stops[i].col[3]); }
    var n = stops.length || 1;
    return [Math.round(r / n), Math.round(g / n), Math.round(b / n), a / n];
  }

  function paintGradient(ctx, w, h, css) {
    var lp = css.indexOf("(");
    var open = css.slice(0, lp).trim().toLowerCase();
    var inner = css.slice(lp + 1, css.lastIndexOf(")"));
    var parts = splitTopLevel(inner, ",");
    if (!parts.length) return;
    var radial = open.indexOf("radial") >= 0, conic = open.indexOf("conic") >= 0;
    var head = parts[0].trim();
    var headIsConfig = /^(to\s|[-\d.]+deg|[-\d.]+turn|[-\d.]+g?rad|circle|ellipse|at\s|closest|farthest|from\s)/i.test(head);
    var stops = parseStops(headIsConfig ? parts.slice(1) : parts);
    if (!stops.length) return;
    if (conic) { ctx.fillStyle = rgbaStr(avgColor(stops)); ctx.fillRect(0, 0, w, h); return; }
    var g;
    if (radial) {
      g = ctx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2, Math.max(w, h) * 0.75);
    } else {
      var a = (headIsConfig ? parseAngle(head) : 180) * Math.PI / 180;
      var dx = Math.sin(a), dy = -Math.cos(a);
      var len = Math.abs(w * dx) + Math.abs(h * dy);
      g = ctx.createLinearGradient(w / 2 - dx * len / 2, h / 2 - dy * len / 2, w / 2 + dx * len / 2, h / 2 + dy * len / 2);
    }
    for (var i = 0; i < stops.length; i++) { try { g.addColorStop(clamp(stops[i].pos, 0, 1), rgbaStr(stops[i].col)); } catch (_) {} }
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);
  }

  function drawCover(ctx, img, w, h) {
    var iw = img.naturalWidth || img.width, ih = img.naturalHeight || img.height;
    if (!iw || !ih) return;
    var s = Math.max(w / iw, h / ih), dw = iw * s, dh = ih * s;
    ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
  }

  function ensureImg(url) {
    var rec = _imgCache[url];
    if (rec && rec !== "pending" && rec !== "failed") return rec;
    if (rec === "pending" || rec === "failed") return null;
    _imgCache[url] = "pending";
    var img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = function () { _imgCache[url] = { img: img }; schedule(); };
    img.onerror = function () { _imgCache[url] = "failed"; };
    img.src = url;
    return null;
  }

  // The backdrop element chain, back-to-front (html → body → known wallpaper containers).
  function backdropChain() {
    var chain = [];
    if (document.documentElement) chain.push(document.documentElement);
    if (document.body) chain.push(document.body);
    var ids = ["__wp", "wallpaper", "app-bg", "background", "desktop"];
    for (var i = 0; i < ids.length; i++) { var e = document.getElementById(ids[i]); if (e) chain.push(e); }
    return chain;
  }

  // Build (or reuse) the unified downscaled backdrop canvas. Returns the cache record.
  function buildBackdrop() {
    var vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
    var w = BACKDROP_MAXW, h = Math.max(1, Math.round(BACKDROP_MAXW * vh / vw));
    var chain = backdropChain();
    // First scan: a signature + the layer plan, so we don't repaint on every scroll.
    var sig = w + "x" + h, plan = [], base = null;
    for (var i = 0; i < chain.length; i++) {
      var cs; try { cs = getComputedStyle(chain[i]); } catch (_) { continue; }
      var col = parseColor(cs.backgroundColor);
      if (col && col[3] > 0.05) { base = col; sig += "|c" + col.join(","); plan.push({ fill: col }); }
      var bi = cs.backgroundImage || "";
      if (bi && bi !== "none") {
        var imgs = splitTopLevel(bi, ",");
        for (var j = imgs.length - 1; j >= 0; j--) {   // CSS paints first-listed on top → reverse
          var layer = imgs[j].trim();
          var u = layer.match(/^url\((['"]?)(.*?)\1\)$/);
          if (u) { plan.push({ url: u[2] }); sig += "|u" + u[2]; }
          else if (/gradient\(/i.test(layer)) { plan.push({ grad: layer }); sig += "|g" + layer.length; }
        }
      }
    }
    // #9 — the mesh wallpaper (#__wp .login-bg-gradient, theme.js/login_bg.js) paints its
    // actual colour LOBES on ::before/::after PSEUDO-elements (meshGradient.css); the real
    // element only ever carries a flat --lbg-base fill (already captured above via #__wp's
    // own mirrored background-color). getComputedStyle(el) can never see a pseudo's
    // background, so without this the sampler always reads that flat mirrored base and the
    // hero/bubble ink resolves against a color the mesh may not actually be showing at that
    // screen position — the hero can wash into a bright lobe it never detected. Sample the
    // mesh child's pseudo-elements directly so the plan carries the SAME gradients the user
    // actually sees (::after paints on top of ::before).
    var meshEl = document.querySelector("#__wp .login-bg-gradient, .login-bg-gradient");
    if (meshEl) {
      ["::before", "::after"].forEach(function (pseudo) {
        var pcs; try { pcs = getComputedStyle(meshEl, pseudo); } catch (_) { return; }
        if (!pcs) return;
        var pbi = pcs.backgroundImage || "";
        if (!pbi || pbi === "none") return;
        var pimgs = splitTopLevel(pbi, ",");
        for (var k = pimgs.length - 1; k >= 0; k--) {
          var players = pimgs[k].trim();
          if (/gradient\(/i.test(players)) { plan.push({ grad: players }); sig += "|m" + pseudo + players.length; }
        }
      });
    }
    if (_bd.sig === sig && _bd.cv) return _bd;
    var cv = _bd.cv || document.createElement("canvas");
    cv.width = w; cv.height = h;
    var ctx = cv.getContext("2d", { willReadFrequently: true });
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = base ? rgbaStr(base) : "#282c34"; ctx.fillRect(0, 0, w, h);
    var pending = false;
    for (var p = 0; p < plan.length; p++) {
      var it = plan[p];
      if (it.fill) { ctx.fillStyle = rgbaStr(it.fill); ctx.fillRect(0, 0, w, h); }
      else if (it.grad) { try { paintGradient(ctx, w, h, it.grad); } catch (_) {} }
      else if (it.url) {
        var rec = ensureImg(it.url);
        if (!rec) { pending = true; continue; }
        try { drawCover(ctx, rec.img, w, h); } catch (_) {}
      }
    }
    var tainted = false;
    try { ctx.getImageData(0, 0, 1, 1); } catch (_) { tainted = true; }
    // sig keeps a |p marker while an image is still loading so the next pass rebuilds.
    _bd = { cv: cv, ctx: ctx, w: w, h: h, sig: pending ? sig + "|p" : sig, base: base, tainted: tainted };
    return _bd;
  }

  // Average luminance of the backdrop behind `rect` (viewport px). Returns 0..1 or null.
  function backdropLuminance(rect) {
    var vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
    var bd = buildBackdrop();
    if (bd && bd.cv && !bd.tainted) {
      var sx = bd.w / vw, sy = bd.h / vh, total = 0, n = 0;
      for (var gy = 0; gy < SAMPLE_GRID; gy++) {
        for (var gx = 0; gx < SAMPLE_GRID; gx++) {
          var vx = rect.left + (rect.width * (gx + 0.5)) / SAMPLE_GRID;
          var vy = rect.top + (rect.height * (gy + 0.5)) / SAMPLE_GRID;
          var ix = clamp(Math.round(vx * sx), 0, bd.w - 1), iy = clamp(Math.round(vy * sy), 0, bd.h - 1);
          try {
            var d = bd.ctx.getImageData(ix, iy, 1, 1).data;
            total += relLum(d[0], d[1], d[2]); n++;
          } catch (_) {}
        }
      }
      if (n) return total / n;
    }
    // Tainted (cross-origin wallpaper w/o CORS): use the resolved base colour if we have it.
    if (bd && bd.base) return relLum(bd.base[0], bd.base[1], bd.base[2]);
    // Deepest fallback: the computed background-color of the element behind the centre.
    try {
      var cx = clamp(rect.left + rect.width / 2, 0, vw - 1);
      var cy = clamp(rect.top + rect.height / 2, 0, vh - 1);
      var els = document.elementsFromPoint(cx, cy);
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.closest && el.closest(SURFACES)) continue; // skip the glass itself / glass chrome
        var c2 = parseColor(getComputedStyle(el).backgroundColor || "");
        if (c2 && (c2[3] == null || c2[3] > 0.4)) return relLum(c2[0], c2[1], c2[2]);
      }
    } catch (_) {}
    return null;
  }

  // Average RGB of the backdrop behind `rect` (viewport px). Returns [r,g,b] or null. Used by
  // the #744 APCA floor — we need the backdrop COLOUR (not just its luminance) so we can composite
  // the scrim over it and measure the real ink↔surface contrast.
  function backdropAvgColor(rect) {
    var vw = window.innerWidth || 1280, vh = window.innerHeight || 800;
    var bd = buildBackdrop();
    if (bd && bd.cv && !bd.tainted) {
      var sx = bd.w / vw, sy = bd.h / vh, rs = 0, gs = 0, bs = 0, n = 0;
      for (var gy = 0; gy < SAMPLE_GRID; gy++) {
        for (var gx = 0; gx < SAMPLE_GRID; gx++) {
          var vx = rect.left + (rect.width * (gx + 0.5)) / SAMPLE_GRID;
          var vy = rect.top + (rect.height * (gy + 0.5)) / SAMPLE_GRID;
          var ix = clamp(Math.round(vx * sx), 0, bd.w - 1), iy = clamp(Math.round(vy * sy), 0, bd.h - 1);
          try { var d = bd.ctx.getImageData(ix, iy, 1, 1).data; rs += d[0]; gs += d[1]; bs += d[2]; n++; } catch (_) {}
        }
      }
      if (n) return [Math.round(rs / n), Math.round(gs / n), Math.round(bs / n)];
    }
    if (bd && bd.base) return [bd.base[0], bd.base[1], bd.base[2]];
    return null;
  }

  // #744 — for a received bubble over a sampled backdrop, pick the polarity (per the existing
  // linear-Y flip), then ESCALATE this bubble's scrim alpha until the APCA(ink↔composited-surface)
  // contrast clears APCA_FLOOR (or we hit SCRIM_MAX). Returns { ink, frostRgb, scrimAlpha, lc }.
  // The surface the ink truly sits on = the frost tint composited over the wallpaper at scrimAlpha
  // (the bubble blurs the wall but the scrim is opaque-over the blurred result), so that is what we
  // measure. Polarity-flip alone is the floor; the scrim escalation is the guarantee.
  function resolveBubbleScrim(L, bgRgb) {
    var dark = L >= INK_THRESHOLD;          // bright backdrop → DARK ink + light frost
    var ink = dark ? parseColor(INK_DARK).slice(0, 3) : [255, 255, 255];
    var frost = dark ? BUBBLE_LIGHT_RGB : BUBBLE_DARK_RGB;
    var a = SCRIM_BASE, lc = 0, surface;
    for (;;) {
      surface = compositeOver(frost, a, bgRgb);
      lc = Math.abs(apcaContrast(ink, surface));
      if (lc >= APCA_FLOOR || a >= SCRIM_MAX) break;
      a = Math.min(SCRIM_MAX, a + SCRIM_STEP);
    }
    return { ink: ink, frostRgb: frost, scrimAlpha: a, lc: lc, dark: dark };
  }

  // #763 — for the welcome hero over a sampled wallpaper, pick ink polarity (the same
  // linear-Y flip the small bars use), then verify APCA(ink ↔ wallpaper) clears the floor
  // and ESCALATE the ink toward pure black / pure white until it does (or it's already
  // maxed). The hero has no frost plate, so the ink sits on the wallpaper DIRECTLY — that
  // is the pair we measure. Returns { ink, halo, dark, lc }. A contrasting halo is the
  // backstop floor for a free wordmark over a busy/edge backdrop (mirrors the bubble halo).
  function resolveHeroInk(L, bgRgb) {
    var dark = L >= INK_THRESHOLD;          // bright wallpaper → DARK ink; dark wallpaper → LIGHT ink
    var ink = dark ? HERO_INK_DARK.slice() : HERO_INK_LIGHT.slice();
    var target = dark ? [0, 0, 0] : [255, 255, 255];  // escalate toward this if the floor isn't met
    var lc = Math.abs(apcaContrast(ink, bgRgb));
    // climb the ink toward pure black/white in a few steps if a mid-tone wallpaper starves it.
    for (var step = 0; step < 6 && lc < APCA_FLOOR; step++) {
      ink = [
        Math.round(ink[0] + (target[0] - ink[0]) * 0.5),
        Math.round(ink[1] + (target[1] - ink[1]) * 0.5),
        Math.round(ink[2] + (target[2] - ink[2]) * 0.5),
      ];
      lc = Math.abs(apcaContrast(ink, bgRgb));
    }
    return { ink: ink, halo: dark ? HERO_HALO_LIGHT : HERO_HALO_DARK, dark: dark, lc: lc };
  }

  // ── apply ───────────────────────────────────────────────────────────────────
  function isFrosted() { return !!(document.body && document.body.classList.contains("theme-frosted")); }

  function applyTo(el) {
    try {
      if (el.id && EXCLUDE_IDS[el.id]) return;
      var r = el.getBoundingClientRect();
      // The hero text (esp. the one-line subtitle) is a THIN strip — a flat 24px floor
      // skipped .welcome-sub entirely (it stayed at the dark CSS default, unreadable over
      // a dark/busy wallpaper). Hero elements are text, so a thin sample is fine; relax the
      // height floor for them (keep the width floor so a collapsed/empty node is still skipped).
      var heroEl = false; try { heroEl = el.matches(HERO_ADAPTIVE); } catch (_) {}
      var minH = heroEl ? 10 : 24;
      if (r.width < 24 || r.height < minH) return;
      var L = backdropLuminance({ left: r.left, top: r.top, width: r.width, height: r.height });
      if (L == null) {
        el.style.removeProperty("background-color");
        el.style.removeProperty("color"); el.style.removeProperty("text-shadow");
        el.style.removeProperty("-webkit-text-fill-color");
        el.removeAttribute("data-adaptive-veil"); el.removeAttribute("data-adaptive-ink");
        return;
      }
      // CHAT BUBBLE polarity (Apple Messages received bubble). Over a BRIGHT wallpaper the
      // bubble becomes a LIGHT frost + DARK ink; over a DARK one it keeps the CSS dark frost
      // + light ink (we just clear our overrides). Chrome never reaches here (pass() sends
      // only bubbles under the glass theme), so the old per-surface dark veil can't crawl back.
      var isBubble = false; try { isBubble = el.matches(BUBBLE_ADAPTIVE); } catch (_) {}
      if (isBubble) {
        // #744 — guarantee the transcript clears the APCA floor over ANY wallpaper. Sample the
        // backdrop COLOUR (not just L), pick polarity, then escalate THIS bubble's scrim alpha
        // until APCA(ink↔composited-surface) ≥ APCA_FLOOR. Frost-only, local, Vault-free.
        var bg = backdropAvgColor({ left: r.left, top: r.top, width: r.width, height: r.height });
        if (!bg) { // no readable backdrop colour → fall back to the CSS default (already floored at SCRIM_BASE)
          el.style.removeProperty("background-color"); el.style.removeProperty("color");
          el.style.removeProperty("text-shadow"); el.style.removeProperty("--ai-scrim-alpha");
          el.removeAttribute("data-adaptive-veil"); el.removeAttribute("data-adaptive-ink");
          el.removeAttribute("data-apca-lc");
          return;
        }
        var s = resolveBubbleScrim(L, bg);
        // Drive the scrim alpha through the CSS var so the floored fill (style.css) and the JS
        // escalation share ONE source of truth; set the frost tint + ink to match the polarity.
        el.style.setProperty("--ai-scrim-alpha", s.scrimAlpha.toFixed(3));
        el.style.setProperty("background-color",
          "rgba(" + s.frostRgb[0] + "," + s.frostRgb[1] + "," + s.frostRgb[2] + ",var(--ai-scrim-alpha))", "important");
        if (s.dark) {
          el.style.setProperty("color", INK_DARK, "important");
          el.style.setProperty("text-shadow", "none", "important");
          el.setAttribute("data-adaptive-ink", "dark");
        } else {
          // white ink over the dark frost — keep the legibility halo from the CSS default.
          el.style.removeProperty("color");
          el.style.setProperty("text-shadow", "0 1px 2px rgba(0,0,0,0.55), 0 0 2px rgba(0,0,0,0.40)", "important");
          el.setAttribute("data-adaptive-ink", "light");
        }
        el.setAttribute("data-adaptive-veil", "bubble");
        el.setAttribute("data-apca-lc", Math.round(s.lc));   // probe hook for the smoke test
        return;
      }
      // #763 — the WELCOME HERO (wordmark + subtitle) over the bare wallpaper. Ink-only
      // polarity flip with the APCA floor measured DIRECTLY against the wallpaper (no
      // frost plate). We never paint a background here — only the ink + a contrasting
      // halo. The CSS default is dark-ink+light-halo; we restate or flip it per backdrop.
      var isHero = false; try { isHero = el.matches(HERO_ADAPTIVE); } catch (_) {}
      if (isHero) {
        var hbg = backdropAvgColor({ left: r.left, top: r.top, width: r.width, height: r.height });
        if (!hbg) {  // no readable wallpaper colour → let the CSS default stand
          el.style.removeProperty("color");
          el.style.removeProperty("-webkit-text-fill-color");
          el.style.removeProperty("text-shadow");
          el.removeAttribute("data-adaptive-ink"); el.removeAttribute("data-apca-lc");
          return;
        }
        var h = resolveHeroInk(L, hbg);
        var hcss = "rgb(" + h.ink[0] + "," + h.ink[1] + "," + h.ink[2] + ")";
        el.style.setProperty("color", hcss, "important");
        // .welcome-name uses -webkit-text-fill-color (it was a clipped gradient) — drive it too.
        el.style.setProperty("-webkit-text-fill-color", hcss, "important");
        el.style.setProperty("text-shadow", h.halo, "important");
        el.setAttribute("data-adaptive-ink", h.dark ? "dark" : "light");
        el.setAttribute("data-apca-lc", Math.round(h.lc));
        return;
      }

      var small = false;
      try { small = el.matches(FLIP_SET); } catch (_) {}
      // SMALL bars stay CLEAR (low veil); LARGE surfaces don't flip, so their glass adapts
      // (a stronger veil over bright) to keep the light --fg symbols legible.
      var vmax = small ? VEIL_MAX_SMALL : VEIL_MAX_LARGE;
      // Reach the cap by the per-size full-mute point. Small bars cross over WITH the ink
      // flip (steeper); large surfaces ramp gently so a bright backdrop still shows through
      // (Apple "adjusted luminosity," never an opaque slab).
      var f = clamp(L / (small ? VEIL_FULL_AT_SMALL : VEIL_FULL_AT_LARGE), 0, 1);
      var pct = Math.round(clamp(VEIL_MIN + (vmax - VEIL_MIN) * f, VEIL_MIN, vmax));
      el.style.setProperty("background-color",
        "color-mix(in srgb, var(--panel, var(--bg)) " + pct + "%, transparent)", "important");
      el.setAttribute("data-adaptive-veil", String(pct));

      if (small && L >= INK_THRESHOLD) {
        // SMALL + BRIGHT: flip symbols DARK (the glass stays clear). Faint light halo = margin.
        el.style.setProperty("color", INK_DARK, "important");
        el.style.setProperty("text-shadow", "0 0 2px rgba(255,255,255,0.55)", "important");
        el.setAttribute("data-adaptive-ink", "dark");
      } else {
        // SMALL+dark, or any LARGE surface: keep light --fg (large elements never flip).
        el.style.removeProperty("color");
        // Stronger dark halo: light ink lingers on near-threshold mid-tones (the transition
        // band), so floor its legibility there until the flip takes over.
        el.style.setProperty("text-shadow", "0 1px 3px rgba(0,0,0,0.55)", "important");
        el.setAttribute("data-adaptive-ink", "light");
      }
    } catch (_) {}
  }

  function isGlassFull() { return !!(document.body && document.body.classList.contains("glass-full")); }

  function pass() {
    // Accessibility wins over the optics (WWDC25): under Increase Contrast the system goes
    // predominantly black/white + a contrasting border — the subtle adaptive flip is dropped.
    // Drop our overrides and let the CSS high-contrast treatment stand.
    //
    // UNIFORMITY (owner: "every light surface needs the SAME properties — the kube music
    // player recreated everywhere"; "there should be no old dark glass at all"): under the
    // GLASS THEME — BOTH tiers (Full Glass = theme-frosted+glass-full, Frosted = theme-frosted
    // alone) — the surface is now a FIXED light glass (the kube 0.60 light fill from style.css,
    // identical on every surface; Full adds SVG refraction + specular, Frosted a CSS blur). The
    // adaptive layer used to paint a per-surface, backdrop-varying DARK veil — that was the "old
    // dark glass" the owner is retiring: it would make each surface look DIFFERENT and darken the
    // fixed light fill. So adaptiveGlass STANDS DOWN whenever theme-frosted is active (it never
    // paints a veil/ink under the glass theme). The module + its functions (SURFACES, FLIP_SET,
    // INK_THRESHOLD, the backdrop sampler, etc.) are kept intact for the source-pinned tests; only
    // the runtime is gated. There is no longer any glass tier that wants the adaptive veil.
    // (isGlassFull is retained as a named helper for the source-pinned tests; the standdown is
    // now keyed on theme-frosted, which covers BOTH tiers, so glass-full is a subset of it.)
    // Accessibility wins: under Increase Contrast the system goes black/white + a border;
    // drop ALL our overrides and let the CSS high-contrast treatment stand.
    if (prefersContrast()) { _dropTagged(null); return; }

    // GLASS THEME (BOTH tiers — theme-frosted): the CHROME is a FIXED light glass (the kube
    // 0.60 fill; Full adds SVG refraction, Frosted a CSS blur). The old per-surface, backdrop-
    // varying DARK veil is RETIRED and must NOT crawl back — so chrome STANDS DOWN. The ONLY
    // adaptive surfaces are the RECEIVED chat bubbles (.msg-ai), which flip polarity like
    // Apple's Messages (light frost+dark ink over a bright wall, dark frost+light ink over a
    // dark one). So: clear every NON-bubble override, then run the adaptive pass on bubbles.
    // (isGlassFull is retained as a named helper for the source-pinned tests; the standdown is
    // keyed on theme-frosted, which covers BOTH tiers, so glass-full is a subset of it.)
    if (isFrosted() || isGlassFull()) {
      // The adaptive surfaces under the glass theme: the RECEIVED chat bubbles (#744) AND
      // the welcome HERO over the bare wallpaper (#763). Both flip ink polarity with the
      // backdrop; everything else (the fixed light glass chrome) stands down.
      var ADAPTIVE_SEL = BUBBLE_ADAPTIVE + ", " + HERO_ADAPTIVE;
      _dropTagged(ADAPTIVE_SEL);      // chrome (+ anything non-adaptive) drops; bubbles + hero kept
      buildBackdrop();                // unified backdrop canvas; bubbles + hero sample it
      var nodes = document.querySelectorAll(ADAPTIVE_SEL);
      for (var j = 0; j < nodes.length; j++) {
        var el = nodes[j];
        if (el.offsetParent === null && getComputedStyle(el).position !== "fixed") continue;
        applyTo(el);
      }
      return;
    }

    // No glass theme → full standdown (the static CSS stands).
    _dropTagged(null);
  }

  // Remove our inline overrides from previously-tagged elements. keepSel (a selector) is
  // spared so a bubble's live adaptive ink isn't cleared on the same pass that re-applies it.
  function _dropTagged(keepSel) {
    var tagged = document.querySelectorAll("[data-adaptive-veil],[data-adaptive-ink]");
    for (var i = 0; i < tagged.length; i++) {
      var el = tagged[i];
      if (keepSel) { try { if (el.matches(keepSel)) continue; } catch (_) {} }
      el.style.removeProperty("background-color");
      el.style.removeProperty("color");
      el.style.removeProperty("-webkit-text-fill-color");   // #763 — drop the hero ink override too
      el.style.removeProperty("text-shadow");
      el.style.removeProperty("--ai-scrim-alpha");   // #744 — drop the per-bubble scrim escalation too
      el.removeAttribute("data-adaptive-veil");
      el.removeAttribute("data-adaptive-ink");
      el.removeAttribute("data-apca-lc");
    }
  }

  var _t = 0;
  function schedule() {
    if (_t) return;
    _t = setTimeout(function () { _t = 0; pass(); }, DEBOUNCE_MS);
  }

  function init() {
    try {
      schedule();
      window.addEventListener("resize", schedule);
      window.addEventListener("scroll", schedule, { passive: true, capture: true });
      // re-sample when the theme or the backdrop changes (no new event — observe body).
      var mo = new MutationObserver(schedule);
      mo.observe(document.body, { attributes: true, attributeFilter: ["class", "style"], childList: true, subtree: false });
      // re-sample when CHAT MESSAGES are added/stream in — the body observer is subtree:false,
      // so a freshly-rendered received bubble (.msg-ai) would keep its default light-on-dark ink
      // over a BRIGHT wallpaper until an unrelated scroll/resize fired. Observe #chat-history so
      // the adaptive polarity flip lands as the bubble appears. Debounced (schedule), so streaming
      // text doesn't thrash. (chat-history is static in index.html, so it exists at init.)
      var _chat = document.getElementById("chat-history");
      if (_chat) {
        var cmo = new MutationObserver(schedule);
        cmo.observe(_chat, { childList: true, subtree: true });
      }
      ["(prefers-reduced-transparency: reduce)", "(prefers-contrast: more)"].forEach(function (q) {
        try { var mq = window.matchMedia(q); (mq.addEventListener ? mq.addEventListener : mq.addListener).call(mq, "change", schedule); } catch (_) {}
      });
      // #744 — expose the APCA helpers + the floor so the browser-smoke probe can MEASURE the
      // resolved fg/bg pair clears the floor (and the source-pinned test can assert their presence).
      window.AppkitAdaptiveGlass = {
        refresh: schedule, _pass: pass,
        apcaContrast: apcaContrast, compositeOver: compositeOver,
        resolveBubbleScrim: resolveBubbleScrim, APCA_FLOOR: APCA_FLOOR,
      };
    } catch (_) {
      try { window.AppkitAdaptiveGlass = { refresh: function () {} }; } catch (__) {}
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else { init(); }
})();
