# CORPUS DIGEST — Liquid Glass (Apple Genius operating knowledge-base)

A dense, faithful rule-index distilled from the entire `docs/design/liquid-glass/` corpus:
the 5 core reference docs + every `sources/` extract (verbatim Apple HIG/DOC/WWDC + the one
cataloged web technique). Every concrete rule, exact number, threshold, and Apple term is
preserved. `"quoted"` = Apple's exact words. `[HIG]`/`[DOC]`/`[WWDC]`/`[NR]` = Apple-authoritative;
`[WEB‡]` = non-authoritative web-replication. iOS 26 / iPadOS 26 / macOS 26 "Tahoe", WWDC25 (June 2025).

> **Golden thread:** ONE glass plane (nav/controls) over content; never glass-on-glass; the material is
> colorless and takes color from behind; Regular is the default and adapts, Clear needs a 35% dimmer;
> color the *background* of a *single* primary action, never labels; the a11y trio strips glass and
> stays legible; ≥44×44pt targets; concentric radius = parent − padding.

---

## PART 1 — PER-FILE INDEX (what each file covers + its load-bearing specifics)

### Core reference docs

**`README.md`** — folder charter + implementation map + owner directives.
- The 5 non-negotiable owner principles: (1) **Authentic Apple always wins**; match pixel-for-pixel, **3–10 parity passes per surface**. (2) Material is **colorless/neutral** — no accent hue on glass **except** the two sanctioned accents (Apple **blue** on toggles, **green** on sliders) + a **single tinted primary-action CTA** (system-blue background) per view. (3) **One glass layer over content — never glass-on-glass**; "glass cannot properly sample other glass." (4) Legible over ANY background via Apple's **adaptive mechanism**, not a static veil. (5) SVG refraction is a **Chromium-only progressive enhancement** over a CSS-blur baseline.
- Adaptive-legibility summary: **small** bars/tiles stay clear + **flip the symbol** dark↔light by backdrop luminance (**linear Y, flip at 0.36**); **large** surfaces (sidebars/windows/modals/menus) **don't flip** (too big — distracting), the glass mutes adaptively. Only sanctioned darkening = **Clear's 35% dimmer** over bright media.
- a11y wins: `prefers-contrast: more` drops the flip (black/white + border); `prefers-reduced-transparency` → opaque; `prefers-reduced-motion` → no elastic/specular motion.
- Apple HIG/dev pages are **JS SPAs** — fetch the JSON data endpoint (`/tutorials/data/design/human-interface-guidelines/<page>.json`), not the HTML; WebFetch returns only titles.
- Implementation lives in `workspace/static/js/appkit*.js` + `workspace/static/style.css` (`body.theme-frosted`).

**`LIQUID_GLASS_REFERENCE.md`** — the compiled, fully-sourced rulebook (every rule = verbatim quote + source URL). Topics: layering / controls-vs-content / Regular-vs-Clear + dimming / concentricity+toolbars+sidebars+sheets+menus / accessibility / optics. Lead answers "does Apple do glass-on-glass? — **No.**" (All its load-bearing quotes are folded into Part 2 below.)

**`ADAPTIVE_LEGIBILITY_REFERENCE.md`** — deep-dive on the adaptive symbol/label mechanism + the closest web replication (CSS/SVG). Key concrete claims: adaptive color is BOTH a **discrete light↔dark flip** (small elements) AND a **continuous glass adaptation** (blur + luminosity + tint-amount + dynamic-range + shadow-opacity); big elements don't flip; **vibrancy is the real engine** (not opacity) — keeps the label's lightness, pulls hue/sat from backdrop; tint = "range of tones mapped to content brightness underneath." Web recipe: `mix-blend-mode: luminosity` (vibrancy analog) + `plus-lighter` (sheen) + `isolation: isolate` + a measured JS luminance flip (WCAG relative luminance, **threshold ≈ 0.36**) or `contrast-color()` (Safari 26+, WCAG-2 algorithm, black-or-white). Clear = `rgba(0,0,0,0.35)` only when backdrop bright.

