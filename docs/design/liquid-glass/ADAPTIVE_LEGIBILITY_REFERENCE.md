# Liquid Glass — Adaptive Symbol/Label Legibility: Mechanism + True-Parity Web Replication

iOS 26 / iPadOS 26 / macOS 26 "Tahoe" (Liquid Glass, introduced WWDC25, June 2025).
Companion to `LIQUID_GLASS_REFERENCE.md`. Every Apple quote below is **verbatim** from an
Apple-authentic source (developer.apple.com HIG, Apple developer docs, WWDC25 session
transcripts). Web-replication sources are explicitly marked **[non-authoritative]**.

> **Source legend:** `[HIG]` Human Interface Guidelines · `[DOC]` Apple developer documentation ·
> `[WWDC]` WWDC25 session transcript · `[WEB‡]` non-authoritative third-party (web-replication only).

---

## TL;DR — the exact technique

- **Adaptive symbol/label color is NOT a per-symbol hard black↔white flip.** Apple flips the *whole
  small element* (navbar/tabbar) and its symbols *together* light↔dark based on the backdrop, and on
  the **Regular** variant the glass *itself continuously adapts* (blur + luminosity adjustment + tint
  amount + dynamic range + shadow opacity) so the monochrome label stays legible. The light/dark flip
  is a discrete state on small bars; the legibility work underneath it is continuous.
- **"Vibrancy" is the real engine** — not transparency, not opacity. It is a blend that takes color
  from the backdrop. Apple's tinting "**generates a range of tones that are mapped to content
  brightness underneath**" — i.e. a content-brightness-derived tone map, "like colored glass."
- **Apple never darkens the *Regular* glass to keep a light symbol; it keeps the glass clear and
  adapts the symbol** (flips it + tweaks shadow/tint). Darkening only appears as (a) the **Clear**
  variant's required **35%-opacity dimming layer** over bright media, and (b) a *scroll-edge* "subtle
  dimming" the glass swaps to when dark content scrolls under.
- **Web parity = two layers.** (1) **Optics**: `backdrop-filter` blur+saturate + an SVG
  `feDisplacementMap` (refraction/lensing) + a rim-light specular. (2) **Legibility**: emulate
  vibrancy with `mix-blend-mode: luminosity` (or `plus-lighter` for the "frost") on the label layer,
  AND an adaptive black/white driver — `contrast-color()` where supported (Safari 26+), else a
  measured backdrop-luminance JS flip (sRGB-linear Y, threshold ≈ 0.36) toggling a CSS class.
- **Accessibility is non-negotiable and overrides the optics**: Reduce Transparency → frostier/near
  opaque; Increase Contrast → elements go **predominantly black or white with a contrasting border**;
  Reduce Motion → kill the elastic/specular animation. Honor `prefers-reduced-transparency`,
  `prefers-contrast`, `prefers-reduced-motion`.

---

## 1. ADAPTIVE SYMBOL/LABEL COLOR — hard flip or continuous? what drives it?

**It is BOTH, on two different axes.** Apple is explicit that two things happen:

**(a) A discrete light↔dark *flip* of small elements and their symbols, driven by the backdrop.**
Small bars flip as a unit; symbols mirror the flip to maximize contrast:

> "For smaller elements like toolbars and tab bars, the system can adapt Liquid Glass between a light
> and dark appearance in response to the underlying content. By default, symbols and text on these
> elements follow a monochromatic color scheme, **becoming darker when the underlying content is
> light, and lighter when it's dark.**"
> — `[HIG]` Color, https://developer.apple.com/design/human-interface-guidelines/color

> "Small elements like navbars and tabbars, constantly adapt their appearance depending on what's
> behind them. **They also flip from light to dark based on the background** to make sure the material
> looks as good as possible and is easily discernible. … To maintain legibility, **symbols and glyphs
> on top of Liquid Glass, do the same. They flip from light to dark and vice versa, mirroring the
> glass's behavior to maximize contrast.** All content placed on the Regular variant will
> automatically receive this treatment."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

