# Corpus Digest — Apple HIG pages N–Z

Distilled operating knowledge from the Apple Human Interface Guidelines pages in
`docs/design/hig/` whose filenames start with letters n–z (26 pages, excluding INDEX.md).
Each entry lists the source page, its URL, and a tight bullet list of concrete rules with
Apple's exact figures and terms preserved. Quotes are marked; nothing invented.

---

## notifications.md
Source: https://developer.apple.com/design/human-interface-guidelines/notifications

- Must get consent before sending any notifications; people then use Settings to pick styles/delivery times.
- Styles: banner/view (Lock Screen, Home Screen, Home View, desktop), badge on app icon, item in Notification Center. Communication notifications use contact images (*avatars*) + group names instead of the app icon.
- Provide concise, informative notifications; avoid multiple notifications for the same thing.
- Use an alert — not a notification — to display an error message.
- Handle notifications gracefully when app is in foreground (increment a badge / subtly insert data), don't show the notification.
- Avoid sensitive/personal/confidential info in a notification.
- Title: title-style capitalization, no ending punctuation. Body/hidden-preview placeholder: sentence-style capitalization (e.g. "Friend request," "New comment").
- Notification actions: up to **four buttons**; short title-case labels; no app name; interface icon shown on the **trailing** side of the action title; prefer nondestructive actions.
- Badge = "small, filled oval containing a number" for unread count only; not for weather/dates/stocks/scores. Reducing count to zero removes all related notifications from Notification Center. Don't mimic a badge with a custom image.
- watchOS: two stages — *short look* and *long look*. Long look default background color: "white with 18% opacity"; system structure = *sash* at top + Dismiss button at bottom; up to **four** custom actions. Double tap runs the first nondestructive action.

## onboarding.md
Source: https://developer.apple.com/design/human-interface-guidelines/onboarding

- Onboarding should be "fast, fun, and optional"; occurs *after* launching completes, not part of launch.
- Teach through interactivity; consider context-specific tips (TipKit) instead of one flow.
- Keep prerequisite flows brief; don't force memorizing a lot of info.
- If a tutorial is offered, make it optional; don't re-show a skipped tutorial on subsequent launches, but keep it findable (help/account/settings).
- Keep content about your app, not the system/device.
- Splash screen: display "just long enough" to absorb at a glance; don't let large downloads block onboarding.
- Avoid licensing details in onboarding (let the App Store show agreements).
- Postpone nonessential setup; provide reasonable default settings. Integrate permission requests into onboarding only if access is needed before functioning. Let people experience the app before ratings/purchase prompts.

## panels.md (macOS only)
Source: https://developer.apple.com/design/human-interface-guidelines/panels

- A panel floats above other windows providing supplementary controls/info for the active window/selection; less prominent than standard windows.
- Use for an *inspector* (updates with selection). An *Info* window (fixed contents) should be a regular window, not a panel.
- Prefer simple adjustment controls (sliders, steppers); avoid controls requiring typing/multi-step selection.
- Title: short noun/noun-phrase, title-style capitalization (e.g. "Fonts," "Colors," "Inspector").
- Bring all panels to front when app activates; hide all panels when app is inactive.
- Don't list panels in the Window menu's documents list; generally don't offer a minimize button.
- HUD-style panel = darker, translucent; use only for media apps, when a standard panel would obscure content, or when no controls needed (except the disclosure triangle). Use color sparingly; keep HUDs small. Not supported iOS/iPadOS/tvOS/visionOS/watchOS.

## pickers.md
Source: https://developer.apple.com/design/human-interface-guidelines/pickers

- Picker = one or more scrollable lists of distinct values. Use for medium-to-long lists; use a pull-down button for short lists, a list/table for very large sets.
- Use predictable, logically ordered values; avoid switching views to show a picker (show below/near the edited field, at window bottom, or in a popover).
- Date picker minute granularity: default 60 values (0–59); optional intervals must divide evenly into 60 (e.g. 0, 15, 30, 45).
- iOS/iPadOS date-picker styles: **Compact, Inline, Wheels, Automatic**. Modes: **Date, Time, Date and time, Countdown timer** (countdown max **23 hours and 59 minutes**; not available in inline/compact).
- macOS: two styles — **textual** and **graphical**.