**`ELEMENT_KIT.md`** — the `AppkitElements` atomic-control kit (`.ow-*`). Every control **rides the ONE glass plane** (fills/transparency/vibrancy, no second glass slab). Dark ink `#16191f` (`HERO_INK_DARK`); focus ring system-blue `#0a84ff` (fixed, ≠ theme accent), width 3px; ≈44px tap target. Button variants map to WWDC 310 tint-prominence: `.ow-btn-prominent`(primary) / `-secondary` / `-plain`(none) / `-destructive`(system red, secondary prominence). Size ladder sm/md hold ≥44px floor (type 13/14px), **lg 52px/16px, xl 62px/18px**; sm/md = rounded-rect, **lg/xl = capsule**; `-xl` reserved for the single prime action. `.ow-btn-concentric` = parent radius − parent inset, with standalone fallback. `.ow-btn-group` = ONE shared backdrop sample (segmented look). Switch knob + slider thumb = the **transient content-layer glass** taking the `#owlg-thumb` lip-bezel filter at Full Glass. Checkbox/radio: neutral at rest, system-blue fill + white glyph only when `:checked`. Slider = **system-green** track. Destructive-solid + `-xl` reserved for a single irreversible confirm.

**`REFERENCE_MANIFEST.md`** — image manifest (27 authentic Apple images: 22 HIG/dev-doc + 5 Newsroom) + the two cataloged non-HIG text sources (kube.io; WWDC 310). Notable refs: `lg_hig_ios_glass_clear/over_light/over_dark`, `materials_thin/regular/thick_bg`, `toolbar_grouping_correct/incorrect`, `sidebar_extend_correct/incorrect`, `slider_poster` (knob→glass), `segmented_control_poster`. Newsroom shows default/dark/**clear**/**tinted** Home-Screen looks + Icon Composer.

### Sources — Apple HIG (`[HIG]`)

**`lg_text_lg_data_materials.md`** (HIG Materials) — the material bible. Two material types: **Liquid Glass** (functional layer) + **standard materials** (content layer). Rules: *"Don't use Liquid Glass in the content layer"* (exception: transient slider/toggle knob); *"Use Liquid Glass effects sparingly … Limit these effects to the most important functional elements."* Regular vs Clear (Regular = default, blurs+adjusts luminosity, works any size/content; Clear = highly translucent for media-rich backgrounds). **35% dark dimming layer** behind Clear when content is bright (skip if content dark or AVKit provides its own). iOS/iPadOS **four standard materials: ultra-thin, thin, regular (default), thick** (thicker = more opaque/better contrast; thinner = more context). **Vibrancy levels: label(default, highest contrast)/secondaryLabel/tertiaryLabel/quaternaryLabel(lowest)**; fills: fill/secondaryFill/tertiaryFill; one separator level. *"avoid using quaternary on top of the thin and ultraThin materials."* *"use vibrant colors on top of materials."* visionOS: vibrancy "pulls light and color forward."

**`lg_text_lg_data_comp_color.md`** (HIG Color) — glass color rules. *"Liquid Glass has no inherent color, and instead takes on colors from the content directly behind it."* Small elements (toolbars/tab bars) adapt light↔dark: symbols/text monochrome, *"becoming darker when the underlying content is light, and lighter when it's dark."* *"Liquid Glass appears more opaque in larger elements like sidebars."* *"Apply color sparingly … To emphasize primary actions, apply color to the background rather than to symbols or text."* *"Refrain from adding color to the background of multiple controls."* Colorful backgrounds → prefer **monochromatic** toolbars/tab bars. *"Avoid hard-coding system color values."* Provide light+dark+increased-contrast variants for custom colors even if app is single-appearance. Dark-mode contrast can drop with Increase Contrast — test both.

**`lg_text_lg_data_layout.md`** (HIG Layout) — content extends edge-to-edge; controls/nav appear **on top of content, not on the same plane**. Use **background extension view** to fill behind sidebar/inspector. Use **scroll edge effect** (not a background) between content and control area. Respect safe areas (Dynamic Island, camera housing). **iOS: avoid full-width buttons** (inset from screen edges; if full-width, harmonize with hardware curvature). macOS: avoid controls at window bottom. tvOS safe area: inset **60pt top/bottom, 80pt sides**. visionOS: buttons ≥60pt center-to-center.

**`lg_text_lg_data_comp_typography.md`** (HIG Typography) — *"avoid light font weights"*; prefer **Regular/Medium/Semibold/Bold**, avoid Ultralight/Thin/Light. San Francisco (SF Pro/Compact/etc.) + New York (NY serif). Dynamic Type; minimize typefaces; keep hierarchy across sizes. WWDC 356 adds: typography is now **bolder and left-aligned** in alerts/onboarding. Section headers now **title-style capitalization** (not all-caps).

**`lg_text_lg_data_comp_buttons.md`** (HIG Buttons) — three attributes: **Style / Content / Role**. **Hit region ≥ 44×44pt (visionOS 60×60pt).** *"Always include a press state."* Prominent style = accent **background**; **keep prominent buttons to one or two per view.** *"Use style — not size — to distinguish the preferred choice."* *"Avoid applying a similar color to button labels and content layer backgrounds"* → prefer default monochromatic labels. Roles: Normal / **Primary** (default, accent, responds to Return) / Cancel / **Destructive** (system **red**). *"Don't assign the primary role to a … destructive action."* macOS image-button: ~10px padding. visionOS: 3 shapes (circle icon-only / rounded-rect or capsule text / capsule both); reserve white-bg+black-text for toggled state; centers ≥60pt apart, +4pt padding if ≥60pt.

