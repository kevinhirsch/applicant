# Apple HIG Corpus Digest — Pages A–M

Distilled operating knowledge for the Apple Genius. Source pages: Apple Human Interface Guidelines (developer.apple.com), as vendored in `docs/design/hig/`. Each entry lists the file, source URL, and its concrete rules with Apple's exact figures/terms preserved. Quotes are marked; nothing is invented. Where a page defers to another page for numbers, that's noted.

26 pages covered: accessibility, action-sheets, activity-rings, activity-views, alerts, boxes, branding, buttons, color, color-wells, dark-mode, disclosure-controls, edit-menus, feedback, gauges, icons, inclusion, launching, layout, lists-and-tables, loading, managing-accounts, materials, menus, modality, motion.

---

## accessibility.md
Source: https://developer.apple.com/design/human-interface-guidelines/accessibility

- Accessible interface = Intuitive, Perceivable, Adaptable. Don't rely on any single method (sight/hearing/speech/touch) to convey information.
- Support text enlargement of at least **200 percent** (or **140 percent** in watchOS). Adopt Dynamic Type.
- Default / minimum type sizes per platform: iOS/iPadOS **17 pt / 11 pt**; macOS **13 pt / 10 pt**; tvOS **29 pt / 23 pt**; visionOS **17 pt / 12 pt**; watchOS **16 pt / 12 pt**.
- Color contrast (WCAG Level AA, used by Accessibility Inspector): text up to 17 pt (all weights) → **4.5:1**; 18 pt (all weights) → **3:1**; any size Bold → **3:1**.
- Prefer system-defined colors (they have accessible variants that adapt to Increase Contrast / light-dark). Convey information with more than color alone (red-green, blue-orange pairings are hard for color-blind users).
- **Control sizes (default / minimum):** iOS/iPadOS **44x44 pt / 28x28 pt**; macOS **28x28 pt / 20x20 pt**; tvOS **66x66 pt / 56x56 pt**; visionOS **60x60 pt / 28x28 pt**; watchOS **44x44 pt / 28x28 pt**.
- Spacing is as important as size: ~**12 points** of padding around elements with a bezel; ~**24 points** around visible edges of elements without a bezel.
- Prefer simplest gesture possible; offer alternatives to gestures (e.g. a button alongside a swipe). Support Voice Control, Full Keyboard Access, Switch Control, VoiceOver, AssistiveTouch, Pointer Control.
- Cognitive: minimize time-boxed / auto-dismiss-on-timer elements; prefer explicit dismissal. Don't autoplay audio/video without controls. Respect Reduce Motion (tighten springs, avoid z-axis depth animation, replace x/y/z transitions with fades, avoid animating into/out of blurs). Respect Dim Flashing Lights.
- Assistive Access: remove noncritical workflows, one interaction per screen, confirm twice for hard-to-recover actions.

## action-sheets.md
Source: https://developer.apple.com/design/human-interface-guidelines/action-sheets

- An action sheet is a modal view presenting choices related to an action people initiate. Use an action sheet — not an alert, not a menu — for choices tied to an intentional action.
- Use sparingly (they interrupt). Keep titles to a single line. Provide a message only if necessary.
- Cancel button at the bottom of the sheet (upper-left corner in watchOS). Place destructive choices at the **top** using the destructive style (most noticeable).
- iOS/iPadOS: avoid letting an action sheet scroll (harder to choose without inadvertently tapping).
- watchOS button styles: Default, Destructive, Cancel. **Avoid more than four buttons total including Cancel** (aim for no more than three additional choices).
- Not supported in visionOS.

## activity-rings.md
Source: https://developer.apple.com/design/human-interface-guidelines/activity-rings

- Rings show Move, Exercise, Stand only. watchOS always shows three rings; iOS shows one Move ring or all three if Apple Watch paired.
- Never change ring colors/opacity/filters. Always display on a **black background**. Prefer enclosing in a circle (adjust corner radius, not a circular mask). Keep black background visible around outermost ring.
- Label/value colors (RGB): **Move R250 G17 B79**; **Exercise R166 G255 B0**; **Stand R0 G255 B246**.
- Minimum outer margin ≥ the distance between rings. Don't use for decoration, branding, app icon, marketing, or multi-person data. Don't send notifications duplicating Activity app info.
- Not supported in macOS, tvOS, visionOS.