## pop-up-buttons.md
Source: https://developer.apple.com/design/human-interface-guidelines/pop-up-buttons

- Presents a menu of **mutually exclusive** options; after choosing, menu closes and button can update to show selection.
- Use a **pull-down button** instead if you need: a list of actions, multiple selections, or a submenu.
- Provide a useful default selection; give people a way to predict options without opening (introductory/button label).
- Space-efficient for many choices; can include a **Custom** option + explanatory text below the list. Not supported tvOS/watchOS.

## popovers.md
Source: https://developer.apple.com/design/human-interface-guidelines/popovers

- Transient view above content; expose a small amount of info/functionality (a few related tasks).
- Arrow should point as directly as possible to the revealing element; don't cover that element or essential content.
- Close button (Cancel/Done) only for clarity; otherwise closes on tap/click outside or on selection. For multiple selections, keep open until explicit dismissal / outside tap.
- Always save work when auto-closing a **nonmodal** popover; discard only on explicit Cancel.
- **Show one popover at a time**; never cascade/hierarchy. Nothing displays over a popover except an alert.
- Don't make a popover too big; animate size changes (condensed/expanded).
- Avoid using a popover for a warning — use an alert.
- iOS/iPadOS: avoid popovers in compact views (use a full-screen modal/sheet). macOS: can be **detachable** into a panel; keep appearance changes minimal. Not supported tvOS/watchOS.

## progress-indicators.md
Source: https://developer.apple.com/design/human-interface-guidelines/progress-indicators