**`lg_text_lg_data_comp_accessibility.md`** (HIG Accessibility) — enlarge text ≥**200%** (watchOS 140%). Contrast standards: **WCAG** + **APCA**; accessibility-inspector uses WCAG **AA**. Dark Mode contrast floor **4.5:1**, custom small text strive **7:1**. *"Convey information with more than color alone."* Control spacing: **~12pt padding around bezeled elements, ~24pt for non-bezel.** Reduce Motion → *"reducing automatic and repetitive animations, including zooming, scaling, and peripheral motion"* — tighten springs, track gestures, avoid z-axis depth animation, replace x/y/z transitions with fades, avoid animating into/out of blurs. Assistive Access: confirm twice for hard-to-recover actions.

**`lg_text_lg_data_comp_sidebars.md`** (HIG Sidebars) — sidebars are **inset, built with Liquid Glass, float above content**; extend rich content beneath via horizontal scroll or **background extension effect** (mirrors adjacent content, blurs to keep sidebar legible). Show **≤ two levels of hierarchy**. Sidebar icons default to app accent color; fixed colors sparingly for meaning. Don't put critical actions at the bottom.

**`lg_text_lg_data_comp_sheets.md`** (HIG Sheets) — modal vs nonmodal (iOS/iPadOS). Detents: **large** (full) + **medium** (~half). Include a **grabber** in resizable sheets. Cancel leading, Done trailing. Display **one sheet at a time**; never show Cancel+Done+Back together. watchOS sheet is semitransparent with a background material that blurs+desaturates.

**`lg_text_lg_data_comp_tab-bars.md`** (HIG Tab bars) — *"A tab bar floats above content at the bottom … items rest on a Liquid Glass background that allows content beneath to peek through."* For navigation, **not actions**. Keep it visible; **don't disable/hide tab buttons**; avoid overflow/More. Include labels (single words); prefer **filled** symbols. iOS: dedicated **Search tab at trailing end**; can minimize on scroll. iPadOS: tab bar near top, convertible to sidebar; default ≤5 tabs. *"Avoid applying a similar color to tab labels and content layer backgrounds."* tvOS tab bar height **68pt**, top edge **46pt** from top (fixed).

**`lg_text_lg_data_comp_toolbars.md`** (HIG Toolbars) — toolbars take Liquid Glass + **group items**. *"Minimize the number of groups … aim for a maximum of three."* *"Reduce the use of toolbar backgrounds and tinted controls"* — let the content layer inform color; use `ScrollEdgeEffectStyle`, not a background. **Keep text-labeled actions separate** (insert fixed space) — text next to a symbol reads as one button. Prefer **system symbols without borders**. *"Use the `.prominent` style for key actions such as Done or Submit … Only specify one primary action, and put it on the trailing side."* Title < 15 chars; don't title with app name. Three zones: leading / center / trailing. Custom components must be **concentric** with the bar corners.

**`lg_text_lg_data_comp_menus.md`** (HIG Menus) — menus adopt Liquid Glass; **use icons for key actions** (a single scannable column), sparingly + uniformly (all-or-none per group). Title-style capitalization; remove articles; append **…** when more input needed. Group logically + separators. Submenus **single level**, ≤~5 items. iOS/iPadOS layouts: **Small** (row of 4 icon-only), **Medium** (row of 3 icon+label), **Large** (default, full list).

**`lg_text_lg_data_comp_popovers.md`** (HIG Popovers) — transient; a few related tasks. Arrow points at its source; don't cover the trigger. **Show one popover at a time; never cascade.** Don't warn in a popover (use an alert). macOS detachable → panel.

**`lg_text_lg_data_comp_search-fields.md`** (HIG Search fields) — Search icon + Clear button + placeholder. iOS: search as **tab** (standard vs button-appearance) / **toolbar** (prefer bottom) / **inline**. iPadOS/macOS: trailing side of toolbar, or top of sidebar. Start search while typing; scope bars + tokens.

**`lg_text_lg_data_comp_motion.md`** (HIG Motion) — Liquid Glass motion responds **more emphatically to direct touch, more subdued via trackpad**. Add motion purposefully; make it **optional**; avoid motion on frequent UI interactions; let people cancel motion. visionOS: avoid peripheral motion; avoid **~0.2 Hz oscillation** (people are very sensitive).