## activity-views.md
Source: https://developer.apple.com/design/human-interface-guidelines/activity-views

- Activity view = "share sheet"; appears as sheet or popover. Revealed via the Share/Action button. App-specific actions listed before system actions by default.
- Don't duplicate system actions (e.g. a second Print); if similar, give a custom title like "Print Transaction."
- Custom interface icon: center it in an area measuring about **70x70 pixels**.
- Succinct verb/verb-phrase titles; long titles wrap and may truncate.
- Streamline extensions (task in a few steps). Avoid placing a modal view above your extension. macOS has no activity view but supports share/action app extensions.
- Not supported in macOS, tvOS, watchOS.

## alerts.md
Source: https://developer.apple.com/design/human-interface-guidelines/alerts

- Alert = modal view for critical, ideally actionable info. Use sparingly. Avoid alerts that are merely informational, for common undoable destructive actions, or at app startup.
- Content: title + optional informative text + **up to three buttons**. iOS/iPadOS/macOS/visionOS alerts can include a text field; macOS/visionOS can include an icon and accessory view; macOS can add a suppression checkbox and Help button.
- Title: complete but specific; avoid "Error"/"Error 329347 occurred"; avoid titles wrapping to more than two lines. Sentence = sentence-style caps + ending punctuation; fragment = title-style caps + no punctuation.
- Buttons: one- or two-word titles, verbs/verb phrases. "OK" only in purely informational alerts (avoid Yes/No). Always title a cancel button "Cancel."
- Placement: default/most-likely button on **trailing side of a row or top of a stack**; Cancel on **leading side of a row or bottom of a stack**. Don't make Cancel the default; to discourage reflexive Return-dismiss, make no button default. Single-button default → use "Done," not "Cancel."
- Destructive style only for a destructive action the person didn't deliberately choose. Cancel via Esc / Command-Period, Home Screen (iOS/iPadOS), Menu on remote (tvOS).
- macOS: use caution symbol (`exclamationmark.triangle`) sparingly. visionOS accessory view: max height **154 pt**, **16-pt corner radius**.

## boxes.md
Source: https://developer.apple.com/design/human-interface-guidelines/boxes

- A box visually groups related info via a border or background color; can include a title.
- Keep a box relatively small vs its containing view (large boxes stop communicating separation). Avoid nested boxes; use padding/alignment for subgroups.
- Title: brief phrase, sentence-style caps, no ending punctuation (except in a settings pane, where you append a colon).
- iOS/iPadOS use secondary and tertiary background colors in boxes. macOS displays a box's title above it. Not supported in tvOS or watchOS.

## branding.md
Source: https://developer.apple.com/design/human-interface-guidelines/branding

- Express brand via app icon, voice/tone, an optional accent color, and optional custom font (must stay legible at all sizes, support bold text / larger type; consider custom font for headlines, system font for body/captions).
- **Branding always defers to content.** Incorporate branding in refined, unobtrusive ways. Don't display your logo throughout unless essential for context.
- Use standard patterns/locations and standard symbols even in stylized UIs.
- Don't use a launch screen as a branding opportunity; consider a welcome/onboarding screen instead.

## buttons.md
Source: https://developer.apple.com/design/human-interface-guidelines/buttons

- Button = Style + Content (symbol/text/both) + Role.
- **Hit region at least 44x44 pt (visionOS 60x60 pt).** Always include a press state for custom buttons.
- Use a prominent style (system applies accent color to background) for the most likely action; keep to **one or two prominent buttons per view**. Use style — not size — to signal the preferred choice; same-size buttons signal a coherent set.
- Roles: Normal, Primary (default; uses accent color; responds to Return; auto-closes temporary views), Cancel, Destructive (uses system red). Don't assign Primary to a destructive action.
- Text buttons: title-style capitalization, start with a verb (e.g. "Add to Cart").
- macOS button types: push buttons (append trailing ellipsis when they open another window/view/app; support spring loading); square/gradient buttons (symbols not text, in a view not the window frame); help buttons (circular, question mark, ≤ one per window, in a view not window frame); image buttons (~**10 pixels** padding between image and button edges, label below).
- visionOS: three shapes (circle for icon-only, rounded-rectangle/capsule for text, capsule for icon+text). Button sizes: Mini **28 pt**, Small **32 pt**, Regular **44 pt**, Large **52 pt**, Extra large **64 pt**. Place button centers **at least 60 pts apart**; add **4 pts** padding if buttons ≥ 60 pt to avoid hover overlap. Prefer circular/capsule (eyes drawn to corners). Don't use white background + black text/icons (system reserves this for toggled state). Use `thin` material on glass.
- watchOS: capsule shape inline; prefer full-width buttons for primary actions; use a toolbar for corner buttons (gets Liquid Glass).

