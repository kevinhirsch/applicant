# Apple Liquid Glass — Authoritative Reference (iOS 26 / macOS 26 "Tahoe", introduced June 2025)

Compiled for a UI-parity effort. **Every quote below is verbatim from an Apple-authentic source**
(developer.apple.com Human Interface Guidelines, Apple developer documentation, Apple WWDC25 session
transcripts, or apple.com Newsroom). Exact source URLs are given per quote. Third-party material is
explicitly excluded. Where a HIG page is a JS SPA, the quote is taken from the same page's JSON data
endpoint (`/tutorials/data/.../<page>.json`), which is the page's own canonical content.

> **Source legend:** `[HIG]` Human Interface Guidelines · `[DOC]` Apple developer documentation ·
> `[WWDC]` WWDC25 session transcript · `[NR]` apple.com Newsroom. All are Apple-authoritative.

---

## TL;DR — Does Apple do glass-on-glass? No. The rule, sourced.

**Apple's explicit rule is: do NOT stack Liquid Glass on Liquid Glass.** Liquid Glass is reserved for a
single floating *navigation/controls layer* above the content; you do not put glass in the content
layer, and you do not put a glass element on top of another glass element. When something must sit on
top of glass, it uses **fills / transparency / vibrancy** (i.e. it rides the parent material), **not its
own glass**.

> "You may be tempted to use Liquid Glass everywhere but it is best reserved for the navigation layer
> that floats above the content of your app. … **Similarly, always avoid glass on glass. Stacking Liquid
> Glass elements on top of each other can quickly make the interface feel cluttered and confusing. When
> placing elements on top of Liquid Glass, avoid applying the material to both layers. Instead, use
> fills, transparency, and vibrancy for the top elements to make them feel like a thin overlay that is
> part of the material.**"
> — `[WWDC]` *Meet Liquid Glass* (WWDC25 session 219), https://developer.apple.com/videos/play/wwdc2025/219/

> "**Don't use Liquid Glass in the content layer.** Liquid Glass works best when it provides a clear
> distinction between interactive elements and content, and including it in the content layer can result
> in unnecessary complexity and a confusing visual hierarchy. Instead, use … Standard materials for
> elements in the content layer, such as app backgrounds. An exception to this is for controls in the
> content layer with a transient interactive element like sliders and toggles; in these cases, the
> element takes on a Liquid Glass appearance to emphasize its interactivity when a person activates it."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