- Two types: **Determinate** (well-defined duration) and **Indeterminate** (aka *activity indicator*/*spinner*). Progress bars fill leading→trailing; circular indicators fill clockwise. All are transient.
- Prefer determinate; be accurate — even out the pace (don't show "90 percent … in five seconds and the last 10 percent in 5 minutes").
- Keep indicators moving (stationary = perceived stall). Switch indeterminate→determinate when possible; **don't switch circular ↔ bar** styles.
- Avoid vague descriptions like *loading*/*authenticating*; keep location consistent.
- Offer a **Cancel** button when interruptible; add a **Pause** button when interruption has side effects; use an alert to confirm cancellation that loses progress.
- macOS: indeterminate can be bar or circular; prefer spinner for background/space-constrained tasks; avoid labeling a spinner. iOS refresh control is a specialized hidden activity indicator revealed by drag-down.

## pull-down-buttons.md
Source: https://developer.apple.com/design/human-interface-guidelines/pull-down-buttons

- Menu of items/actions related to the button's purpose; after choosing, menu closes and the action runs. Use a **pop-up button** for mutually exclusive non-command choices.
- Don't hide a view's primary actions in a pull-down button.
- Balance length: list a **minimum of three items** to feel worthwhile; if only 1–2, use buttons/toggles instead; too many slows people down.
- Show a menu title only if it adds meaning. Destructive items use **red text**; choosing one shows an **action sheet (iOS)** or **popover (iPadOS)** to confirm. Interface icon/SF Symbol may follow a label.
- iOS/iPadOS: consider a **More** pull-down button (ellipsis) for less prominent items — weighs convenience vs. discoverability.

## right-to-left.md
Source: https://developer.apple.com/design/human-interface-guidelines/right-to-left

- System UI frameworks flip RTL (Arabic, Hebrew) automatically; only fine-tune if needed.
- Align paragraphs (**three or more lines**) by their language; align 1–2 line blocks to current context. Use consistent alignment for all list items.
- Never reverse digits within a specific number (phone/credit-card/"541"). Reverse the *order* of numerals that show progress/counting; never flip the numerals themselves.
- Flip controls that show progress (sliders, progress indicators) and navigation controls (back/next/previous) in RTL; preserve controls that refer to an actual direction/onscreen area.
- To balance Arabic/Hebrew next to all-caps Latin, "increase the RTL font size by about 2 points."
- Don't flip photos/artwork/logos/universal marks (checkmark); reverse image positions when order is meaningful. Flip interface icons representing text/reading direction or forward/backward motion; don't flip real-world-object icons unless indicating directionality.

## search-fields.md
Source: https://developer.apple.com/design/human-interface-guidelines/search-fields

- A search field = editable text field with a Search icon, a Clear button, and placeholder text.
- Use placeholder text to convey scope; start search immediately as a person types when possible; show suggested/recent search terms; simplify + categorize results.
- **Scope bar** = control to filter/adjust search scope; **token** = selectable/editable visual representation of a search term acting as a filter. Default to a broader scope; pair tokens with suggestions.
- iOS positions: **as a tab** in the tab bar (Standard tab or Button appearance), **in a toolbar** (bottom preferred if room, else top/navigation bar), or **inline** with content.
- iPadOS/macOS: put a search field at the **trailing side of the toolbar** for many uses; at the top of the sidebar for filtering navigation; or as a dedicated sidebar/tab item for discovery. Consider auto-focusing the field (exception: iPad with only a virtual keyboard — leave unfocused).

## searching.md
Source: https://developer.apple.com/design/human-interface-guidelines/searching

- If search is important, give it a primary position; aim for a single searchable location (local search OK for distinct sections).
- Clearly display current scope (placeholder text, scope bar, or title). Provide recent/predictive suggestions.
- Take privacy into account before showing search history; provide a way to clear it.
- Systemwide: make content searchable in **Spotlight** via indexable *metadata*; supply a Spotlight File Importer for custom types; prefer system-provided open/save views; implement a Quick Look generator for custom file types.

## segmented-controls.md
Source: https://developer.apple.com/design/human-interface-guidelines/segmented-controls

- "A linear set of two or more segments, each of which functions as a button." Usually **equal width**. Single choice (all platforms) or single/multiple (macOS); can also be a set of momentary action buttons.
- Use for closely related choices affecting an object/state/view; groups stay grouped regardless of view size.
- **Keep control types consistent** within one control (don't mix selection-state and action segments).
- **Limit segments: no more than about five to seven in a wide interface, no more than about five on iPhone.** Keep segment size consistent.
- Prefer text OR images — not a mix — in a single control; similar content size per segment. Labels: nouns/noun phrases, title-style capitalization.
- iOS/iPadOS: OK to switch closely related subviews; for separate app sections use a **tab bar**. macOS: use a **tab view** (not a segmented control) for main-window view switching; supports spring loading. tvOS: segments select on focus (not click) — avoid nearby focusable elements. Not supported watchOS.

## settings.md
Source: https://developer.apple.com/design/human-interface-guidelines/settings

- Provide defaults that give the best experience to the most people; **minimize the number of settings**.
- Standard open shortcut: **Command-Comma (,)**; games often use Esc.
- Don't ask via settings for info obtainable another way; respect systemwide settings — don't duplicate global options.
- Put general, infrequently changed options in your custom settings area; keep task-specific options in the screens they affect. Add only the most rarely changed options to the system Settings app.
- macOS: settings window has views called **panes** in a **noncustomizable toolbar** that always shows the active button; dim minimize/maximize buttons; update window title to the current pane (or "*App Name* Settings" if single pane); restore the most recently viewed pane; settings item lives in the **App menu** (not toolbar).

## sheets.md
Source: https://developer.apple.com/design/human-interface-guidelines/sheets

- A sheet performs a scoped task related to current context. Always **modal** in macOS/tvOS/visionOS/watchOS; iOS/iPadOS can be modal or **nonmodal**.
- Buttons: **Cancel/Close** (dismiss without saving), **Done** (dismiss after completing/saving), **Back** (previous step — not a dismiss). Placement varies by platform.
- **Display only one sheet at a time**; close the first before showing another.
- **Always pair a Done button with a Cancel or Back button**; "Avoid showing all three buttons — Cancel, Done, and Back — together."
- iOS/iPadOS: Cancel on the **leading edge** of the top toolbar, Done on the **trailing edge**. Resizable sheets use a *grabber* and *detents*: system defines **large** (fully expanded) and **medium** (about half). Include a grabber; support swipe-to-dismiss (confirm with an action sheet if unsaved changes). iPadOS: prefer **page** or **form** sheet styles.
- macOS: cardlike view with rounded corners over a dimmed parent; use a reasonable default size (support resizing when helpful); let people interact with other app windows without dismissing; use a **panel** instead when repeated input/observe-results is needed.

## sidebars.md
Source: https://developer.apple.com/design/human-interface-guidelines/sidebars

- Sidebar on the **leading side** for navigating app areas/top-level collections; needs lots of vertical + horizontal space (use a tab bar when space is limited).
- iOS/iPadOS/macOS: can float in the **Liquid Glass** layer; extend content beneath via horizontal scroll or a **background extension effect** (mirrors adjacent content under the sidebar).
- Let people customize contents; group hierarchy with disclosure controls; use SF Symbols.
- Let people hide/show the sidebar (iPadOS edge swipe; macOS Show/Hide Sidebar in View menu); **avoid hiding by default**.
- **In general, show no more than two levels of hierarchy** (deeper → use a split view with a content list). Use succinct group labels.
- Sidebar icons default to the **app accent color** (macOS honors user's system accent); use fixed colors sparingly for meaning (e.g. Mail VIP = yellow). macOS sidebar sizes: **small, medium, or large** (user-settable in General settings); avoid critical info/actions at the bottom.

## sliders.md
Source: https://developer.apple.com/design/human-interface-guidelines/sliders

- Horizontal track with a **thumb**; the track between minimum and thumb fills with color; optional left/right icons for min/max meaning.
- Familiar directions: **min on leading side, max on trailing** (horizontal); min at bottom, max at top (vertical).
- Supplement wide-range sliders with a **text field + stepper** for exact values.
- iOS/iPadOS: **don't use a slider for audio volume** — use a volume view.
- macOS: can include **tick marks**; linear thumb is a "narrow lozenge shape," circular thumb is a small circle. Use circular sliders for repeating/continuous values (e.g. 0–360 degrees; 1440 degrees = four spins). Labels: sentence-style capitalization ending with a colon. Often label only min/max; provide a tooltip showing the thumb value. visionOS: prefer horizontal sliders. Not supported tvOS.

## split-views.md
Source: https://developer.apple.com/design/human-interface-guidelines/split-views

- Manages multiple adjacent panes; selecting an item in the **primary** pane shows contents in the **secondary** (optional **tertiary**) pane; commonly hosts a sidebar for navigation.
- **Persistently highlight the current selection** in each pane leading to detail; consider drag-and-drop between panes.
- iOS: prefer a split view in a **regular** (not compact) environment. iPadOS: two or three vertical panes; account for narrow/compact/intermediate widths.
- macOS: arrange panes vertically/horizontally/both; set reasonable min/max pane sizes (keep the divider visible); provide multiple ways to reveal hidden panes; **prefer the thin divider style — "one point in width."**
- tvOS: default split = **one-third primary / two-thirds secondary** (or half-and-half); single title above the split view.

## steppers.md
Source: https://developer.apple.com/design/human-interface-guidelines/steppers

- A **two-segment** control to increase/decrease an incremental value; the stepper itself displays no value — it sits next to a field showing the current value.
- Make the affected value obvious; pair with a text field when large value changes are likely.
- macOS: consider **Shift-click** to change by a larger increment (e.g. **10 times** the default). Not supported watchOS/tvOS.

## tab-bars.md
Source: https://developer.apple.com/design/human-interface-guidelines/tab-bars

- Tab bar navigates between **top-level sections** while preserving each section's navigation state; use a **toolbar** for actions instead.
- Keep the tab bar visible during navigation (exception: a modal covering it). **Avoid overflow tabs** — the trailing tab becomes a **More** tab (iOS/iPadOS) which hides content.
- **Don't disable or hide tab bar buttons** even when content is unavailable; explain empty sections instead.
- Include tab labels (single words when possible); prefer filled SF Symbols. Badge = "a red oval containing white text and either a number or an exclamation point" — reserve for critical info.
- iOS: floats at the bottom on a **Liquid Glass** background; a dedicated **search tab** can sit at the trailing end. iPadOS: near the top, can convert to a **sidebar** (`sidebarAdaptable`); aim for a default of **five or fewer** customizable tabs. tvOS: tab bar height is **68 points**, top edge **46 points** from screen top (both fixed). visionOS: tab bar is **vertical**, fixed to the leading side. Not supported watchOS.

## text-fields.md
Source: https://developer.apple.com/design/human-interface-guidelines/text-fields

- "A rectangular area in which people enter or edit small, specific pieces of text." Use a **text view** for larger amounts.
- Show placeholder/hint text (e.g. "Email," "Password"); consider a separate label since placeholder disappears on typing.
- Use **secure text fields** for sensitive data (SecureField). Match field size to anticipated text; evenly space and vertically stack multiple fields with consistent widths; ensure logical tab order.
- Validate when it makes sense: email — validate when switching fields; username/password — validate **before** switching fields. Use a number formatter for numeric input; adjust line breaks (clip/wrap/truncate with ellipsis); consider an expansion tooltip for truncated text; show the appropriate keyboard type on iOS/iPadOS/tvOS/visionOS.
- iOS/iPadOS: display a **Clear button** at the trailing end; leading end indicates purpose, trailing end offers extra features (e.g. Bookmarks). macOS: consider a **combo box** to pair input with a list.

## the-menu-bar.md (macOS + iPadOS)
Source: https://developer.apple.com/design/human-interface-guidelines/the-menu-bar

- Menu order: **YourAppName, File, Edit, Format, View, app-specific menus, Window, Help**; macOS adds the Apple menu (leading) and menu bar extras (trailing).
- Support default system menus/ordering; **always show the same set of menu items** — disable rather than hide. Prefer short, one-word menu titles (title-style capitalization if multi-word). Support standard keyboard shortcuts.
- App menu: **About** first (in its own group; short name ≤ **16 characters**, no version), **Settings…** (Command-Comma), then Services/Hide/Quit (macOS).
- View menu handles window appearance (Show/Hide Tab Bar, Toolbar, Sidebar; Enter/Exit Full Screen); Window menu handles window management (Minimize, Zoom, tab commands, Bring All to Front — list open windows **alphabetically**). Close lives in the **File** menu.
- App-specific menus appear between View and Window, ordered most→least general. **Dynamic menu items** require a **single** modifier key (Control/Option/Shift/Command) and must not be the only way to do a task.
- macOS menu bar height is **24 pt**. iPadOS menu bar: hidden until revealed, **centered**, no Apple menu / no menu bar extras.

## toggles.md
Source: https://developer.apple.com/design/human-interface-guidelines/toggles

- A toggle chooses between two opposing states (on/off); styles include **switch** and **checkbox**.
- Clearly identify what the toggle affects; make state differences obvious (fill, background shape, checkmark/dot) — **don't rely solely on color**.
- iOS/iPadOS: use the **switch style only in a list row**; default color is **green** (change only if needed); **outside a list, use a button that behaves like a toggle**, not a switch.
- macOS: use switches/checkboxes/radio buttons in the **window body, not the toolbar/status bar**. Switch = more visual weight (emphasize a setting or group); **mini switch** for single subordinate rows. Checkbox states: **on, off, or mixed** (dash) — use mixed for partially-selected subordinate checkboxes. Radio buttons: typically groups of **two to five** mutually exclusive options; use a pop-up button if more than about **five**. Prefer a checkbox for a single on/off setting.

## toolbars.md
Source: https://developer.apple.com/design/human-interface-guidelines/toolbars

- Provides frequently used commands/controls/navigation/search along the top or bottom edge; contains the view title, navigation controls (back/forward, search), and actions/bar items. (A tab bar navigates; a toolbar acts.)
- Choose items deliberately to avoid overcrowding; the **system auto-adds an overflow menu (macOS/iPadOS)** — don't add one manually or cause default overflow. Add a **More** menu only if needed.
- **Reduce toolbar backgrounds and tinted controls** — let the content layer inform color; use a `ScrollEdgeEffectStyle` to distinguish the toolbar. Prefer standard components with corner radii **concentric with the bar's corners**. Prefer system-provided symbols **without borders**.
- Use standard **Back** and **Close** buttons (standard symbols, no "Back"/"Close" text label).
- Titles: concise, distills the window's purpose, **under 15 characters**; don't title windows with the app name; leave the title area empty if redundant.
- Item groupings — three locations: **leading edge** (back/sidebar controls + view title + document menu; not customizable), **center area** (common controls, customizable, collapses into overflow when narrow), **trailing edge** (important always-visible items, inspectors, search, More menu, and one primary action). **Use `.prominent` style for the primary action (Done/Submit) — only one, on the trailing side.** Aim for a **maximum of three** groups; separate text-labeled actions with fixed space.
- macOS: make **every toolbar item also available as a menu bar command** (toolbar is customizable/hideable).

## typography.md
Source: https://developer.apple.com/design/human-interface-guidelines/typography

- Default / minimum text sizes: **iOS & iPadOS 17 pt / 11 pt**, **macOS 13 pt / 10 pt**, **tvOS 29 pt / 23 pt**, **visionOS 17 pt / 12 pt**, **watchOS 16 pt / 12 pt**.
- Avoid light weights — "prefer Regular, Medium, Semibold, or Bold" and avoid Ultralight/Thin/Light. Minimize number of typefaces.
- System typefaces: **San Francisco (SF)** sans serif (SF Pro, SF Compact, SF Arabic, SF Armenian, SF Georgian, SF Hebrew, SF Mono; + rounded variants) and **New York (NY)** serif. Provided in the **variable** font format with **dynamic optical sizes**. Weights **Ultralight to Black**; SF widths include Condensed and Expanded.
- *Text styles* (weight + point size + leading) support Dynamic Type. System fonts: iOS/iPadOS/macOS/tvOS/visionOS = **SF Pro**; watchOS = **SF Compact** (complications use SF Compact Rounded). **macOS doesn't support Dynamic Type.**
- macOS built-in text styles (Weight / Size pt / Line height pt): **Large Title** Regular 26/32; **Title 1** 22/26; **Title 2** 17/22; **Title 3** 15/20; **Headline** Bold 13/16; **Body** Regular 13/16; **Callout** 12/15; **Subheadline** 11/14; **Footnote** 10/13; **Caption 1** 10/13; **Caption 2** Medium 10/13. (144 ppi @2x.)
- macOS tracking sample (Size pt → Tracking pt): 12 → 0.0; 13 → −0.08; 17 → −0.43 (most negative); 24 → +0.07; 80+ → 0. (Expressed in 1/1000 em.)

## widgets.md
Source: https://developer.apple.com/design/human-interface-guidelines/widgets

- Sizes: **system small / medium / large / extra large / extra large portrait**; accessory **circular / corner / inline / rectangular**.
- Appearances: **full-color, monochrome+tint, clear/translucent** (Liquid Glass). Rendering modes: **fullColor, accented** (splits views into accent + primary group), **vibrant** (Lock Screen / StandBy low-light — red tint).
- Show timely, glanceable content + deep links; prefer dynamic info; balance information density; offer sizes only when they add value.
- **Standard margin = 16 points** for most widgets; tighter groupings can use **11 points**; smaller margins on Mac desktop and Lock Screen/StandBy. Coordinate content corner radius with the widget (ContainerRelativeShape).
- Prefer system font/text styles/SF Symbols; **display text at 11 points or larger**; don't rasterize text; widgets support Dynamic Type **Large to AX5**.
- Interactivity: buttons/toggles act without launching; other taps launch the app at the right deep-linked location. Animated update transitions up to **two seconds**. visionOS widgets are 3D objects; scalable **75 to 125 percent**; two detail thresholds (**simplified** at distance, **default** nearby); mounting styles **elevated / recessed**; treatment styles **paper / glass**. Default visionOS-ish margins aside, iOS small widget e.g. **170x170 pt** on 430×932 screens.

## windows.md (iPadOS, macOS, visionOS)
Source: https://developer.apple.com/design/human-interface-guidelines/windows

- Two conceptual types: **primary** (main navigation/content) and **auxiliary** (single task/area, no navigation, has a close button).
- Windows must adapt fluidly to sizes; choose the right moment to open a new window (avoid excessive clutter); offer "view in new window" via context/File menu.
- **Avoid custom window UI** — use system frames/controls; use the term **"window"** in user-facing content (not "scene").
- macOS window = **frame** (controls + toolbar, rare bottom bar) + **body**. Three states: **Main** (one per app), **Key/active** (accepts input, one onscreen), **Inactive** (subdued, no Materials). Avoid critical info/actions in a bottom bar. Not supported iOS/tvOS/watchOS.
- iPadOS: **Full screen** or **Windowed** (freely resizable, remembers size/placement). Keep window controls (leading edge) from overlapping toolbar items — move buttons inward when controls appear.
- visionOS: styles **default (window)** + **volumetric (volume)** (+ *plain*). Retain the **glass** background. Default window size **1280x720 pt**, placed **about two meters** in front (apparent width ~three meters). Set min/max window sizes. Volumes show 3D content viewable from any angle; use dynamic scaling; baseplate glow marks edges.

---

### Rules most relevant to a glass web UI's chrome/controls

1. **Toolbars — reduce backgrounds and tinting.** Let the content layer inform toolbar color rather than custom backgrounds/tinted controls (they interfere with system background/glass effects); prefer standard components with corner radii **concentric with the bar's corners** and system symbols **without borders** (toolbars.md).
2. **Toolbar item groupings + one prominent primary action.** Three zones — leading (back/sidebar + title, non-customizable), center (customizable, collapses to overflow), trailing (always-visible items, search, More, primary action). Use the **`.prominent`** style for a single primary action (Done/Submit) on the **trailing** side; aim for a **max of three** groups; the system auto-adds overflow — don't hand-roll it (toolbars.md).
3. **Sheets — button placement and pairing.** Cancel on the **leading** edge, Done on the **trailing** edge; always pair Done with Cancel or Back and **never show Cancel + Done + Back together**; only one sheet at a time; support the **medium**/**large** detents with a grabber for progressive disclosure (sheets.md).
4. **Sidebars — glass layer, two levels, don't hide by default.** Sidebars can float in the Liquid Glass layer with a background-extension effect; show **no more than two levels of hierarchy**; let people hide/show but **avoid hiding by default**; icons default to the app accent color (sidebars.md).
5. **Segmented controls — limit count and keep types consistent.** No more than about **five to seven** segments wide / **five** on narrow; keep all segments equal width; don't mix selection-state and action segments, and don't mix text with images in one control (segmented-controls.md).
6. **Text fields — placeholder + label, trailing Clear button, contextual validation.** Placeholder disappears on typing so keep a separate label; secure fields for sensitive data; show a **Clear button at the trailing end**; validate email on field-exit but username/password before leaving the field (text-fields.md).
7. **Toggles — obvious state, not color-only; switch only in list rows.** Make on/off differences obvious with more than color; use the switch style **only in a list row** (default green), and outside a list use a button-that-toggles; use checkboxes for hierarchical/mixed-state settings (toggles.md).
8. **Typography — size floors and weights.** Respect minimums (macOS **13 pt default / 10 pt min**; iOS **17 / 11**); avoid Ultralight/Thin/Light — prefer Regular/Medium/Semibold/Bold; minimize the number of typefaces; use text styles for hierarchy (typography.md).
9. **Popovers — one at a time, save nonmodal work, no warnings.** Show a single popover (never cascade), point the arrow at the revealing element, always save on auto-close of a nonmodal popover, and never use a popover for a warning (use an alert) (popovers.md).
10. **Progress indicators — determinate, moving, don't swap shapes.** Prefer determinate with an even pace; keep it moving; never switch circular ↔ bar; offer Cancel (and Pause when interruption has side effects) (progress-indicators.md).