## color.md
Source: https://developer.apple.com/design/human-interface-guidelines/color

- Don't use the same color to mean different things. Make colors work in light, dark, and increased-contrast contexts; supply light + dark + increased-contrast variants for custom colors (needed even in a single-appearance app, for Liquid Glass adaptivity).
- **Don't hard-code system color values** (they fluctuate per release); use APIs like `Color`. Don't redefine semantic meanings of dynamic system colors (e.g. don't use `separator` as text color).
- **Liquid Glass color:** by default Liquid Glass has no inherent color and takes color from content behind it. Apply color **sparingly**, reserved for emphasis (status indicators, primary actions). To emphasize primary actions, apply color to the **background**, not to symbols/text. Don't add color to the background of multiple controls. For toolbars/tab bars over colorful content, prefer a monochromatic appearance. Larger elements (sidebars) render more opaque for legibility; small elements (toolbars, tab bars) adapt light/dark to underlying content.
- Foreground dynamic colors (iOS): label, secondaryLabel, tertiaryLabel, quaternaryLabel, placeholderText, separator, opaqueSeparator, link. Backgrounds have primary/secondary/tertiary variants in both `system` and `grouped` sets.
- Color management: color spaces sRGB and Display P3 (a.k.a. gamuts). Apply color profiles to images; sRGB is accurate on most displays. Wide color = P3 at **16 bits per pixel (per channel)**, export PNG.
- Full system-color RGB table (light/dark/increased-contrast) present in file, e.g. **Red light R255 G56 B60 / dark R255 G66 B69**; **Blue light R0 G136 B255 / dark R0 G145 B255**. iOS system grays (systemGray…systemGray6) tabulated. visionOS uses the default dark values.

## color-wells.md
Source: https://developer.apple.com/design/human-interface-guidelines/color-wells

- A color well shows a color picker (system-provided or custom) on tap/click. Prefer the system picker for a familiar, cross-platform experience and shared saved colors.
- macOS: color well highlights when active, updates to show the chosen color, and supports drag-and-drop of colors. Not supported in tvOS or watchOS.

## dark-mode.md
Source: https://developer.apple.com/design/human-interface-guidelines/dark-mode

- Dark Mode = systemwide dark palette for low-light; respect the user's systemwide choice. **Avoid an app-specific appearance setting.** Support light, dark, and Auto.
- Dark palette isn't a straight inversion — some colors invert, some don't. Use semantic/adaptive colors; add Color Set assets with bright + dim variants; avoid hard-coded colors.
- Contrast: **no lower than 4.5:1**; for custom foreground/background strive for **7:1**, especially small text. Soften white backgrounds in content images to prevent glowing.
- Use SF Symbols (auto-adapt). Design separate light/dark interface icons where needed. Use system label colors (primary/secondary/tertiary/quaternary) and system views for text.
- iOS/iPadOS Dark Mode uses two background sets — **base** (dimmer, recedes) and **elevated** (brighter, advances, used for foreground like popovers/modal sheets and multitasking separation). Prefer system background colors.
- macOS: graphite accent → **desktop tinting**; add transparency only to custom components with a visible background/bezel and only in a neutral (non-color) state.
- Not supported in visionOS or watchOS.

## disclosure-controls.md
Source: https://developer.apple.com/design/human-interface-guidelines/disclosure-controls

- Use to hide details until relevant; keep most-used controls at top of the hierarchy, advanced options hidden by default.
- **Disclosure triangle:** points inward from the leading edge when collapsed, down when expanded. Provide a descriptive label (e.g. "Advanced Options").
- **Disclosure button:** points down when collapsed, up when expanded. Place near the content it controls; **use no more than one disclosure button per view.**
- Not supported in tvOS or watchOS.

## edit-menus.md
Source: https://developer.apple.com/design/human-interface-guidelines/edit-menus

- Edit menu = commands on selected content (Copy, Select, Translate, Look Up, plus data-detected actions like "Get directions").
- Prefer the system-provided edit menu; let people reveal it with system-defined interactions (touch and hold, pinch and hold in visionOS, secondary click). Don't invent custom reveal gestures.
- Remove/dim commands that don't apply (no Copy/Cut with nothing selected; no Paste with nothing to paste). List custom commands near related system ones; don't overwhelm.
- Let people copy noneditable content text but not control labels. Support undo/redo. Avoid redundant controls duplicating edit-menu functions. Differentiate Delete vs Cut (Cut copies to pasteboard first).
- iOS compact horizontal style (touch) vs vertical/context-menu style (keyboard/pointer) — support both; you can adjust menu position but not its shape/pointer.
- Not supported in tvOS or watchOS.

## feedback.md
Source: https://developer.apple.com/design/human-interface-guidelines/feedback

- Match significance to delivery: passive/status info integrated near items; interrupting alerts only for critical, ideally actionable info.
- Make all feedback accessible — combine color, text, sound, and haptics so it works when muted, looking away, or using VoiceOver.
- Warn only for unexpected, irreversible data loss; don't warn for expected data loss (e.g. deleting a file). Confirm only sufficiently important completed actions (e.g. Apple Pay). Show when a command can't be carried out and why.
- watchOS: avoid indeterminate/loading progress indicators; reassure that a notification will arrive on completion.

## gauges.md
Source: https://developer.apple.com/design/human-interface-guidelines/gauges

- A gauge shows a numeric value within a range on a circular or linear path. Standard style = indicator at the value; capacity style = fill stopping at the value. `accessory` variant echoes watchOS complications (good for Lock Screen widgets).
- Write succinct labels for current value + both endpoints (VoiceOver reads visible labels). Consider a gradient fill to communicate purpose (e.g. red→blue for hot→cold).
- macOS also has a **level indicator** (capacity/rating/relevance). Default capacity fill color is **green**; use continuous style for large ranges; use tiered state for multi-color sequences.
- Not supported in tvOS.

## icons.md
Source: https://developer.apple.com/design/human-interface-guidelines/icons

- Interface icon (glyph) = simplified single concept; distinct from rich app icons. Icons/symbols use black + clear to define shape; system tints the black areas.
- Keep highly simplified and recognizable; maintain consistent size, detail, stroke thickness/weight, and perspective across all icons. Generally match icon weight to adjacent text.
- Use **optical** centering (not just geometric) for asymmetric icons; bake adjustments as padding. Provide a selected state only if not in standard components (toolbars/tab bars/buttons auto-update selected appearance).
- Use vector format (**PDF or SVG**) for custom interface icons (system scales for high-res); PNG (used for app icons with shading/texture) needs multiple resolutions. Provide alternative text labels for VoiceOver. Use inclusive, gender-neutral imagery; localize/flip text-bearing icons for RTL. Avoid replicas of Apple hardware.
- Standard action → SF Symbol mappings include: Cut `scissors`, Copy `document.on.document`, Paste `document.on.clipboard`, Done `checkmark`, Cancel/Deselect `xmark`, Delete `trash`, Undo `arrow.uturn.backward`, Redo `arrow.uturn.forward`, Compose `square.and.pencil`, Add `plus`, More `ellipsis`, Share `square.and.arrow.up`, Print `printer`, Search `magnifyingglass`, Filter `line.3.horizontal.decrease`, Account `person.crop.circle`, Bold `bold`, Italic `italic`, Underline `underline`.
- macOS document icons: paper with top-right corner folded down; can display as small as **16x16 px**; keep important content out of the top-right corner. Center image = **half** the canvas size; margin ~**10%** of canvas, image occupies ~**80%** (e.g. ~205x205 px within a 256x256 px canvas). Background/center-image sizes tabulated (16→512 px, @1x/@2x).

## inclusion.md
Source: https://developer.apple.com/design/human-interface-guidelines/inclusion

- Put people first: respectful communication + content everyone can access and understand; it's iterative.
- Welcoming language: plain, direct, respectful copy. Use "you"/"your" to address people; reserve "we"/"our" for your company. Define technical terms. Replace colloquialisms (e.g. avoid "peanut gallery," "grandfathered in") and be cautious with humor (hard to translate).
- Be approachable: clear interface + an onboarding path that lets others skip ahead.
- Gender identity: avoid unnecessary gender references and singular gendered pronouns; use nongendered images/SF Symbols; offer inclusive options (nonbinary, self-identify, decline to state) only if you truly need gender.
- Portray human diversity; avoid stereotypes and context-specific assumptions (e.g. security questions based on college/first car). Support accessibility features (VoiceOver, Display Accommodations, closed captioning, Switch Control, Speak Screen). Take a people-first approach when writing about disability.
- Prepare for internationalization/localization; note color meanings differ by culture (e.g. white = death/grief vs purity/peace).

## launching.md
Source: https://developer.apple.com/design/human-interface-guidelines/launching

- **Launch instantly** (people don't want to wait more than a couple of seconds). Provide a launch screen where required (iOS/iPadOS/tvOS); macOS/visionOS/watchOS don't require one. Restore previous state on restart.
- **Launch screen is not branding / not artistic / not a splash screen.** Design it nearly identical to the first screen (to avoid a flash); if the app shows a solid color first, the launch screen is only that color. Match current orientation and appearance mode. Avoid text (won't be localized). No logos/advertising unless a fixed part of the first screen.
- Splash screen (optional) belongs at the start of onboarding.
- iOS/iPadOS: launch in the device's current orientation (don't tell people to rotate).

## layout.md
Source: https://developer.apple.com/design/human-interface-guidelines/layout

- Group related items (negative space, background shapes, colors, materials, separators). Give essential info sufficient space. **Extend content to fill the screen/window** — backgrounds and scrollable layouts reach all edges; controls (sidebars, tab bars) sit **on top of** content, not on the same plane. Use a background extension view where content doesn't span the window.
- Visual hierarchy: differentiate controls from content using the **Liquid Glass** material; use a **scroll edge effect** for the content↔control transition rather than a background. Place important items near the top and leading side (reading order top→bottom, leading→trailing; account for RTL). Align components; use progressive disclosure.
- Respect system-defined **safe areas**, margins, and layout guides. Safe area = region not covered by toolbar/tab bar/other views, avoiding Dynamic Island and camera housing. Adapt to size classes: **regular** (larger screen / landscape) vs **compact** (smaller screen / portrait).
- iOS: support portrait + landscape; **avoid full-width buttons** (respect system margins); hide the status bar only when it adds value.
- iPadOS: windows resize to a minimum width/height; defer switching to compact view as long as possible; test at halves/thirds/quadrants; consider a convertible (`sidebarAdaptable`) tab bar.
- macOS: avoid controls/critical info at the bottom of a window; avoid content in the camera housing.
- tvOS: inset primary content **60 points top/bottom, 80 points sides**; use consistent spacing; account for focus growth.
- visionOS: center important content; keep content within window bounds (window controls sit just outside in the XY plane — Share above, resize/move/close below); use ornaments for extra controls; place button centers **at least 60 points apart**.
- watchOS: extend content edge to edge (bezel is natural padding); no more than **two or three** side-by-side controls (≤3 glyph buttons or ≤2 text buttons in a row).
- Extensive device screen-dimension and size-class tables included (pt + px @2x/@3x).

## lists-and-tables.md
Source: https://developer.apple.com/design/human-interface-guidelines/lists-and-tables

- Prefer text in lists/tables (row format is good for scanning/reading); use a collection for widely varying sizes or many images.
- Let people edit (reorder even if not add/remove); iOS/iPadOS require entering an edit mode to select. Provide selection feedback: persistent highlight for navigation paths; brief highlight + checkmark for option selection.
- Keep item text succinct; a mid-string ellipsis can preserve beginning + end. Multicolumn headings = nouns/short noun phrases, title-style caps, no ending punctuation.
- Styles: grouped (iOS/iPadOS: headers/footers + space), elliptical (watchOS), bordered/alternating rows (macOS).
- iOS/iPadOS/visionOS: use an info/detail-disclosure button only to reveal more info (not for navigation — use a disclosure indicator to drill in). Don't add an index to a table with trailing-edge controls (both live on the trailing side).
- macOS: click column headings to sort (re-click to reverse); resizable columns; alternating row colors; use an outline view (disclosure triangles) for hierarchy.

## loading.md
Source: https://developer.apple.com/design/human-interface-guidelines/loading

- Best loading finishes before people notice it. **Show something as soon as possible** (placeholder text/graphics/animations, replaced as content arrives) so absence of content isn't read as a problem.
- Let people do other things while content loads in the background. For unavoidably long loads, show something interesting (hints/tips/new features). Download large assets in the background (Background Assets framework).
- Use a **determinate** progress indicator when you know how long loading takes, **indeterminate** when you don't.
- watchOS: avoid loading indicators where possible; if content needs a second or two, a loading indicator beats a blank screen.

## managing-accounts.md
Source: https://developer.apple.com/design/human-interface-guidelines/managing-accounts

- Require an account only if core functionality needs it. Consider Sign in with Apple. **Delay sign-in as long as possible** (people abandon apps forced to sign in first). Explain the benefits of an account in the sign-in view.
- If not using Sign in with Apple, prefer a **passkey** (no password to create/enter); if still using passwords, add two-factor auth.
- Always name the auth method ("Sign In with Face ID," not "Sign In"); only reference methods available on the current device. Don't offer an app-specific setting to opt into biometric auth (it's a system-level setting). Avoid the term "passcode" for account auth.
- Account deletion: if you let people create an account you must let them **delete** it (not just deactivate); provide a clear in-app path or a direct link (don't bury in Privacy Policy). Keep in-app and web deletion equally simple; tell people when deletion completes and notify when finished; can offer scheduled deletion but also offer immediate. Explain subscription/billing implications.

## materials.md
Source: https://developer.apple.com/design/human-interface-guidelines/materials

- A material separates foreground (text/controls) from background (content/color), establishing hierarchy. Two types: **Liquid Glass** (functional layer for controls/navigation) and **standard materials** (differentiation within the content layer).
- **Don't use Liquid Glass in the content layer** (use standard materials there); exception: transient interactive elements like sliders/toggles take on Liquid Glass when activated. Use Liquid Glass **sparingly** — limit to the most important functional elements.
- Liquid Glass variants: **`regular`** (blurs + adjusts luminosity to keep foreground legible; use for text-heavy components — alerts, sidebars, popovers — or when background hurts legibility; most system components use it) and **`clear`** (highly translucent; for components over visually rich media backgrounds). With `clear` over bright content, add a **dark dimming layer of 35% opacity**; skip the dimming layer if the content is dark enough or AVKit provides its own.
- **iOS/iPadOS standard materials (4 tiers):** **ultra-thin, thin, regular (default), thick.** Thicker/more opaque = better contrast for fine text; thinner/more translucent = more background context. Use vibrant colors on top of materials for legibility. Avoid quaternary label vibrancy on `thin`/`ultraThin` (contrast too low).
- tvOS material→use mapping: `ultraThin` (full-screen, light scheme), `thin` (overlay, light), `regular` (overlay), `thick` (overlay, dark scheme).
- visionOS uses an adaptive system `glass` material (no separate Dark Mode; glass adapts to background luminance). Prefer translucency over opaque colors. Three vibrancy tiers: label, secondaryLabel, tertiaryLabel.

## menus.md
Source: https://developer.apple.com/design/human-interface-guidelines/menus

- A menu reveals menu items (each = a command/option/state). Labels: clear, succinct verb/verb-phrase; **title-style capitalization**; remove articles (a/an/the) to save space; append an ellipsis (…) when the action needs more info; dim (don't remove) unavailable items, but keep the menu itself openable.
- Icons: use standard SF Symbols for common actions; use icons sparingly and with purpose; apply a **uniform treatment across items in a group** (icons for all in a group, or none).
- Organization: list important/frequently-used items first; group logically related items separated by a separator (horizontal line or gap); keep related commands in the same group even at differing importance; watch menu length (split long menus, but user-generated content like History/Bookmarks may be long and scrollable).
- Submenus: use sparingly (consider when a term repeats in >2 items in a group); limit to a **single level**; if a submenu has more than **about five items**, make a new menu; keep the parent openable even when its items are unavailable; prefer submenus over indentation.
- Toggled items: use a changeable label reflecting current state (Show Map ↔ Hide Map); add a verb if ambiguous (Turn HDR On/Off); consider a checkmark for an in-effect attribute; consider a "remove all" item (e.g. Plain).
- iOS/iPadOS layouts: **Small** (top row of four symbol-only items), **Medium** (top row of three symbol+label items), **Large** (default; all items in a list).

## modality.md
Source: https://developer.apple.com/design/human-interface-guidelines/modality

- Modality presents content in a dedicated mode that blocks interaction with the parent view and requires an explicit dismiss. Use only when there's a clear benefit.
- Keep modal tasks simple, short, streamlined; avoid a modal that feels like "an app within your app" (provide a single path through any subviews; avoid buttons mistakable for the dismiss button).
- Use full-screen modal for in-depth content / complex multistep tasks (video, photos, markup, editing).
- Always give an obvious dismiss: iOS/iPadOS/watchOS → button in top toolbar or swipe down; macOS/tvOS → button in the main content view. Confirm before closing if it could lose user-generated content.
- Give the modal a title naming its task. **Dismiss one modal before presenting another** (never show more than one alert at a time, though an alert can appear atop other modals).

## motion.md
Source: https://developer.apple.com/design/human-interface-guidelines/motion

- Add motion purposefully — never for its own sake (gratuitous animation distracts/can cause discomfort). **Make motion optional** and never the only way to convey important info (supplement with haptics/audio).
- Feedback motion should be realistic and follow gestures/expectations (a view revealed by sliding down shouldn't dismiss by sliding sideways). Aim for brevity and precision. Generally avoid adding motion to frequent UI interactions (system already provides subtle animations). Let people cancel motion.
- Games: maintain a consistent frame rate of **30 to 60 fps**; let people customize the visual experience for performance/battery.
- visionOS: avoid motion at the edges of the field of view (peripheral motion is distracting and can cause discomfort); use fades to relocate objects; avoid rotating a virtual world; give a stationary frame of reference; avoid sustained oscillation, especially around **0.2 Hz** (people are very sensitive to it).
- Liquid Glass motion responds more emphatically to direct touch, more subdued via trackpad.

---

## Top rules most relevant to a glass web UI's chrome/controls

1. **Touch targets:** every control needs a hit region of **at least 44x44 pt** (accessibility minimum 28x28 pt); include enough surrounding space — ~12 pt padding around bezeled elements, ~24 pt around unbezeled ones. (accessibility, buttons)
2. **Glass belongs to the chrome, not the content:** put the Liquid Glass material on the functional layer (toolbars, tab bars, sidebars, nav/controls) and use standard materials for content-layer backgrounds; don't put glass in the content layer (exception: transient controls like sliders/toggles glass-up only while active). (materials, layout)
3. **Glass has no inherent color — apply color sparingly and to the background:** to emphasize a primary action, tint the button **background** (accent color), not its label/symbol; don't color the backgrounds of multiple controls; over colorful content prefer monochromatic toolbars/tab bars. (color, buttons, materials)
4. **Pick the glass variant by background:** `regular` (blur + luminosity adjust) for text-heavy chrome (alerts, sidebars, popovers) and legibility-risk backgrounds; `clear` only over rich media — and when `clear` sits over bright content, add a **dark dimming layer at 35% opacity**. (materials)
5. **Contrast is non-negotiable:** meet **4.5:1** for text up to 17 pt and **3:1** for 18 pt / bold; in dark contexts don't drop below **4.5:1**, and strive for **7:1** for custom small text. Convey state with more than color alone. (accessibility, dark-mode, color)
6. **Layer chrome over content and let content run to the edges:** controls sit on top of content (not the same plane); extend backgrounds/scroll areas to all edges; use a **scroll edge effect** for the content↔control transition instead of an opaque bar; respect safe areas/margins. (layout)
7. **Respect the system, not an app toggle:** follow the systemwide light/dark preference (support Auto) with adaptive/semantic colors — no app-specific appearance switch; never hard-code system color values. (dark-mode, color)
8. **Honor Reduce Motion / keep motion optional:** motion is purposeful, brief, cancelable, never the sole information channel; avoid animating blurs and z-axis depth; prefer fades. (motion, accessibility)
9. **Button hierarchy by style, not size:** keep to one or two prominent buttons per view; give the default/most-likely action the Primary role; place default on the trailing side of a row (or top of a stack), Cancel on the leading side (or bottom); never make a destructive action the Primary/default. (buttons, alerts)
10. **Menu/disclosure discipline for chrome:** title-style labels, ellipsis when more input is needed, dim (don't remove) unavailable items, uniform icons per group; disclosure triangle points down when open / inward-leading when closed; at most one disclosure button per view. (menus, disclosure-controls)