> "**Check for crowding or overlapping of controls.** Prefer to use standard spacing metrics instead of
> overriding them, and **avoid overcrowding or layering Liquid Glass elements on top of each other.**"
> — `[HIG/DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

**Layer economy / "one glass layer" corollary:** Apple frames Liquid Glass as a single distinct
*functional layer* that floats above content — not a stackable decoration. Use it sparingly and only on
the most important functional elements.

> "Liquid Glass forms a **distinct functional layer** for controls and navigation elements — like tab
> bars and sidebars — that floats above the content layer, establishing a clear visual hierarchy between
> functional elements and content. … **Use Liquid Glass effects sparingly.** … overusing this material
> in multiple custom controls can provide a subpar user experience by distracting from that content.
> Limit these effects to the most important functional elements in your app."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

**The "glass cannot sample other glass" technical basis** (why stacking is disallowed and why blending
is the sanctioned alternative): in code you do not nest glass effects; you put multiple glass shapes in a
single `GlassEffectContainer` so they **blend/morph into one shape** rather than layering, and you cap
how much glass is on screen.

> "Use `GlassEffectContainer` when applying Liquid Glass effects on multiple views to achieve the best
> rendering performance. A container also allows views with Liquid Glass effects to **blend their shapes
> together and to morph in and out of each other** during transitions. … **Creating too many Liquid Glass
> effect containers and applying too many effects to views outside of containers can degrade
> performance. Limit the use of Liquid Glass effects onscreen at the same time.**"
> — `[DOC]` Applying Liquid Glass to custom views, https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views

**Parity takeaway:** model exactly ONE glass plane (the nav/controls layer). Content gets standard
materials, never glass. Anything resting on the glass uses fills/transparency/vibrancy — it is part of
that one sheet, not a second sheet. The only sanctioned content-layer glass is a *transient* control
knob (slider/toggle) that becomes glass only while actively manipulated.

---

## 1. LAYERING / glass-on-glass — the exact rule

See the TL;DR for the load-bearing quotes. Additional supporting wording:

> "Liquid Glass applies to the topmost layer of the interface, where you define your navigation. Key
> navigation elements like tab bars and sidebars float in this Liquid Glass layer to help people focus on
> the underlying content. **Establish a clear navigation hierarchy.** … Ensure that you clearly separate
> your content from navigation elements, like tab bars and sidebars, to establish a distinct functional
> layer above the content layer."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "But it's also constantly, subtly changing to ensure legibility and **to maintain clear separation from
> the content layer.**" … "Scroll edge effects work in concert with Liquid Glass to maintain that crucial
> separation between the UI and content layers and ensure legibility."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "In steady states, such as when an app first launches, **avoid intersections between content and Liquid
> Glass.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Rule summary:** glass = the single floating nav/controls plane. Never glass-in-content; never
glass-on-glass; never let two glass surfaces overlap. Use a single container so multiple glass shapes
blend into one rather than stack.

---

## 2. CONTROLS vs CONTENT — do controls get their own glass, or sit on a system material?

**Authoritative answer: controls sit on top of a system material, NOT directly on content** — that
system material provides the separation/legibility. Standard controls pick up Liquid Glass automatically
from the framework; you should not be hand-applying glass to each control.

> "… elements that adopt Liquid Glass require clear separation from content to maintain legibility. **Like
> in Safari today, controls sit on top of a system material, not directly on content. Without that
> separation, contrast can suffer.** Scroll edge effects reinforce that boundary, replacing hard dividers
> with subtle blur to reduce clutter and keep UI legible. And remember, scroll edge effects are not
> decorative. They don't block or darken like overlays. They simply clarify where UI and content meet,
> and shouldn't be used where there aren't any floating UI elements."
> — `[WWDC]` Get to know the new design system (WWDC25 session 356), https://developer.apple.com/videos/play/wwdc2025/356/

> "**Leverage system frameworks to adopt Liquid Glass automatically.** In system frameworks, standard
> components like bars, sheets, popovers, and controls automatically adopt this material. … **Reduce your
> use of custom backgrounds in controls and navigation elements.** Any custom backgrounds and appearances
> you use in these elements might overlay or interfere with Liquid Glass or other effects that the system
> provides, such as the scroll edge effect."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "**Leverage new button styles.** Instead of creating buttons with custom Liquid Glass effects, you can
> adopt the look and feel of the material with minimal code by using one of the following button style
> APIs"
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "**Reduce the use of toolbar backgrounds and tinted controls.** Any custom backgrounds and appearances
> you use might overlay or interfere with background effects that the system provides. Instead, use the
> content layer to inform the color and appearance of the toolbar, and use a `ScrollEdgeEffectStyle` when
> necessary to distinguish the toolbar area from the content area."
> — `[HIG]` Toolbars, https://developer.apple.com/design/human-interface-guidelines/toolbars

**Transient exception (content-layer controls):** sliders/toggles knobs become glass only during
interaction.

> "For controls like sliders and toggles, **the knob transforms into Liquid Glass during interaction**,
> and buttons fluidly morph into menus and popovers."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

**Parity takeaway:** put controls on a shared system-material bar/surface; do not give each button its
own glass slab. The bar is the one glass surface; the buttons are vibrant content riding on it.

---

## 3. The two material variants — Regular vs Clear — and the dimming layer

> "There are two to choose from: Regular and Clear. **They should never be mixed,** as they each have
> their own characteristics and specific use cases. **Regular is the most versatile and the one you will
> be using the most.** This variant gives you all the visual and adaptive effects we've talked about, and
> provides legibility regardless of context. **It works in any size, over any content and anything can be
> placed on top of it.** Clear, on [the other hand] … To provide enough legibility for symbols or labels,
> **it needs a dimming layer to darken the underlying content.** … whereas the Regular variant can work
> anywhere, **Clear should only be used when these 3 conditions are met. First, the element you're
> applying it to is over media-rich content. Second, your content layer won't be negatively affected by
> introducing a dimming layer. And lastly, the content sitting above it is bold and bright.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "**Only use clear Liquid Glass for components that appear over visually rich backgrounds.** … The
> *regular* variant blurs and adjusts the luminosity of background content to maintain legibility … Most
> system components use this variant. Use the regular variant when background content might create
> legibility issues, or when components have a significant amount of text, such as alerts, sidebars, or
> popovers. The *clear* variant is highly translucent, which is ideal for prioritizing the visibility of
> the underlying content … Use this variant for components that float above media backgrounds — such as
> photos and videos — to create a more immersive content experience."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

**Dimming layer over bright media (concrete number):**

> "For optimal contrast and legibility, determine whether to add a dimming layer behind components with
> clear Liquid Glass: **If the underlying content is bright, consider adding a dark dimming layer of 35%
> opacity.** … If the underlying content is sufficiently dark, or if you use standard media playback
> controls from AVKit that provide their own dimming layer, you don't need to apply a dimming layer."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

> "If Liquid Glass elements in your app have a smaller footprint, you can use **localized dimming** and
> allow the content to retain more of its original vibrancy."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Parity takeaway:** default to **Regular** glass for almost everything (it adapts and stays legible
anywhere, and you may place content on top of it). Use **Clear** only over bright/bold media, and pair it
with a **~35% dark dimming layer** (or localized dimming for small elements). Never mix Regular and Clear
in the same place.

---

## 4. Concentric / grouped controls · sidebars · sheets · popovers · toolbars · tab bars

**Concentricity (shape geometry):**

> "There's a quiet geometry to how our shapes fit together, driven by concentricity. By aligning radii
> and margins around a shared center, shapes can comfortably nest within each other. … We use **three
> shape types** to build concentric layouts: **fixed shapes** have a constant corner radius. **Capsules**
> use a radius that's half the height of the container. And **concentric shapes** calculate their radius
> by subtracting padding from the parent's."
> — `[WWDC]` Get to know the new design system (356), https://developer.apple.com/videos/play/wwdc2025/356/

> "Glass controls nest perfectly into the rounded corners of windows, **maintaining concentricity
> throughout the UI.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "**Consider aligning the shape of controls with other rounded elements throughout the interface.**
> Across Apple platforms, the shape of the hardware informs the curvature, size, and shape of nested
> interface elements, including controls, sheets, popovers, windows, and more."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

**Grouped controls / toolbar groups:**

> "toolbars take on a Liquid Glass appearance, and provide a grouping mechanism for toolbar items …
> **Determine which toolbar items to group together.** Group items that perform similar actions or affect
> the same part of the interface … For consistency, don't mix text and icons across items that share a
> background."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "**Minimize the number of groups.** Too many groups of controls can make a toolbar feel cluttered and
> confusing, even with the added space on iPad and Mac. **In general, aim for a maximum of three.**"
> — `[HIG]` Toolbars, https://developer.apple.com/design/human-interface-guidelines/toolbars

> "Group bar items by function and frequency. … be sure to not group symbols with text … **If you have a
> need for text buttons, allow them to sit on their own containers. A primary action, like Done, stays
> separate.**"
> — `[WWDC]` Get to know the new design system (356), https://developer.apple.com/videos/play/wwdc2025/356/

**Sidebars (glass, inset, content extends beneath):**

> "the focus on content carries over to sidebars … **sidebars are now inset and built with Liquid Glass,
> allowing content to flow behind them** for a more immersive feel. Background extension effects let
> content expand behind the [sidebar]."
> — `[WWDC]` Get to know the new design system (356), https://developer.apple.com/videos/play/wwdc2025/356/

> "**Extend visually rich content beneath the sidebar.** In iOS, iPadOS, and macOS … sidebars can float
> above content in the Liquid Glass layer. To reinforce the separation, you can extend content beneath
> the sidebar either by letting it horizontally scroll or by applying a *background extension effect*. A
> background extension effect mirrors adjacent content to give the impression of stretching it under the
> sidebar."
> — `[HIG]` Sidebars, https://developer.apple.com/design/human-interface-guidelines/sidebars

> "Liquid Glass appears more opaque in larger elements like sidebars to preserve legibility over complex
> backgrounds and accommodate richer content on the material's surface."
> — `[HIG]` Color, https://developer.apple.com/design/human-interface-guidelines/color

**Tab bars (float, peek-through, minimize on scroll):**

> "A tab bar floats above content at the bottom of the screen. Its items rest on a Liquid Glass
> background that allows content beneath to peek through."
> — `[HIG]` Tab bars, https://developer.apple.com/design/human-interface-guidelines/tab-bars

> "**Choose whether to automatically minimize your tab bar in iOS.** Tab bars can help elevate the
> underlying content by receding when a person scrolls up or down. … The tab bar expands when a person
> scrolls in the opposite direction."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

**Sheets / action sheets / popovers (adopt glass; half-sheet → more opaque when full height):**

> "Modal views like sheets and action sheets adopt Liquid Glass. sheets feature an increased corner
> radius, and **half sheets are inset from the edge of the display to allow content to peek through from
> beneath them. When a half sheet expands to full height, it transitions to a more opaque appearance to
> help maintain focus on the task.** … **Audit the backgrounds of sheets and popovers.** Check whether you
> add a visual effect view to your popover's content view, and remove those custom background views to
> provide a consistent experience with other sheets across the system."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "An action sheet originates from the element that initiates the action, instead of from the bottom edge
> of the display. When active, an action sheet also lets people interact with other parts of the
> interface."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

**Control Center / Top Shelf (tvOS) and system surfaces use glass throughout:**

> "In tvOS, Liquid Glass appears throughout navigation elements and system experiences such as Top Shelf
> and Control Center. Certain interface elements, like image views and buttons, adopt Liquid Glass when
> they gain focus."
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

**Menus:**

> "menus have a refreshed look across platforms. They adopt Liquid Glass, and menu items for common
> actions use icons to help people quickly scan and identify those actions."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

---

## 5. Accessibility — Reduce Transparency / Increase Contrast / Reduce Motion

> "**Increased contrast** makes elements predominantly black or white and highlights them with a
> contrasting border and **Reduced Motion** decreases the intensity of some effects and disables any
> elastic properties for the material."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "The appearance of these variants can differ in response to certain system settings, like if people
> choose a preferred look for Liquid Glass in their device's settings, or **turn on accessibility settings
> that reduce transparency or increase contrast in the interface.**"
> — `[HIG]` Materials, https://developer.apple.com/design/human-interface-guidelines/materials

> "**Test your interface with a variety of display and accessibility settings.** Translucency and fluid
> morphing animations contribute to the look and feel of Liquid Glass, but can adapt to people's needs.
> For example, people can … turn on accessibility settings that **reduce transparency or motion** in the
> interface. **These settings can remove or modify certain effects.** If you use standard components from
> system frameworks, this experience adapts automatically. **Ensure you test your app's custom elements,
> colors, and animations** with different configurations of these settings."
> — `[DOC]` Adopting Liquid Glass, https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass

> "When this setting [Reduce Motion] is active, ensure your app or game responds by **reducing automatic
> and repetitive animations, including zooming, scaling, and peripheral motion.**"
> — `[HIG]` Accessibility, https://developer.apple.com/design/human-interface-guidelines/accessibility

**Parity takeaway:** glass effects are NOT load-bearing for legibility — under Reduce Transparency the
material falls back to (near-)opaque; under Increase Contrast elements go predominantly black/white with
a contrasting border; under Reduce Motion the elastic/morph behavior is disabled. A parity build must
honor `prefers-reduced-transparency`, `prefers-contrast`, and `prefers-reduced-motion` (or the platform
equivalents) and stay fully legible/operable when glass is stripped.

---

## 6. Specular / edge highlight · refraction (lensing) · adaptive tint

**Lensing (the defining optic) + specular highlights:**

> "The primary way Liquid Glass visually defines itself is through something called **Lensing.** … the
> warping and bending of light of a transparent object communicates to us its presence, its motion, and
> form. Liquid Glass uses these instinctive visual cues to provide separation and communicate layering …
> while letting content shine [through]."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "First, the **highlights layer.** Liquid Glass lives inside an environment that behaves like the world
> around us. **Light sources inside of this environment shine on the material producing highlights that
> respond to geometry** just as you'd expect. On interactions, such as locking and unlocking your phone,
> **these lights move in space, causing light to travel around the material, defining its silhouette.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "It casts **deeper, richer shadows, has more pronounced lensing and refraction effects, and a softer
> scattering of light.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "Liquid Glass is a material that **blurs content behind it, reflects color and light of surrounding
> content, and reacts to touch and pointer interactions in real time.**"
> — `[DOC]` Applying Liquid Glass to custom views, https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views

**Adaptive tint + dark/light adaptation:**

> "By default, Liquid Glass has **no inherent color, and instead takes on colors from the content directly
> behind it.** You can apply color to some Liquid Glass elements, giving them the appearance of colored or
> stained glass. This is useful for drawing emphasis to a specific control, like a primary call to
> action … For smaller elements like toolbars and tab bars, **the system can adapt Liquid Glass between a
> light and dark appearance in response to the underlying content.** By default, symbols and text on these
> elements follow a monochromatic color scheme, **becoming darker when the underlying content is light,
> and lighter when it's dark.**"
> — `[HIG]` Color, https://developer.apple.com/design/human-interface-guidelines/color

> "**Apply color sparingly to the Liquid Glass material** … reserve it for elements that truly benefit
> from emphasis, such as status indicators or primary actions. **To emphasize primary actions, apply color
> to the background rather than to symbols or text.** … Refrain from adding color to the background of
> multiple controls."
> — `[HIG]` Color, https://developer.apple.com/design/human-interface-guidelines/color

> "Tinting should only be used to bring emphasis to primary elements and actions in the UI. **Avoid
> tinting all your elements. When every element is tinted, nothing stands out** … If you want to imbue
> color into your app, do it in the content layer instead."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "Selecting a color **generates a range of tones that are mapped to content brightness underneath the
> tinted element.**"
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Adaptive legibility / dynamic range while scrolling:**

> "The amount of tint and the dynamic range shift to always ensure buttons remain legible, while letting
> as much of the content through as possible." … "When darker content scrolls under, triggering the glass
> itself to transition to its dark style, the effect intelligently switches to apply a subtle dimming
> instead, again ensuring contrast and legibility."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

> "Instead of fading, Liquid Glass objects **materialize in and out by gradually modulating the light
> bending and lensing,** ensuring a graceful transition that preserves the optical integrity of the
> material."
> — `[WWDC]` Meet Liquid Glass (219), https://developer.apple.com/videos/play/wwdc2025/219/

**Parity takeaway:** the look is (1) a blur of what's behind, (2) **lensing/refraction at the edges**
(light bending — the silhouette read), (3) a moving **specular highlight** that tracks geometry, and (4)
**adaptive tint** — glass is colorless by default and pulls color from content; light/dark flips with the
underlying brightness; intentional tint is a *background* color on primary actions only, tone-mapped to
the content brightness underneath. Edge highlight + lensing are the cheapest highest-value cues to match.

---

## Newsroom framing (apple.com) — for vocabulary parity

Apple's own product framing for the design (use for naming/positioning, not as a spec):
- Page: "Apple introduces a delightful and elegant new software design",
  https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/
- Describes Liquid Glass as "a new translucent material … that … reflects and refracts its surroundings,
  while dynamically transforming to help bring greater focus to content." Variants shown: default
  (light), dark, **clear** and **tinted** Home Screen looks; Icon Composer for layered, dynamic icons.

---

## Source index (all Apple-authentic)

| Source | URL | Local extract |
|---|---|---|
| HIG — Materials | https://developer.apple.com/design/human-interface-guidelines/materials | `lg_text_lg_data_materials.md` |
| HIG — Color | https://developer.apple.com/design/human-interface-guidelines/color | `lg_text_lg_data_comp_color.md` |
| HIG — Toolbars | https://developer.apple.com/design/human-interface-guidelines/toolbars | `lg_text_lg_data_comp_toolbars.md` |
| HIG — Tab bars | https://developer.apple.com/design/human-interface-guidelines/tab-bars | `lg_text_lg_data_comp_tab-bars.md` |
| HIG — Sidebars | https://developer.apple.com/design/human-interface-guidelines/sidebars | `lg_text_lg_data_comp_sidebars.md` |
| HIG — Sheets | https://developer.apple.com/design/human-interface-guidelines/sheets | `lg_text_lg_data_comp_sheets.md` |
| HIG — Popovers | https://developer.apple.com/design/human-interface-guidelines/popovers | `lg_text_lg_data_comp_popovers.md` |
| HIG — Menus | https://developer.apple.com/design/human-interface-guidelines/menus | `lg_text_lg_data_comp_menus.md` |
| HIG — Buttons | https://developer.apple.com/design/human-interface-guidelines/buttons | `lg_text_lg_data_comp_buttons.md` |
| HIG — Accessibility | https://developer.apple.com/design/human-interface-guidelines/accessibility | `lg_text_lg_data_comp_accessibility.md` |
| HIG — Dark Mode | https://developer.apple.com/design/human-interface-guidelines/dark-mode | `lg_text_lg_data_comp_dark-mode.md` |
| HIG — Motion | https://developer.apple.com/design/human-interface-guidelines/motion | `lg_text_lg_data_comp_motion.md` |
| HIG — Layout | https://developer.apple.com/design/human-interface-guidelines/layout | `lg_text_lg_data_layout.md` |
| DOC — Liquid Glass (technology overview) | https://developer.apple.com/documentation/technologyoverviews/liquid-glass | `lg_text_lg_data_techoverview_liquidglass.md` |
| DOC — Adopting Liquid Glass | https://developer.apple.com/documentation/technologyoverviews/adopting-liquid-glass | `lg_text_lg_data_adopting_liquidglass.md` |
| DOC — Applying Liquid Glass to custom views (SwiftUI) | https://developer.apple.com/documentation/SwiftUI/Applying-Liquid-Glass-to-custom-views | `lg_text_applying_lg_custom.md` |
| DOC — Landmarks: Building an app with Liquid Glass | https://developer.apple.com/documentation/SwiftUI/Landmarks-Building-an-app-with-Liquid-Glass | `lg_text_landmarks_app.md` |
| WWDC25 219 — Meet Liquid Glass | https://developer.apple.com/videos/play/wwdc2025/219/ | `lg_wwdc_219_transcript.md` |
| WWDC25 356 — Get to know the new design system | https://developer.apple.com/videos/play/wwdc2025/356/ | `lg_wwdc_356_transcript.md` |
| NR — Newsroom: new software design | https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/ | `lg_newsroom_page.html` |

**Proxy-blocked sources:** none. Two HIG component paths returned 404 at the `components/<name>` prefix
(`components/toolbars`, `components/sidebars`) — these were not policy denials; the pages live at the
root path (`/toolbars`, `/sidebars`) and were fetched successfully there. `action-buttons` and
`controls-and-selections` 404'd (no such HIG page slug). No 403/405/407 proxy denials were encountered.