So the symbol color tracks the *element's* light/dark state. The flip is **discrete** (light or
dark), but the trigger is the continuously-evaluated backdrop. Note the size cutoff — **big elements
do NOT flip** (a full sidebar/menu flipping would be distracting); they adapt only the underlying
material:

> "Bigger elements, like menus or sidebars also adapt based on context, **but they don't flip from
> light to dark. Their surface area is too big and transitions like these would be distracting.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**(b) A *continuous* adaptation of the glass itself underneath the symbol** — this is the part that
holds legibility moment-to-moment without flipping. The Regular variant continuously blurs +
luminosity-adjusts the backdrop and shifts tint amount, dynamic range, and shadow opacity:

> "Its primary goal is to remain visually clear, deferring to the content underneath. But it's also
> **constantly, subtly changing to ensure legibility** … each layer continuously adapts based on
> what's behind it. **As text scrolls underneath, shadows become more prominent to create additional
> separation. The amount of tint and the dynamic range shift to always ensure buttons remain legible,
> while letting as much of the content through as possible.** And when needed, it can also
> independently switch between light and dark."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "The *regular* variant **blurs and adjusts the luminosity of background content** to maintain
> legibility of text and other foreground elements."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

The element is also backdrop-aware in its **shadow**, not just its fill — it raises shadow opacity
over text and lowers it over a flat light background:

> "The element is aware of what's behind it and **increases the opacity of its shadow when it is over
> text. Conversely, it lowers the opacity of its shadow when it is over a solid light background.**
> This provides separation from the content to make sure elements are always easy to spot."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**What "vibrancy" is.** Apple's word for the legibility-preserving foreground treatment is
**vibrancy** — and it is explicitly *not* opacity/transparency. It is a system blend that pulls
color/light from the backdrop so foreground content stays legible on any material:

> "**Help ensure legibility by using vibrant colors on top of materials.** When you use system-defined
> vibrant colors, you don't need to worry about colors seeming too dark, bright, saturated, or low
> contrast in different contexts. Regardless of the material you choose, use vibrant colors on top of
> it."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

> "To ensure foreground content remains legible when it displays on top of a material, visionOS
> applies **vibrancy** to text, symbols, and fills. **Vibrancy enhances the sense of depth by pulling
> light and color forward** from both virtual and physical surroundings."
> — `[HIG]` Materials (visionOS), https://developer.apple.com/design/human-interface-guidelines/materials

Vibrancy is also **graded**, not binary — iOS exposes several discrete vibrancy levels (the
"midpoint" question, below):

> "iOS and iPadOS also define vibrant colors for labels, fills, and separators that are specifically
> designed to work with each material. **Labels and fills both have several levels of vibrancy** …
> The name of a level indicates the relative amount of contrast between an element and the background:
> **The default level has the highest contrast, whereas quaternary (when it exists) has the lowest
> contrast.** … label (default) / secondaryLabel / tertiaryLabel / quaternaryLabel"
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

**How tinting (colored symbols/labels/buttons) maps to backdrop brightness — the duotone/tone-map.**
When you *do* color a symbol/label/button, Apple does not paint a flat color; it generates a *range
of tones mapped to content brightness*, exactly like real colored glass:

> "**Selecting a color generates a range of tones that are mapped to content brightness underneath the
> tinted element.** It draws inspiration from how colored glass works in reality: **changing its hue,
> brightness and saturation depending on what's behind without deviating too much from the intended
> color.** Not only does this emphasize the physicality of the material, but it also helps legibility
> and contrast."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Is there a midpoint (neither pure black nor white)?** Yes — for *monochrome* labels the resting
state is the element's light/dark tone (so a "light" symbol is effectively white, a "dark" symbol
effectively black), but the **vibrancy levels** (secondary/tertiary/quaternary) deliberately sit at
reduced contrast (grays/partial), and **tinted** content is a *continuous tone range* keyed to
backdrop brightness — not pure black/white. So: the *flip* is binary; the *vibrancy ladder* and the
*tint tone-map* are graded.

