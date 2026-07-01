# AppkitElements kit — Apple-HIG atomic primitives

> Vendored from Orwell's `OrwellElement` kit into Applicant as `appkitElements.js` /
> `window.AppkitElements`; the `.ow-*` class API was carried over verbatim.

ONE source of truth for the atomic UI controls. Every front-door surface — the chat,
settings, gadgets, decision cards, **and the separate `login.html` + admin pages** — composes
these classes instead of re-inventing control chrome. The kit lives in the ELEMENT KIT block of
`workspace/static/style.css` (the class-API comment block at the top of that region is the
authoritative inline spec; this file mirrors it) and is instantiated by
`workspace/static/js/appkitElements.js`.

> Migration of existing surfaces onto the kit is a **separate** task (#775). #773 only
> **creates** the kit + a demo. Do not migrate surfaces here.

## Design contract (every primitive)

- **Theme-agnostic, glass-default.** Controls ride the one glass plane — they do not stack a
  second glass slab. HIG Materials: *"Like in Safari today, controls sit on top of a system
  material, not directly on content."* HIG (glass-on-glass): *"use fills, transparency, and
  vibrancy for the top elements to make them feel like a thin overlay that is part of the
  material."* (`LIQUID_GLASS_REFERENCE.md` §1–§2.)
- **Dark-ink legible on glass.** Labels/values use the control ink (`--ow-control-ink`,
  resolves to `--fg`), the same dark-on-glass legibility floor the chrome uses.
- **NO accent HUE on text.** HIG Color: *"To emphasize primary actions, apply color to the
  background rather than to symbols or text."* The only colored pixels are **state fills** (a
  checked box, an ON switch, a slider track) using Apple's **system** blue/green, plus the
  **Destructive** role's **system red** fill (a semantic system color, not the theme accent),
  always with a legible on-color label. (`LIQUID_GLASS_REFERENCE.md` §6; HIG Buttons "Role".)
- **a11y-trio safe.** `prefers-reduced-transparency: reduce` → solid opaque fills (glass is
  never load-bearing for legibility); `prefers-contrast: more` → contrasting border;
  `prefers-reduced-motion: reduce` → no transform/elastic motion. (`LIQUID_GLASS_REFERENCE.md`
  §5; HIG Accessibility.)