**`lg_text_lg_data_comp_dark-mode.md`** (HIG Dark Mode) — *"Avoid offering an app-specific appearance setting"* (respect system). Semantic colors adapt automatically; contrast floor **4.5:1**, custom small text **7:1**. iOS Dark uses **base** (recede) + **elevated** (advance) background sets. Provide light+dark color-set variants; don't hard-code colors. macOS **desktop tinting** (graphite accent) — include some transparency in neutral-state custom backgrounds.

**`lg_text_lg_data_comp_icons.md`** (HIG Icons/glyphs) — interface icons: simple, consistent (size/weight/stroke/perspective), **match weight to adjacent text**, optical (not geometric) centering, vector (PDF/SVG). Don't provide selected/unselected states for standard toolbar/tab/button icons (system handles it). Standard SF Symbols for common actions.

**`lg_text_lg_data_comp_app-icons.md`** (HIG App icons) — layered (background + ≥1 foreground); take Liquid Glass attributes (**specular highlights, refraction, translucency**), applied by the system. **Let the system handle blur/shadow/highlight** — don't bake them in. Square layers (iOS/iPadOS/macOS masked to rounded rect; visionOS/watchOS circular); tvOS rectangular; keep content centered. Appearances: **default / dark / clear / tinted**. Prefer overlapping filled shapes + varied opacity. Vector artwork; PNG for raster/mesh gradients.

**`lg_text_lg_data_comp_right-to-left.md`** (HIG Right-to-left) — reverse layout for RTL; **flip progress/nav controls** (sliders, back buttons), never flip logos/universal marks/real-world-direction icons; **don't reverse digits within a number**; align paragraphs by language; balance RTL vs all-caps Latin (+~2pt). SF Symbols provide RTL variants.