**Net answer:** Symbol/label color = a **discrete light/dark flip** (on small elements; large
elements don't flip) **layered on top of a continuous glass adaptation** (blur + luminosity +
tint-amount + dynamic-range + shadow-opacity). The driver is the **backdrop's brightness/content**,
read continuously. "Vibrancy" is the blend that pulls backdrop color/light into the foreground;
intentional tint is a backdrop-brightness tone map, not a flat fill.

---

## 2. VIBRANCY on the web — closest CSS replication for legible labels on translucent material

There is **no native CSS "vibrancy"**. Apple's vibrancy = "foreground color whose luminosity is
driven by the foreground but whose hue/brightness is pulled from the backdrop." The closest faithful
primitives, in priority order:

### 2a. `mix-blend-mode: luminosity` / `plus-lighter` — the true vibrancy analog
`luminosity` keeps the foreground's *lightness* but takes *hue+saturation from the backdrop* — that
is the literal definition of Apple "colored-glass" vibrancy (label inherits the scene's color cast).
For the bright "frost"/specular layer, `plus-lighter` (additive, clamped) matches the way Apple's
highlight adds light without darkening.

> "The luminosity blend mode creates a color with the luminosity of the content and the hue and
> saturation of the background." … "useful for fast duotone effects, combining the luminosity from the
> source with the hue and saturation of the backdrop."
> — `[WEB‡]` MDN, mix-blend-mode, https://developer.mozilla.org/en-US/docs/Web/CSS/mix-blend-mode

```css
/* Vibrant label that takes its color cast from the glass/backdrop, like Apple vibrancy */
.glass .label {
  color: #fff;                 /* base luminance of the label */
  mix-blend-mode: luminosity;  /* keep label lightness, pull hue/sat from backdrop */
  isolation: isolate;          /* keep the blend scoped to the glass stack only */
}
/* The frosty inner specular sheen: additive, never darkens */
.glass .sheen { mix-blend-mode: plus-lighter; }
```

**Tradeoff:** `luminosity` blends against whatever is *behind in the same stacking context*, so you
must wrap the glass + its label in `isolation: isolate` or the blend leaks to the page. A pure
`luminosity` white label can wash out over a *light* backdrop (lightness preserved, but no
backstop) — so it is **not sufficient alone**; pair it with 2b for the light↔dark decision.

### 2b. Adaptive black/white driver — the discrete "flip" (`contrast-color()` or measured JS)
This reproduces Apple's light↔dark flip. Native CSS now has `contrast-color()` (Safari 26+), which
returns black **or** white for best contrast with a given color — exactly Apple's binary flip, but it
only takes a *declared* color, not a sampled backdrop:

> "the browser will set color to either black or white, whichever choice provides better contrast" …
> "The current implementation in Safari Technology Preview is using the contrast algorithm officially
> defined in WCAG 2." … "Using the contrast-color() function does not guarantee that the resulting
> pair of colors will be accessible."
> — `[WEB‡]` WebKit blog, contrast-color(), https://webkit.org/blog/16929/contrast-color/

```css
/* Works when you KNOW the local backdrop color (e.g. a tint behind the bar). Safari 26+. */
.tab-bar { background: var(--bar-tint); color: contrast-color(var(--bar-tint)); }
```

For an **arbitrary image/video backdrop** (the hard case Apple actually solves in the compositor),
`contrast-color()` can't see it. Sample the backdrop luminance in JS and toggle a class — the
faithful web equivalent of Apple's "read the backdrop, flip the element":

```js
// sRGB → relative luminance (WCAG); flip threshold ≈ 0.36 (perceptual midpoint, matches APCA-ish)
function relLuma(r, g, b) {                       // r,g,b in 0..1
  const lin = c => c <= 0.03928 ? c/12.92 : ((c+0.055)/1.055)**2.4;
  return 0.2126*lin(r) + 0.7152*lin(g) + 0.0722*lin(b);
}
// Sample the region of the backdrop *under* the bar (drawImage a slice to a 1x1/NxN canvas, read px),
// average it, then:
bar.classList.toggle('on-light', relLuma(r,g,b) > 0.36); // -> dark symbols
bar.classList.toggle('on-dark',  relLuma(r,g,b) <= 0.36); // -> light symbols
```
```css
.bar.on-light { --sym: #000; }   /* underlying content is light -> darker symbols  */
.bar.on-dark  { --sym: #fff; }   /* underlying content is dark  -> lighter symbols */
.bar .symbol  { color: var(--sym); }
```
(`Y > 0.36` is the commonly-cited flip point; it aligns better with perception than 0.5. Source:
`[WEB‡]` search synthesis re: luminance Y / APCA, and `[WEB‡]` Lea Verou / CSS-Tricks
"Approximating contrast-color()", https://css-tricks.com/approximating-contrast-color-with-other-css-features/.)

### 2c. What the best web "liquid glass" builds actually do for legibility
Honest answer from the field: **they mostly don't fully solve it** — the optics are easy, vibrancy is
hard, and most ship a contrast concession:

> "the liquid glass look has been rightfully criticized for text contrast accessibility" … designers
> make "concessions to ensure text accessibility by way of readability."
> — `[WEB‡]` Frontend Masters, Liquid Glass on the Web, https://frontendmasters.com/blog/liquid-glass-on-the-web/

The pragmatic recipe the better builds converge on: **(i)** put labels on an **isolated** layer
(`isolation: isolate`) so refraction never distorts the *text* (only the backdrop is displaced);
**(ii)** apply a **local dimming/scrim** behind the text region (Apple's own Clear-variant rule,
§3); **(iii)** use a `text-shadow`/duotone backstop; **(iv)** flip via 2b. `mix-blend-mode:
difference` is sometimes used as a cheap "always visible" hack but it inverts color and looks unlike
Apple — prefer luminosity + flip.

> "place text on an isolated layer using the `isolation: isolate` property, pair with highly
> contrasting semi-transparent background color, and disable distortion animations using
> prefers-reduced-motion."
> — `[WEB‡]` web-replication synthesis (grafit.agency / naughtyduk liquidGL),
>   https://www.grafit.agency/blog/why-you-shouldnt-use-the-liquid-glass-effect-on-your-website-yet ·
>   https://github.com/naughtyduk/liquidGL

**Recommended web vibrancy stack (parity-max):** `luminosity` blend on the label (color cast) **+**
sampled-luminance flip (the light/dark decision) **+** a thin local scrim/`text-shadow` backstop
(the legibility floor) **+** `isolation: isolate` (scope). That is the closest faithful decomposition
of Apple's single compositor effect.

---

## 3. CLEAR vs REGULAR — exact rules + the dimming spec (35%, localized, AVKit)

**Default to Regular; Clear is the exception.** Regular adapts and is legible anywhere and lets you
put content on top; Clear is permanently transparent, has **no adaptive behavior**, and needs a
dimming layer:

> "There are two to choose from: Regular and Clear. **They should never be mixed** … **Regular is the
> most versatile and the one you will be using the most.** This variant gives you all the visual and
> adaptive effects … and provides legibility regardless of context. **It works in any size, over any
> content and anything can be placed on top of it.** Clear, on the other hand, **does not have
> adaptive behaviors. It is permanently more transparent** … To provide enough legibility for symbols
> or labels, **it needs a dimming layer to darken the underlying content. Without it, legibility gets
> noticeably worse.** … whereas the Regular variant can work anywhere, **Clear should only be used
> when these 3 conditions are met. First, the element you're applying it to is over media-rich
> content. Second, your content layer won't be negatively affected by introducing a dimming layer.
> And lastly, the content sitting above it is bold and bright.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**The exact dimming number + the AVKit exception:**

> "For optimal contrast and legibility, determine whether to add a dimming layer behind components
> with clear Liquid Glass: **If the underlying content is bright, consider adding a dark dimming layer
> of 35% opacity.** … **If the underlying content is sufficiently dark, or if you use standard media
> playback controls from AVKit that provide their own dimming layer, you don't need to apply a dimming
> layer.**"
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

**Localized dimming for small footprints:**

> "If Liquid Glass elements in your app have a smaller footprint, you can use **localized dimming** and
> allow the content to retain more of its original vibrancy."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Does Apple EVER darken the glass to keep light symbols, or always keep glass clear + adapt the
symbol?** For **Regular**, it keeps the glass clear and **adapts the symbol** (flips it; raises shadow
opacity; shifts tint/dynamic-range) — it does *not* slap a dark plate behind a light symbol. The
**only** sanctioned *darkening* is: (a) the **Clear** variant's **35% dimming layer** (a content
dimmer, not a tint of the glass), and (b) a *scroll-edge* "subtle dimming" the glass switches to when
**dark** content scrolls under, to preserve contrast as it goes dark:

> "When darker content scrolls under, triggering the glass itself to transition to its dark style, the
> effect **intelligently switches to apply a subtle dimming instead, again ensuring contrast and
> legibility.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Sheets are a related case:** a half-sheet gets **more opaque** at full height to protect focus/
legibility — opacity, not a symbol flip:

> "When a half sheet expands to full height, it transitions to a more opaque appearance to help
> maintain focus on the task."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

**Web mapping:** Regular → `backdrop-filter: blur() saturate() brightness()` + adaptive symbol flip
(§2). Clear → minimal/zero blur + a **`rgba(0,0,0,0.35)` dimming layer** *only when the backdrop is
bright* (mirror the 35% rule literally); skip the dimmer when backdrop is dark or it's a video with
its own controls scrim.

---

## 4. The OPTICS that read as glass over any backdrop — lensing, specular, adaptive colorless tint

**Lensing (refraction) is the defining optic** — light bends at the edges; the silhouette is read
from the warp, not a border:

> "The primary way Liquid Glass visually defines itself is through something called **Lensing.** …
> the warping and bending of light of a transparent object communicates to us its presence, its
> motion, and form. … Where as previous materials scattered light, **this new set of materials
> dynamically bends, shapes, and concentrates light in real time.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Moving specular highlight** tracks geometry and travels on interaction/lock-unlock; thicker glass =
deeper shadow + more lensing:

> "the **highlights layer.** … **Light sources inside of this environment shine on the material
> producing highlights that respond to geometry** … On interactions … **these lights move in space,
> causing light to travel around the material, defining its silhouette.**" … "It casts **deeper,
> richer shadows, has more pronounced lensing and refraction effects, and a softer scattering of
> light.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Adaptive colorless tint — glass has no color; it takes color from content:**

> "By default, Liquid Glass has **no inherent color, and instead takes on colors from the content
> directly behind it.**"
> — `[HIG]` Color, https://developer.apple.com/design/human-interface-guidelines/color

> "Liquid Glass is a material that **blurs content behind it, reflects color and light of surrounding
> content, and reacts to touch and pointer interactions in real time.**"
> — `[DOC]` Applying Liquid Glass to custom views, https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views

**Concrete web parameters (from the best non-authoritative replications):**
- **Refraction:** SVG `feImage` (a pre-computed displacement map from an SDF/height field; squircle
  height `y = ⁴√(1−(1−x)⁴)` is the Apple-favored curve) → `feDisplacementMap in="SourceGraphic"
  in2="displacement_map" scale=<maxDisplacePx> xChannelSelector="R" yChannelSelector="G"`, applied via
  `backdrop-filter: url(#filter)`. Map encodes displacement as `r = 128 + x*127`, `g = 128 + y*127`.
  **Chromium-only** (SVG-in-`backdrop-filter` is non-standard; Safari/Firefox can't do it on the
  *backdrop* — fall back to plain blur). Source: `[WEB‡]` kube.io, https://kube.io/blog/liquid-glass-css-svg/
  (**cataloged verbatim**: `sources/lg_text_kube_liquid_glass_css_svg.md`).
- **Blur/tint:** `backdrop-filter: blur(8–20px) saturate(160–180%) brightness(1.05)` for Regular
  (numbers are field practice, not Apple-published).
- **Specular rim:** a separate `feImage` rim-light blended with `feBlend`, or in pure CSS an inset
  highlight: `box-shadow: inset 0 1px 0 rgba(255,255,255,.6), inset 0 -1px 1px rgba(255,255,255,.25)`
  + a gradient `border-image`; animate a moving highlight only when motion is allowed.
- **Materialize, don't fade:** Apple modulates lensing in/out rather than opacity — on the web,
  animate the `feDisplacementMap` `scale` (the one prop cheap to animate) instead of `opacity`.
> "Instead of fading, Liquid Glass objects **materialize in and out by gradually modulating the light
> bending and lensing.**" — `[WWDC]` 219.

---

## 5. ACCESSIBILITY interplay — Reduce Transparency / Increase Contrast / Reduce Motion

These are **modifiers on the material** and they override the optics; legibility is never load-bearing
on the glass effect:

> "**Reduced Transparency, makes Liquid Glass frostier and obscures more of the content behind it.
> Increased contrast, makes elements predominantly black or white and highlights them with a
> contrasting border and Reduced Motion decreases the intensity of some effects and disables any
> elastic properties for the material.** These are available automatically whenever you use the new
> material."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "people can … turn on accessibility settings that **reduce transparency or motion** in the
> interface. **These settings can remove or modify certain effects.** If you use standard components
> from system frameworks, this experience adapts automatically. **Ensure you test your app's custom
> elements, colors, and animations** with different configurations of these settings."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "With the Increase Contrast setting turned on, the color differences become far more apparent. …
> If your app doesn't provide this minimum contrast by default, ensure it at least provides a higher
> contrast color scheme when the system setting **Increase Contrast** is turned on."
> — `[HIG]` Color / Accessibility, https://developer.apple.com/design/human-interface-guidelines/color ·
>   https://developer.apple.com/design/human-interface-guidelines/accessibility

**Effect on symbol adaptation specifically:** under **Increase Contrast** the adaptive monochrome
flip is *superseded* — symbols/elements go **predominantly black or white with a contrasting
border** (a stronger, guaranteed-contrast state, not the subtle vibrancy flip). Under **Reduce
Transparency** the glass frosts toward opaque so the backdrop stops driving the symbol at all. Under
**Reduce Motion** the moving specular/elastic morph is disabled (symbol color unaffected).

**Web mapping (must-honor):**
```css
@media (prefers-reduced-transparency: reduce) {
  .glass { backdrop-filter: none; background: var(--solid-bg); }   /* frost -> opaque */
}
@media (prefers-contrast: more) {
  .glass { backdrop-filter: none; background: Canvas; color: CanvasText;
           border: 2px solid CanvasText; }                          /* B/W + border */
  .glass .symbol { color: CanvasText; }                             /* drop the adaptive flip */
}
@media (prefers-reduced-motion: reduce) {
  .glass .sheen, .glass { animation: none !important; transition: none !important; }
}
```

---

## HOW TO IMPLEMENT ON THE WEB FOR TRUE PARITY (drop-in)

Decompose Apple's single compositor effect into **four stacked layers** in one isolated container:
(1) refracted+blurred backdrop, (2) colorless adaptive tint, (3) vibrant adaptive label, (4) rim
specular. Then layer the accessibility overrides on top.

### HTML
```html
<div class="lg" data-variant="regular">
  <div class="lg__backdrop"></div>   <!-- refraction + blur + saturate (the optics)        -->
  <div class="lg__tint"></div>       <!-- colorless tint that "takes color from content"    -->
  <div class="lg__sheen"></div>      <!-- moving specular rim (plus-lighter)                -->
  <div class="lg__content">          <!-- labels/symbols: vibrant + adaptive flip           -->
    <span class="lg__label">Continue</span>
  </div>
</div>
```

### CSS
```css
.lg{
  position:relative; border-radius:22px; overflow:clip;
  isolation:isolate;                         /* scope every blend to this stack only        */
  --sym:#fff;                                /* adaptive symbol color, set by the JS flip    */
}
/* (1) OPTICS — Regular variant: blur + saturate + (Chromium) SVG refraction */
.lg__backdrop{
  position:absolute; inset:0;
  backdrop-filter: blur(14px) saturate(175%) brightness(1.06);
  -webkit-backdrop-filter: blur(14px) saturate(175%) brightness(1.06);
}
@supports (backdrop-filter:url(#x)){          /* Chromium: add real lensing/refraction       */
  .lg__backdrop{ backdrop-filter: url(#lgRefract) blur(14px) saturate(175%); }
}
/* (3 on Clear) dimming layer — ONLY for Clear over BRIGHT media, Apple's literal 35% rule    */
.lg[data-variant="clear"][data-backdrop="bright"] .lg__backdrop{
  background: rgba(0,0,0,.35);                /* skip when backdrop dark or AVKit-style video */
}
/* (2) colorless adaptive tint: glass has no color, pulls hue/sat from content                */
.lg__tint{ position:absolute; inset:0; mix-blend-mode:overlay; background:rgba(255,255,255,.10); }
/* (4) moving specular rim — additive light, never darkens; off under reduced-motion           */
.lg__sheen{
  position:absolute; inset:0; mix-blend-mode:plus-lighter; pointer-events:none;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.65), inset 0 -1px 1px rgba(255,255,255,.25);
  background: linear-gradient(105deg, transparent 40%, rgba(255,255,255,.35) 50%, transparent 60%);
  background-size:250% 250%; animation:lg-sweep 6s linear infinite;
}
@keyframes lg-sweep{ from{background-position:0% 0%} to{background-position:100% 100%} }
/* VIBRANCY: label takes color cast from backdrop (luminosity) + adaptive light/dark flip      */
.lg__label{
  color: var(--sym);
  mix-blend-mode: luminosity;                /* keep label lightness, pull hue/sat from below  */
  text-shadow: 0 0 1px rgba(0,0,0,.25);      /* thin legibility backstop (the floor)           */
  font: 600 17px/1.2 -apple-system, "SF Pro Text", system-ui, sans-serif;
}
.lg.on-light{ --sym:#000; }                  /* light content -> darker symbols (Apple's rule) */
.lg.on-dark { --sym:#fff; }                  /* dark content  -> lighter symbols               */

/* contrast-color() shortcut when the local backdrop color IS known (Safari 26+) — no sampling */
@supports (color: contrast-color(red)){
  .lg[style*="--bar-tint"] .lg__label{ color: contrast-color(var(--bar-tint)); mix-blend-mode:normal; }
}

/* ACCESSIBILITY OVERRIDES (these win) */
@media (prefers-reduced-transparency: reduce){
  .lg__backdrop{ backdrop-filter:none; -webkit-backdrop-filter:none; background:rgba(20,20,22,.92); }
}
@media (prefers-contrast: more){
  .lg__backdrop{ backdrop-filter:none; background:Canvas; }
  .lg{ border:2px solid CanvasText; }
  .lg__label{ color:CanvasText; mix-blend-mode:normal; text-shadow:none; }   /* drop the flip */
}
@media (prefers-reduced-motion: reduce){ .lg__sheen{ animation:none; } }
```

### SVG refraction filter (Chromium) — the lensing
```html
<svg width="0" height="0" style="position:absolute" color-interpolation-filters="sRGB">
  <filter id="lgRefract" x="0" y="0" width="100%" height="100%">
    <!-- displacement map: precompute from a squircle height field y = (1-(1-x)^4)^(1/4),
         encode r = 128 + dx*127, g = 128 + dy*127; load it as feImage -->
    <feImage href="data:image/png;base64,…displacementMap…" result="disp"/>
    <feDisplacementMap in="SourceGraphic" in2="disp"
        scale="18" xChannelSelector="R" yChannelSelector="G"/>
  </filter>
</svg>
```

### JS — the adaptive flip (continuous backdrop read = Apple's driver)
```js
function relLuma(r,g,b){ const l=c=>{c/=255;return c<=.03928?c/12.92:((c+.055)/1.055)**2.4};
  return .2126*l(r)+.7152*l(g)+.0722*l(b); }
function reflow(el, sampler){                 // sampler() -> {r,g,b} avg under the element
  const {r,g,b}=sampler(); const light = relLuma(r,g,b) > 0.36;   // 0.36 ≈ perceptual midpoint
  el.classList.toggle('on-light', light);
  el.classList.toggle('on-dark', !light);
}
// call reflow() on scroll/resize/backdrop-change (rAF-throttled) to mirror Apple's continuous adapt
```

**Parity notes / honest gaps vs. Apple:**
- Apple's flip + vibrancy + dimming happen in the GPU compositor with true backdrop sampling and
  per-pixel tone mapping; the web has no per-pixel backdrop read in CSS, so the adaptive flip must be
  JS-sampled (canvas `drawImage` slice of the backdrop under the bar → average → flip). That is the
  single biggest fidelity gap and the right place to spend effort.
- `mix-blend-mode: luminosity` is the closest single-property analog to vibrancy; combine it with the
  flip + a thin scrim/`text-shadow` for the legibility floor.
- SVG-driven refraction in `backdrop-filter` is **Chromium-only**; everywhere else degrade to
  `blur()+saturate()` (still reads as glass; just no lensing).
- Honor `prefers-reduced-transparency` / `prefers-contrast` / `prefers-reduced-motion` — under
  Increase Contrast specifically, **abandon the subtle flip** for predominantly black/white +
  contrasting border (Apple's documented behavior), which is also the WCAG-safe state.

---

## Source index (this doc)

| # | Source | URL |
|---|---|---|
| Apple | `[HIG]` Color | https://developer.apple.com/design/human-interface-guidelines/color |
| Apple | `[HIG]` Materials | https://developer.apple.com/design/human-interface-guidelines/materials |
| Apple | `[HIG]` Accessibility | https://developer.apple.com/design/human-interface-guidelines/accessibility |
| Apple | `[DOC]` Adopting Liquid Glass | https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass |
| Apple | `[DOC]` Applying Liquid Glass to custom views | https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views |
| Apple | `[WWDC]` 219 — Meet Liquid Glass | https://developer.apple.com/videos/play/wwdc2025/219/ |
| Apple | `[WWDC]` 356 — Get to know the new design system | https://developer.apple.com/videos/play/wwdc2025/356/ |
| Web‡ | MDN — mix-blend-mode | https://developer.mozilla.org/en-US/docs/Web/CSS/mix-blend-mode |
| Web‡ | WebKit blog — contrast-color() | https://webkit.org/blog/16929/contrast-color/ |
| Web‡ | CSS-Tricks — Approximating contrast-color() | https://css-tricks.com/approximating-contrast-color-with-other-css-features/ |
| Web‡ | kube.io — Liquid Glass refraction with CSS+SVG (cataloged: `sources/lg_text_kube_liquid_glass_css_svg.md`) | https://kube.io/blog/liquid-glass-css-svg/ |
| Web‡ | Frontend Masters — Liquid Glass on the Web | https://frontendmasters.com/blog/liquid-glass-on-the-web/ |
| Web‡ | grafit.agency — Liquid Glass web reality check | https://www.grafit.agency/blog/why-you-shouldnt-use-the-liquid-glass-effect-on-your-website-yet |
| Web‡ | naughtyduk/liquidGL | https://github.com/naughtyduk/liquidGL |

**Proxy-blocked sources:** none encountered. All Apple JSON/transcript content was read from the
local extracts in this folder (`lg_text_lg_data_*.md`, `lg_wwdc_219_transcript.md`,
`lg_wwdc_356_transcript.md`), which were captured from Apple's own canonical JSON/transcript
endpoints. Web-replication sources fetched live; none returned 403/405/407.