- **Keyboard + focus.** Real `:focus-visible` ring in Apple **system blue** (`--ow-focus-ring`,
  `#0a84ff`) — a fixed accessibility color, deliberately distinct from the theme accent so it
  never reads as a hued label. ≈44px tap target (HIG Buttons: *"a hit region of at least
  44×44 pt"*). Apple capsule/concentric radii from the shared radius scale.

All primitives are scoped to `body.theme-frosted` (the glass build) so the non-glass Normal
tier is untouched — same convention as the rest of the kit.

## The glass technique (how the primitives are built)

The kit uses the **real in-browser Liquid Glass technique** — the same one the app already
implements — not a flat approximation. The technique sources:

- **kube.io — "Liquid Glass with CSS + SVG"** (https://kube.io/blog/liquid-glass-css-svg/,
  incl. its source): the SVG `feImage` displacement map → `feDisplacementMap in="SourceGraphic"
  in2="displacement_map" scale=<px> xChannelSelector="R" yChannelSelector="G"` applied via
  `backdrop-filter: url(#…)`; the `feImage` + `feBlend` **specular rim-light that responds to
  geometry**; the displacement encoding `r = 128 + x·127, g = 128 + y·127`; the **squircle**
  height curve `y = ⁴√(1−(1−x)⁴)`; and the **switch "lip-bezel"** (convex outer rim + concave
  center → *"the center slider zoomed out, while the edges refract the inside"*).
- **Frontend Masters — "Liquid Glass on the Web"** (https://frontendmasters.com/blog/liquid-glass-on-the-web/).
- `ADAPTIVE_LEGIBILITY_REFERENCE.md` §Refraction (L337–351) + §Accessibility (L355–379); the
  app's derivation note in `README.md` L48.

**The kit composes the existing app mechanisms — it does not reinvent or flatten them:**

- **The control rides the ONE glass plane.** The parent surface (the window / card / bar) is
  the refracted glass — `appkitGlass.js` applies the `feDisplacementMap` refraction + specular
  rim there, capped to ~20 desktop / 8 mobile **chrome** surfaces, never the content layer or
  every tiny control (HIG: *"Don't use Liquid Glass in the content layer"*; *"Use Liquid Glass
  effects sparingly"*). A kit control therefore uses **fills / transparency / vibrancy** to read
  as *"a thin overlay that is part of the material"* (HIG no-glass-on-glass): a neutral
  translucent veil (`--ow-control-fill`) + the kit's `--ow-btn-glass` backdrop blur + a **soft
  luminous rim** (`box-shadow: inset 0 1px 0 var(--ow-glass-rim)` — the pure-CSS equivalent of
  the kube.io `feBlend` specular rim, per `ADAPTIVE_LEGIBILITY` L345–347).
- **Adaptive, legible dark ink.** Controls use the canonical neutral chrome dark ink `#16191f`
  (the same value the adaptive layer in `appkitGlass.js` picks as `HERO_INK_DARK` and pinned on
  `.ow-btn`) — never the theme's light `--fg` (which on a naked glass surface is light-on-light).
  On large surfaces `appkitGlass.js` keeps the parent legible via its APCA contrast veil; the
  control inherits that legible context.
- **The transient knobs take the REAL SVG refraction.** The switch thumb and slider thumb are
  the sanctioned **content-layer transient glass** (HIG: *"the knob transforms into Liquid Glass
  during interaction"*). At **Full Glass** (`body.glass-full`, the Chromium SVG-refraction tier)
  they take the app's `#owlg-thumb` concave **lip-bezel** filter — generated **once** in
  `appkitGlass.js` (the kube.io `#switch` port) — exactly like the existing bespoke toggles.
  Plain **Frosted** and every non-Chromium / reduced-transparency fallback keep the clean white
  knob (the refraction is pure progressive enhancement, never load-bearing).
- **a11y trio overrides the optics.** Reduce Transparency → solid opaque fills + the knob drops
  to solid white; Increase Contrast → contrasting border; Reduce Motion → no transform/elastic
  — legibility is never load-bearing on the glass (`ADAPTIVE_LEGIBILITY` §Accessibility).

## Tokens added by the kit

| Token | Meaning |
|---|---|
| `--ow-focus-ring` / `--ow-focus-ring-w` | system-blue keyboard focus ring + width (3px) |
| `--ow-control-fill` / `--ow-control-fill-hover` | neutral translucent control fill (idle / hover) |
| `--ow-control-rim` | the control's hairline rim |
| `--ow-control-ink` | the control's legible ink (→ `--fg`, never accent) |
| `--ow-danger` / `--ow-on-danger` | system red + its legible on-red label (Destructive role) |

Reused from the existing design system: `--ow-tap-min`, `--ow-ui-font`, `--ow-fw-*`,
`--ow-fs-*`, `--ow-space-*`, `--ow-radius-*`, `--ow-btn-glass`, `--ow-ios-blue`,
`--ow-ios-green`, `--ow-glass-rim-border`, `--select-option-*`.

## Classes, variants & states

### Button — `.ow-btn` + one variant

`.ow-btn` is the kit button base (already present; rounded out here additively — `.ow-btn`
COLORS are owned/tuned by #726, this kit only adds variants + states without touching them).

| Variant | Role (WWDC25 310 prominence) | Look |
|---|---|---|
| `.ow-btn-prominent` | primary / default action | luminous tinted glass — default tint **neutral** (emphasis = luminosity + weight, owner ruling; glass is colorless), `--ow-btn-tint-primary` opt-in **accent** wash for 310's accent-tinted primary |
| `.ow-btn-secondary` | secondary / standard action | subdued neutral glass tint + rim |
| `.ow-btn-plain` | none / low-emphasis | borderless / text-only |
| `.ow-btn-destructive` | Destructive, secondary prominence | **system-red TINT over glass + legible on-red label** (`.ow-btn-destructive-solid` = opt-in loud opaque plate) |
| `.ow-btn-icon` | icon-only | circular glass disc |

Plus the **size ladder** (`.ow-btn-sm`/`-md`/`-lg`/`-xl`), the **concentric** modifier
(`.ow-btn-concentric`), and the **grouped-glass** wrapper (`.ow-btn-group`) — see the
WWDC25 310/356 sections below.

States (all variants): `:hover` (lift), `:active` (iOS dim + slight scale-down `.97`),
`:focus-visible` (system-blue ring), `:disabled` / `[disabled]` / `.is-disabled` (inert,
0.42 opacity, no pointer events). Reduced-motion drops the transform; reduced-transparency
solidifies the glass fills; increased-contrast strengthens the border.

```html
<button class="ow-btn ow-btn-prominent">Confirm</button>
<button class="ow-btn ow-btn-secondary">Cancel</button>
<button class="ow-btn ow-btn-plain">Skip</button>
<button class="ow-btn ow-btn-destructive">Delete</button>
<button class="ow-btn ow-btn-icon" aria-label="Close">✕</button>
```

#### Depth & material (WWDC25 310/356 parity)

A Liquid Glass button **floats**: it casts a soft, diffuse drop shadow (a real cast
shadow — `--ow-btn-shadow`, a tight near-black contact line + two broad low-alpha ambient
layers) and carries a **full-perimeter specular rim** (`--ow-btn-rim` — a bright lit glass
edge, brightest at the top, light source ≈ -60° per kube.io). The fill is a **translucent
glass veil** (`--ow-btn-veil`) + the kit material filter (`--ow-btn-glass-kit`: blur +
saturate, only a hair of brightness so the **backdrop samples through** — *tint, not fill*).
The rim + shadow, not opacity, give it form. Tuned against the authentic Apple refs
(`images/lg_hig_segmented_control_poster.png`, `lg_hig_ios_glass_over_light.png`,
`lg_hig_toolbar_grouping_correct.png`, `lg_color_160…tinted`).

**#709 — refraction + rim + shadow read coherently.** At Full Glass `appkitGlass.js` lays
the kube.io `feDisplacementMap` refraction onto the glass buttons via
`backdrop-filter: url(#…)`. That displacement is a **soft wide halo at the pill edge** that
can *fight* the rim, so the CSS depth was retuned to win the cascade: a **CRISP 0.5px lit
top hairline** (re-asserts the glass outline the refraction blurs), a **more present
contact-shadow** (a faint shadow vanished over a vivid/colourful wallpaper), and a
**luminous-but-translucent fill with a top-down luminosity gradient** so the refracted
wallpaper still reads through while the dark label clears contrast over light/colourful
backdrops. `.ow-btn-secondary`/`-icon` ride a **light luminous veil** (not the old dark
wash) — Apple's "secondary" lowers visual *weight*, it doesn't darken the material, and a
dark wash made the dark ink illegible over a colourful/dark backdrop.

#### Size ladder — shape follows size (WWDC25 310)

WWDC25 310 establishes a **five-size hierarchy** and ties **shape to size**. The size
modifiers size via **padding + line-height** + a stepped **min-height floor** + an explicit
**font ladder** (#709 — the prior build collapsed: the base `min-height:44px` dominated and
the shared `--ow-fs-*` tokens are all ~14px, so every size rendered ~44px with near-identical
type). 310 forbids a hard `height`, but a stepped `min-height` floor (the control's tap
metric) is exactly how AppKit's control sizes work: **sm/md hold the ≥44px tap floor**
(WCAG 2.5.5; 310: mini/sm/md are "slightly taller" anyway) with the **type** stepped for
density (13/14px), and **lg (52px/16px) / xl (62px/18px)** step UP for the spacious capsule
read. The result is a real, visible hierarchy.

| Modifier | Size | Shape |
|---|---|---|
| `.ow-btn-sm` | small | rounded-rect (`--ow-radius-inner`) — high-density |
| `.ow-btn-md` | medium | rounded-rect (`--ow-radius-inner`) — high-density |
| `.ow-btn-lg` | large | **capsule** (`9999px`) |
| `.ow-btn-xl` | **extra-large** (new in Tahoe) | **capsule** — the single most-prominent action |

> **Reserve `-xl` for the one prime action** per context ("the actions that people launch
> your app to get done"). Don't make everything large.

```html
<button class="ow-btn ow-btn-secondary ow-btn-sm">Small</button>
<button class="ow-btn ow-btn-secondary ow-btn-md">Medium</button>
<button class="ow-btn ow-btn-prominent ow-btn-lg">Large</button>
<button class="ow-btn ow-btn-prominent ow-btn-xl">Start the season</button>
```

#### Tint prominence — "tint, don't fill" (WWDC25 310)

310's key button correction: a prominent button **tints the translucent glass** (color on
the **background**, never the label), it is **never an opaque solid plate** (a solid fill
"breaks the visual character of Liquid Glass", 219). 310 names four `tintProminence`
levels, which our variants map onto:

| Our variant | Apple `tintProminence` | Look |
|---|---|---|
| `.ow-btn-prominent` | **primary** | the single default action — luminous tinted glass (default tint = neutral; override `--ow-btn-tint-primary` to an accent wash for 310's accent-tinted primary) |
| `.ow-btn-secondary` | **secondary** | a subdued neutral wash — supporting, doesn't upstage primary |
| `.ow-btn-plain` | **none** | no tint (borderless) |
| `.ow-btn-destructive` | **secondary**, system **red** | a red TINT over glass (`--ow-btn-tint-danger`) — danger signal that "doesn't overpower nearby controls" |

> **One primary per context.** Exactly one `.ow-btn-prominent` (the default action) per
> view — everything else `secondary`/`plain`. The orthogonal `.ow-btn-prominence-{none,
> secondary,primary}` helpers let a consumer set prominence independently of a variant.
> `.ow-btn-destructive-solid` is the **opt-in** loud opaque-red plate, reserved (like `-xl`)
> for a single final, irreversible confirm. The tint is always a **background** tint — the
> label keeps the dark chrome ink, **no accent hue on text** (HIG Color).

```html
<!-- accent-tinted primary (310 accent look): tint the BACKGROUND, not the label -->
<button class="ow-btn ow-btn-prominent ow-btn-lg"
        style="--ow-btn-tint-primary: color-mix(in srgb, #0a84ff 30%, transparent)">Play</button>
```

#### Concentric nesting (WWDC25 356)

356's three shape types: **fixed** (constant radius), **capsule** (radius = ½ height), and
**concentric** (radius = **parent radius − padding**). `.ow-btn-concentric` computes the
inner radius from `--ow-parent-radius` and `--ow-parent-inset`, and — per 356's trick for a
control that must work **both nested and standalone** — falls back to a standalone radius
when neither is set ("the concentric value adapts when nested, the fallback kicks in when
the component stands alone"). Works for buttons, and the same override applies to pop-up /
segmented controls.

```html
<div style="padding:10px; border-radius:24px /* parent */">
  <button class="ow-btn ow-btn-prominent ow-btn-concentric"
          style="--ow-parent-radius:24px; --ow-parent-inset:10px">Nested</button>
</div>
<!-- standalone: the fallback radius stands -->
<button class="ow-btn ow-btn-secondary ow-btn-concentric">Standalone</button>
```

#### Grouped glass — one shared backdrop sample (WWDC25 310)

310: adjacent glass elements must **share ONE backdrop sample** — "glass can't directly
sample other glass", and one sampling pass is faster (`NSGlassEffectContainerView`). The
`.ow-btn-group` wrapper is the web analogue: the **group** carries the backdrop-filter (the
one shared sample) and the outer capsule; its member `.ow-btn`s **drop their own sample**
and ride the group's, melding into one seamless capsule (segmented look). At Full Glass the
group is the surface `appkitGlass.js` refracts — one shared sample region per group.

```html
<span class="ow-btn-group">
  <button class="ow-btn ow-btn-secondary" aria-label="Back">‹</button>
  <button class="ow-btn ow-btn-secondary" aria-label="Forward">›</button>
</span>
```

### Field — `.ow-field`

Canonical glass-appropriate text input / textarea. `:focus` system-blue ring;
`[aria-invalid="true"]` / `.is-invalid` red ring; legible placeholder (muted neutral, never
invisible); `:disabled`. Use `textarea.ow-field` for multi-line (vertical resize).

```html
<input class="ow-field" placeholder="Type a message…">
<textarea class="ow-field" placeholder="Notes…"></textarea>
```

### Checkbox / Radio — `.ow-check` / `.ow-radio`

Apple-style: neutral box/ring at rest; the **accent (system-blue) fill + white glyph appears
only when `:checked`**. `:focus-visible` ring; `:disabled`.

```html
<input type="checkbox" class="ow-check" checked>
<input type="radio" class="ow-radio" name="g" checked>
```

### Switch — `.ow-switch` (iOS toggle)

ON track = system blue, OFF = neutral translucent track, glass knob that slides. CSS-only —
no JS needed (a `<label>` wrapping a native checkbox). `:focus-visible` ring on the input.

```html
<label class="ow-switch">
  <input type="checkbox" checked>
  <span class="ow-switch-track"></span>
</label>
```

### Select — `.ow-select`

Kit-styled `<select>`: glass capsule, neutral monochrome chevron, and **option-list tokens
pinned to legible dark-on-light** — this is the fix for admin's dark-on-dark native `<select>`
(the class is provided; admin migration is #775, not done here). `:focus-visible` ring;
`:disabled`.

```html
<select class="ow-select"><option>One</option><option>Two</option></select>
```

### Slider — `.ow-slider`

Kit-styled `<input type="range">`: **system-green** filled track, glass thumb — replaces the
bright-green admin slider look with the Apple system green. Set `--ow-slider-fill` (e.g. from
JS) to color the filled portion on WebKit. `:focus-visible` ring; `:disabled`.

```html
<input type="range" class="ow-slider" min="0" max="100" value="50" style="--ow-slider-fill:50%">
```

## Demo / verification — the full kit reference

The composite kits below are instantiated live in the app front-door (`workspace/static/`), not
via a standalone demo page (Orwell's `frontend/static/element_kit_demo.html` + demo-only
`orwellElements.js` driver did not vendor across). Verify them on the real surfaces, over a light
wallpaper at Full Glass + Frosted. The kit is two tiers:

1. **Atomic elements** — every AppkitElements primitive in every state (above), built by
   `appkitElements.js`. `appkitGlass.js` gives the `.ow-switch` / `.ow-slider` knobs the real
   `#owlg-thumb` SVG refraction at Full Glass (the switches render as actual liquid glass, not
   flat discs).
2. **Composite kits** — LIVE instances, instantiated through each kit's own seam:
   - **Windows (`AppkitWindowKit`, `appkitWindow.js`):** a standard HUD window, a `modal:true`
     centered dialog, and a `dockable` (docked) window — via
     `AppkitWindowKit.create({id,title,content,modal?,dockable?})`. Shows the `.ow-titlebar`
     (dark-ink title), the macOS **traffic-light** `.ow-controls` (rest + hover/focus glyphs),
     and the `.ow-body`. Window states: minimizable / closable / resizable / draggable; persisted
     layout + cross-device sync.
   - **Notifications (`AppkitNoticeKit`, `appkitNotice.js`):** an `.on-card` in each severity
     (info/warn/error) with the unified monochrome `.on-icon` set; the top system **banner**
     (`placement:"top-banner"`); and the **chat-hint** (the `AppkitChatHint` composition in
     `appkitChatHint.js` — kind "guide").
   - **Gadgets (`AppkitGadgetKit`, `appkitGadget.js`):** every real gadget KIND, instantiated
     live as `.og-card` (with `.og-head` + `.og-body`, action buttons, collapse chevron,
     system-blue `:focus-visible` header ring).
   - **Decision (`appkitDecision.js`, composed over `AppkitNoticeKit` kind "decision"):** a
     `.odec-*` card with prompt + selectable option buttons + a confirm action + an instruction
     note, plus the `.odec-risk` binding/irreversible variant.

Confirm legibility, Apple-correct states, and no-accent-on-text across every kit surface.

## References (Apple-authentic — see `LIQUID_GLASS_REFERENCE.md`)

- HIG **Buttons** (`sources/lg_text_lg_data_comp_buttons.md`): 44×44pt hit region; always
  include a press state; prominent = accent **background** with a legible label; **Destructive
  role uses system red**; *"avoid applying a similar color to button labels and content layer
  backgrounds"* → monochrome labels.
- HIG **Color** (`LIQUID_GLASS_REFERENCE.md` §6): glass has no inherent color; *"apply color
  to the background rather than to symbols or text"*; tint sparingly, primary actions only.
- HIG **Materials** (§1–§2): controls sit on a system material; no glass-on-glass — the
  knob/control rides the parent material; the transient slider/toggle knob becomes glass.
- HIG **Accessibility** (§5): honor Reduce Transparency / Increase Contrast / Reduce Motion;
  glass is never load-bearing for legibility.
- `lg_hig_slider_poster.png`, `lg_hig_segmented_control_poster.png` — the glass knob look.

### In-browser technique (the build method)

- **kube.io — "Liquid Glass with CSS + SVG"** — https://kube.io/blog/liquid-glass-css-svg/
  (the `feImage`/`feDisplacementMap` refraction, the `feBlend` specular rim, the displacement
  encoding + squircle curve, the `#switch` lip-bezel). The app's `#owlg-thumb` filter + the
  specular rim derive from this; the kit composes them.
- **Frontend Masters — "Liquid Glass on the Web"** — https://frontendmasters.com/blog/liquid-glass-on-the-web/
- App implementation the kit composes: `workspace/static/js/appkitGlass.js` (SVG refraction +
  `#owlg-thumb`, Full-Glass, perf-capped to chrome — **plus** the APCA/contrast veil + adaptive
  ink, the layer that was Orwell's separate `adaptiveGlass.js`).