**`lg_text_lg_data_comp_the-menu-bar.md`** (HIG Menu bar) — macOS/iPadOS menu order: AppName, File, Edit, Format, View, app-specific, Window, Help. One-word titles; represent actions with familiar icons; always show the same set (disable, don't hide). Menu bar height **24pt** (macOS extras). Dynamic menu items require a single modifier.

### Sources — Apple developer docs (`[DOC]`)

**`lg_text_lg_data_techoverview_liquidglass.md`** (DOC — Liquid Glass overview) — high-level: material "combines the optical properties of glass with a sense of fluidity"; standard components adopt it automatically; establish hierarchy/harmony/consistency; Landmarks is the sample app.

**`lg_text_lg_data_adopting_liquidglass.md`** (DOC — Adopting Liquid Glass) — the adoption checklist. *"Leverage system frameworks to adopt Liquid Glass automatically."* *"Reduce your use of custom backgrounds in controls and navigation elements."* *"Avoid overusing Liquid Glass effects."* *"Check for crowding or overlapping of controls … avoid overcrowding or layering Liquid Glass elements on top of each other."* *"Consider aligning the shape of controls with other rounded elements"* (concentric). Sliders/toggles: *"the knob transforms into Liquid Glass during interaction, and buttons fluidly morph into menus and popovers."* Half-sheet at full height → **more opaque**. **Audit backgrounds of sheets/popovers** (remove custom visual-effect views). Action sheet **originates from the initiating element**. Tab bar can auto-minimize on scroll. **New extra-large control size.** `GlassEffectContainer` to combine custom effects. `UIDesignRequiresCompatibility` to opt out.

**`lg_text_applying_lg_custom.md`** (DOC/SwiftUI — Applying Liquid Glass to custom views) — `glassEffect(_:in:)` defaults to **Regular in a Capsule**; add tint / `interactive(_:)`. **`GlassEffectContainer`** = best perf + blends/morphs shapes; **spacing** controls when shapes merge (larger spacing → merge sooner; container spacing > interior stack spacing = merged at rest). `glassEffectUnion(id:namespace:)`, `glassEffectID(_:in:)`, `GlassEffectTransition` (**matchedGeometry** default; **materialize** for farther-apart). *"Liquid Glass … blurs content behind it, reflects color and light of surrounding content, and reacts to touch and pointer interactions in real time."* *"Creating too many Liquid Glass effect containers … can degrade performance. Limit the use of Liquid Glass effects onscreen at the same time."*

**`lg_text_landmarks_app.md`** (DOC — Landmarks sample) — `NavigationSplitView`; `backgroundExtensionEffect()` on hero images; horizontal scroll under sidebar/inspector; system glass in toolbars (organized into groups); custom glass badges via `glassEffect` + `GlassEffectContainer` + `glassEffectID`; app icon in Icon Composer (**4 layers** → specular highlights).

### Sources — WWDC transcripts (`[WWDC]`)

**`lg_wwdc_219_transcript.md`** ("Meet Liquid Glass") — the foundational talk. **Lensing** is the defining optic (bends/shapes/concentrates light in real time; previous materials *scattered* light). Layers continuously adapt: shadows grow over text, **tint amount + dynamic range shift**, can switch light/dark. Larger glass = thicker: *"deeper, richer shadows, more pronounced lensing and refraction, softer scattering of light."* **Shadow opacity: higher over text, lower over solid light background.** **Highlights** respond to geometry + move on lock/unlock. *"always avoid glass on glass … use fills, transparency, and vibrancy for the top elements."* **Regular vs Clear never mixed**; Clear = no adaptive behavior, permanently transparent, needs dimming; **3 Clear conditions** (over media-rich content / content layer won't be hurt by dimming / content above is bold+bright). **Localized dimming** for small footprints. **Small nav/tab bars flip light↔dark; big elements (menus/sidebars) don't flip.** Symbols mirror the flip. Tinting = *"range of tones mapped to content brightness underneath"* (like colored glass); a **solid fill "breaks the visual character of Liquid Glass."** *"Avoid tinting all your elements. When every element is tinted, nothing stands out."* *"avoid intersections between content and Liquid Glass"* in steady states. **Materialize (modulate lensing), don't fade.** a11y trio: Reduced Transparency = frostier; Increased Contrast = **predominantly black/white + contrasting border**; Reduced Motion = disables elastic properties.

**`lg_wwdc_356_transcript.md`** ("Get to know the new design system") — concentricity + structure. **Three shape types: fixed** (constant radius) / **capsule** (radius = ½ container height) / **concentric** (radius = **parent radius − padding**). Views mathematically centered when it makes sense. Watch for **pinched or flared** corners; nested artwork should be concentric. Phone: capsule + extra margin near screen edge; iPad/Mac: concentric aligned to window edge. **Concentric shape with a fallback radius** works both nested and standalone. *"controls sit on top of a system material, not directly on content. Without that separation, contrast can suffer."* **Scroll edge effects: soft (default, iOS) vs hard (macOS, pinned headers); one per view; don't mix/stack; not decorative** (don't block/darken). Sidebars inset + glass, content flows behind (background extension). Bars now rely on symbols; **group by function+frequency; don't group symbols with text; text buttons on their own containers; a primary action (Done) stays separate + tinted.** iOS Search tab at bottom. Dimming layer signals modality on sheets; dragging a sheet up → glass **recedes, more opaque, grows**. Use the same symbols across devices; text label when no clear shorthand.

**`lg_wwdc_310_appkit_new_design.md`** ("Build an AppKit app with the new design", `NS*` APIs) — the control/glass specifics. **Five control sizes: mini → small → medium → large → extra-large** (new in Tahoe); **mini/small/medium = rounded rect, large/extra-large = capsule**; mini/small/medium now **slightly taller** (bigger click target); **never hard-code height** (Auto Layout; `prefersCompactControlSizeMetrics` for legacy density). Extra-large = the single most-prominent action. **Tint prominence: automatic / none / secondary / primary**; default button (`keyEquivalent = "\r"`) auto-takes **primary**; destructive = **red at secondary** prominence; sliders — `none` ⇒ track not filled, `secondary`/`primary` ⇒ filled; slider **`neutralValue`** anchors fill anywhere (e.g. **1x** playback). Toolbar: buttons auto-group on one glass, other control types get own glass; `NSToolbarItemGroup`/spacers to override; `.style = .prominent` (accent) or `.backgroundTintColor` (e.g. `.systemGreen`); **`isBordered = false`** to remove glass from non-interactive titles/status; `NSItemBadge.count(4)/.text("New")/.indicator`. Windows: **larger corner radius with toolbars, smaller titlebar-only**; `NSView.LayoutRegion` + `layoutGuide(for: .safeArea(cornerAdaptation: .horizontal|.vertical))` for corner-collision avoidance. Sidebars = floating glass pane, inspectors = edge-to-edge glass; remove legacy `NSVisualEffectView` sidebar material; `automaticallyAdjustsSafeAreaInsets = true` on the **content** (not sidebar); `NSBackgroundExtensionView` mirrors+blurs. Custom glass: **`NSGlassEffectView`** — set `.contentView` (must **wrap** content, never a sibling behind it), `.cornerRadius` (**999 = capsule**), tint. **`NSGlassEffectContainerView`** for adjacent glass: (a) fluid meld by proximity + `spacing`; (b) shared adaptive appearance; (c) **correctness — "glass can't directly sample other glass," so share ONE sampling region; also one sampling pass = faster.** (This is the direct rationale for one shared backdrop-sample per group on the web.)

### Sources — cataloged web technique (`[WEB‡]`, non-authoritative)

**`lg_text_kube_liquid_glass_css_svg.md`** (kube.io — "Liquid Glass in the Browser") — the refraction build method. Snell–Descartes `n₁·sin θ₁ = n₂·sin θ₂`; glass index **1.5**, air **1**. **Squircle surface curve Apple favors: `y = ⁴√(1−(1−x)⁴)`** (convex circle `y=√(1−(1−x)²)`; concave `1−Convex(x)`; **lip** `mix(Convex,Concave,Smootherstep)` for the switch bezel). Displacement field: **127 ray sims** across a half-slice, rotated around the bezel. Encode: **R = 128 + x·127, G = 128 + y·127, B=128, A=255** (128 = neutral). `feImage`(displacement-map data-URL) → **`feDisplacementMap in="SourceGraphic" in2="displacement_map" scale=<px> xChannelSelector="R" yChannelSelector="G"`**, applied via **`backdrop-filter: url(#id)` — Chromium-only** (only Chromium exposes SVG filters as backdrop-filter). `feDisplacementMap` scale maps 0↦−scale / 128↦0 / 255↦+scale — **animate `scale` for fade in/out** (cheap; everything else forces a full map rebuild). Specular = **`feBlend` rim-light** responding to surface-normal vs a fixed light direction (**e.g. −60°**) — described only (no code). Backdrop-filter dims don't auto-fit — the filter images must match element size.

### Empty files (noted for completeness)
`lg_text_lg_data_components_sidebars.md` and `lg_text_lg_data_components_toolbars.md` are **0 bytes** (the real content lives in the `comp_` variants at the root HIG slug — the manifest notes the `components/` prefix 404'd).

---

## PART 2 — RULE INDEX BY TOPIC (concrete rules, exact numbers/terms)

### A. MATERIALS
- **Two glass variants: Regular + Clear — never mixed.** Regular = default/most-used; adaptive; blurs + adjusts luminosity; works any size, any content, anything can sit on top. Clear = permanently more transparent, **no adaptive behavior**, needs a dimming layer.
- **Clear's dimming layer = a dark layer of 35% opacity** over bright content. Skip it if content is sufficiently dark or AVKit provides its own. Small footprint → **localized dimming**.
- **Clear's 3 conditions (all required):** over media-rich content; content layer won't be hurt by dimming; content above is bold + bright.
- **Four *standard* (content-layer) materials: ultra-thin / thin / regular (default) / thick.** Thicker = more opaque/better contrast; thinner = more context. These are NOT glass — they're for the content layer.
- **Vibrancy label levels: label (default, highest contrast) / secondaryLabel / tertiaryLabel / quaternaryLabel (lowest).** Fills: fill/secondaryFill/tertiaryFill. Avoid quaternary on thin/ultra-thin.
- Use Liquid Glass **sparingly** — most important functional elements only; overuse distracts from content.

### B. LAYERING (the glass-on-glass rule)
- **ONE glass plane = the floating nav/controls layer above content.** *"Don't use Liquid Glass in the content layer."*
- **Never glass-on-glass.** Elements on top of glass use **fills / transparency / vibrancy** — *"a thin overlay that is part of the material."*
- **"Glass can't directly sample other glass"** — the technical reason. Multiple glass shapes go in ONE container (`GlassEffectContainer` / `NSGlassEffectContainerView`) so they **blend/morph into one** + share one sampling pass.
- **Controls sit on a system material, not directly on content** ("like Safari today") — that separation provides legibility; **scroll edge effects** reinforce the boundary.
- **Avoid intersections between content and glass** in steady states; reposition/scale content instead.
- Only sanctioned content-layer glass = the **transient slider/toggle knob** while actively manipulated.

### C. COLOR / TINT
- **Glass is colorless — it takes color from the content directly behind it.** No accent on the glass itself.
- **Tint the BACKGROUND, not symbols/text.** *"To emphasize primary actions, apply color to the background rather than to symbols or text."*
- **Tint sparingly — reserve for one primary action / status.** *"When every element is tinted, nothing stands out."* *"Refrain from adding color to the background of multiple controls."* One-or-two prominent buttons per view.
- **A solid/opaque fill "breaks the visual character of Liquid Glass"** — use the built-in *tinting* (translucent), which generates *"a range of tones mapped to content brightness underneath"* (colored-glass tone map).
- Colorful content layer → **prefer monochromatic toolbars/tab bars/labels**; *"avoid applying a similar color to button/tab/toolbar labels and content layer backgrounds."*
- Sanctioned accents (this project): Apple **blue** on toggles, **green** on sliders/tracks, **red** for destructive (system red), one **system-blue** primary CTA. Focus ring = fixed system blue `#0a84ff` (≠ theme accent).
- Provide light + dark + increased-contrast color variants even in a single-appearance app.

### D. ADAPTIVE LEGIBILITY (the hardest part to get right)
- **Small elements (navbars/tabbars/small tiles) flip light↔dark by the backdrop; symbols mirror the flip** (dark symbols over light content, light symbols over dark). **Big elements (sidebars/menus/windows) do NOT flip** — surface too big, would distract; they adapt the material only, and appear **more opaque** at larger size.
- The **flip is discrete**; underneath it the **glass adapts continuously** — blur + luminosity + **tint amount + dynamic range + shadow opacity**. **Shadow opacity rises over text, falls over a solid light background.**
- **Vibrancy ≠ opacity.** It keeps the label's lightness and pulls hue/sat from the backdrop. Web analog = `mix-blend-mode: luminosity` + `isolation: isolate`, paired with a light/dark flip + a `text-shadow`/scrim floor.
- **Web flip threshold: WCAG relative luminance Y ≈ 0.36** (perceptual midpoint; better than 0.5). Or `contrast-color()` (Safari 26+, WCAG-2, returns black or white) when the local backdrop color is known.
- **The only sanctioned *darkening*:** (a) Clear's **35% dimmer** over bright media; (b) a scroll-edge **"subtle dimming"** the glass swaps to when *dark* content scrolls under. Regular glass is NOT dark-plated behind a light symbol — it keeps the glass clear and adapts the symbol.
- Under **Increase Contrast** the subtle flip is superseded by **black/white + contrasting border** (the WCAG-safe state).

### E. OPTICS (what reads as glass)
- **Lensing / refraction** is the defining optic — light bends at the edges; the silhouette is read from the warp, not a border. *"dynamically bends, shapes, and concentrates light in real time."*
- **Moving specular highlights** respond to geometry, travel on interaction (lock/unlock), sometimes device motion.
- **Thicker/larger glass = deeper shadows + more pronounced lensing + softer light scatter.**
- **Materialize in/out by modulating lensing — don't fade opacity.** (Web: animate `feDisplacementMap` `scale`.)
- Web: `backdrop-filter: blur(8–20px) saturate(160–180%) brightness(~1.05)` (field practice, not Apple-published) + SVG displacement map (Chromium-only) + `feBlend` rim-light (light ≈ −60°). Squircle curve `y=⁴√(1−(1−x)⁴)`, encode R=128+x·127 / G=128+y·127.

### F. CONCENTRICITY / SHAPE / GEOMETRY
- **Three shape types: fixed** (constant radius) / **capsule** (radius = **½ container height**) / **concentric** (radius = **parent radius − padding**).
- **Concentric shape with a fallback radius** handles both nested and standalone.
- Glass controls **nest into the rounded corners of windows** (maintain concentricity). Windows: **larger radius with a toolbar, smaller titlebar-only.** Watch for **pinched/flared** corners.
- Sheets have an **increased corner radius**; list/table sections have increased corner radius; larger row heights + padding.

### G. TYPOGRAPHY
- **Avoid light weights** (no Ultralight/Thin/Light); prefer **Regular/Medium/Semibold/Bold**.
- **Bolder + left-aligned** in alerts/onboarding (Tahoe). Section headers → **title-style capitalization** (not all-caps).
- SF Pro (iOS/iPadOS/macOS/tvOS/visionOS), SF Compact (watchOS), New York (serif). SF Symbols match text weight. Support Dynamic Type; minimize typefaces; keep hierarchy at all sizes.

### H. MOTION
- Liquid Glass motion is **more emphatic on direct touch, more subdued on trackpad**.
- Purposeful + **optional**; avoid motion on frequent UI interactions; let people cancel it; brief + precise feedback.
- **Reduce Motion** disables elastic/morph/specular; also: tighten springs, track gestures, avoid z-axis depth animation, replace x/y/z transitions with fades, don't animate into/out of blurs, no zoom/scale/peripheral motion. Avoid ~0.2 Hz oscillation (visionOS).

### I. COMPONENTS (quick rules)
- **Buttons:** ≥44×44pt hit region (visionOS 60×60pt); always a press state; prominent = accent **background**, 1–2 per view; style-not-size distinguishes preference; roles Normal/Primary/Cancel/Destructive(red); never Primary on a destructive action. **Five sizes** mini→XL; mini/sm/md rounded-rect, lg/XL capsule; XL for the single prime action; never hard-code height. **Tint prominence** automatic/none/secondary/primary; default button auto-primary; destructive red at secondary.
- **Toolbars:** ≤3 groups; keep text-labeled actions separate (fixed space); system symbols without borders; `.prominent` for the one trailing primary action; no custom backgrounds — use scroll edge effect; concentric custom components.
- **Tab bars:** float at bottom, content peeks through; navigation not actions; never disable/hide tabs; filled symbols + single-word labels; iOS Search tab trailing; can minimize on scroll.
- **Sidebars:** inset glass, content flows behind (background extension); ≤2 hierarchy levels; no critical actions at bottom; remove legacy visual-effect material.
- **Sheets:** detents large/medium; grabber; Cancel leading / Done trailing; one at a time; half-sheet → **more opaque at full height**; audit/remove custom backgrounds.
- **Popovers:** one at a time, never cascade; arrow at source; don't warn (use alert).
- **Menus:** Liquid Glass; icons for key actions (single scannable column, all-or-none per group); title-style caps; submenus single level ≤~5.
- **Action sheet:** originates from the initiating element (not the screen bottom).
- **App icons:** layered; system applies specular/refraction/translucency — don't bake effects in; default/dark/clear/tinted variants; square (masked) layers; centered content.

### J. ACCESSIBILITY (the a11y trio + baseline)
- **Reduce Transparency** → glass frostier / near-opaque (`backdrop-filter: none; solid bg`). **Increase Contrast** → predominantly **black/white + contrasting border** (`Canvas`/`CanvasText`, drop the flip). **Reduce Motion** → disable elastic/specular/morph animation. All three available automatically with the system material; **a parity build must honor `prefers-reduced-transparency`, `prefers-contrast`, `prefers-reduced-motion`** and stay fully legible/operable when glass is stripped — **glass is never load-bearing for legibility.**
- Contrast: WCAG **AA** (inspector), **4.5:1** floor, **7:1** for custom small text; APCA also cited. Convey info with more than color. Enlarge text ≥200% (watchOS 140%). Control spacing ~12pt (bezeled) / ~24pt (non-bezel). Provide accessibility labels for every icon.

---

## PART 3 — MOST-VIOLATED RULES (audit shortlist for a Liquid Glass web UI)

The rules a web reimplementation most often breaks — check these first:

1. **Glass-on-glass.** A glass panel/card with glass buttons/inputs nested inside (each with its own `backdrop-filter`). Fix: ONE glass surface; nested controls use fills/transparency/vibrancy and share ONE backdrop sample (group).
2. **Glass in the content layer.** Making list rows / tables / backgrounds glassy. Glass is the nav/controls plane only; content uses standard materials.
3. **Tinting the label instead of the background** (colored text/symbols on glass) or **tinting everything.** Color the *background* of a *single* primary action; keep labels monochromatic; one-or-two prominent per view.
4. **Opaque solid fills that "break the visual character."** A flat solid primary button instead of a translucent *tint* that samples the backdrop.
5. **No adaptive legibility** — a static frosted veil / fixed light-or-dark labels that fail over a photo or the opposite theme. Small bars must flip symbols by backdrop luminance (Y ≈ 0.36); the glass must adapt continuously; large surfaces must NOT flip.
6. **Missing the a11y trio** — no `prefers-reduced-transparency` (→ opaque), no `prefers-contrast: more` (→ black/white + border, drop the flip), no `prefers-reduced-motion` (→ kill elastic/specular). Legibility must survive glass being stripped.
7. **Wrong Clear/dimming handling** — Clear glass with no 35% dimmer over bright media, or a dimmer left on over dark/video backdrops, or Regular+Clear mixed in one place.
8. **Broken concentricity** — hand-rolled radii, pinched/flared corners, controls not nesting into parent radius. Radius = parent − padding (concentric) or ½ height (capsule).
9. **Sub-44pt targets / no press state / no focus ring.** ≥44×44pt (60 visionOS); always a press state; visible system-blue focus ring.
10. **Custom toolbar/bar backgrounds + >3 groups + text-next-to-symbol.** Remove custom bar backgrounds (use scroll edge effect), ≤3 groups, separate text-labeled actions with fixed space, one trailing primary.
11. **Light font weights + all-caps section headers + accent-hued body text.** Use Regular/Medium/Semibold/Bold; title-style caps; monochromatic labels over colorful content.
12. **Fading instead of materializing, and shadow that ignores the backdrop.** Modulate lensing (animate displacement scale), not opacity; raise shadow opacity over text, lower over solid light backgrounds.
