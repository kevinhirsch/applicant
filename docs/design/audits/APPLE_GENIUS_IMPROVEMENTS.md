# Apple Genius — 100+ Improvement Suggestions (Liquid Glass / HIG / Product)

Produced by the Apple Genius (the reviewer who built this glass system) auditing the
live front-door in parallel, each finding grounded in one of: **(P)** pixel-parity
with the upstream render, **(H)** an Apple HIG rule, or **(X)** product knowledge
(the 25-surface feature map). Severities: blocker / major / minor / nit. `file:line`
anchors are into `workspace/static/`.

> Scope honesty (read `§I Coverage gaps` first): these audit the **disconnected,
> empty-state** surfaces. The **trust-core flows** — a live chat with bubbles, a
> populated Portal, the digest→redline→approve loop, the takeover/final-submit — were
> never rendered (no model/data) and are **not** covered here. The dynamic optics
> (adaptive-ink flip, specular, lensing-in-motion) can't be judged from stills.

## The five systemic themes (fix these once, fix dozens)

1. **Adopt the kit.** Portal/Chat/Mind/Vault/Debug/Compare/Activity/Gallery hand-roll
   `.modal-content` + `<button class="close-btn">✖</button>` + `.cal-btn` + native
   `<select>` instead of composing `appkitWindow` (`.ow-window`/`.ow-titlebar`/
   `.ow-controls`), `.ow-btn`, `.ow-select`. So they never get the traffic-light
   controls, concentric radii, or kit selects. This is the deeper lift-and-shift.
2. **One list-row primitive.** Memory/Tasks/Library/Email/Gallery each frame rows as
   bordered glass tiles (glass-in-content). Extract one flat `.ow-list-row` (hairline
   separator, ≥44px, hover fill, system-blue focus) and adopt everywhere.
3. **Color discipline, still.** Selection uses `--red` (should be system-blue); status
   uses raw hex + glows; event/tab/field labels carry hue. Chrome ink neutral; color
   = system state fills + one primary CTA.
4. **Kill perpetual/decorative motion** and gate every `infinite` keyframe behind
   `prefers-reduced-motion` (several are ungated).
5. **Tokenize the system**: one `--tap-min:44px`, one `--concentric-radius`, motion
   `--dur/--ease`, a `--text-*` type ramp, and **one tier gate** (collapse the
   `house-theme` vs `theme-frosted`/`glass-full` split).

---

## §A — Systemic / engine / global

1. **[P][blocker]** Tier gate is split: CSS frost gates on `body.house-theme`
   (kit-themes.css:30) but JS refraction/adaptive gate on `theme-frosted`/`glass-full`
   (appkitGlass.js:867,1622); `applyFrostedGlass()` (theme.js:461) sets `theme-frosted`
   *without* `house-theme` → refraction over surfaces with no frost fill. Collapse to
   one gate; make `applyGlassTier` the sole writer.
2. **[P][major]** Delete the dead `house-theme--*` persona skins (the-feed/telescreen/
   memory-wall/sequester/room-101, kit-themes.css:55-90) and rename `house-theme` →
   `theme-frosted` throughout (white-label + simplicity).
3. **[P][major]** Missing kit: no `appkitSheet.js` (the upstream fork's sheet kit) — no
   bottom-sheet primitive, so flows fall back to full modals. Port it; wire for review.
4. **[P][major]** Missing kit: no status-panel (the upstream fork's engine/night-status
   panels) — no live surface for the 24/7 loop. Port + bind to setup-status/heartbeat.
5. **[P][major]** Missing kit: no slot manager (the upstream fork's slot kit) — only the
   `.appkit-slotted` marker survives, slotted layout half-wired. Port it.
6. **[P][major]** Missing kit: no gadget **rail** (the upstream fork's gadget-rail kit) —
   only single `appkitGadget` cards; no rail container. Port it.
7. **[P][major]** Mesh wallpaper hard-pinned to `preset:'aurora'` (theme.js:36); the
   5 presets are login-only. Surface the picker in Settings; read it in `ensureGlassWallpaper`.
8. **[H][major]** Adaptive-ink node list stands down on chrome (appkitGlass.js:1759-80);
   only `.msg-ai` + hero adapt. Composer/model-picker/toasts get no small-bar symbol
   flip → light glyphs wash out over bright mesh lobes. Re-enable per WWDC219.
9. **[H][major]** Welcome hero washes into the wallpaper despite `HERO_ADAPTIVE`
   (appkitGlass.js:1206) — the sampler reads `#__wp` but the `--lbg-base` mirror
   (theme.js:38-43) can miss first paint. Sample the mesh child directly; re-run on
   wallpaper load/`transitionend`.
10. **[H][major]** ~12 focusable surfaces lost their focus ring in the fork (106 vs 118
    upstream `#0a84ff` rules). Diff and restore the missing `:focus-visible` blocks.
11. **[H][major]** No single concentric-radius token: `--window-radius:10px`,
    `--window-sheet-radius:14px`, `--ow-glass-radius:14px`, JS lens `RADIUS=18`
    disagree — the lens band sits outside the visible corner. One `--concentric-radius`.
12. **[H][major]** 44px tap floor is a copy-pasted literal at ~9 sites; newer surfaces
    miss it. Add `--tap-min:44px` and reference globally.
13. **[H][major]** No motion tokens — durations are ad-hoc literals (.08s/.2s/.3s).
    Add `--dur-fast/-base/-slow` + `--ease-standard`; migrate hot paths.
14. **[H][major]** Reduced-motion: the `#__wp` ray-sweep `::after` + specular re-render
    aren't gated. Extend the `prefers-reduced-motion` block to the wallpaper children.
15. **[H][minor]** In-app mesh intensity/speed have no user control (theme.js:36) while
    login exposes them. Add Settings sliders (OLED/low-power/distraction).
16. **[H][major]** Reduce-transparency completeness: 64 vs 66 upstream a11y queries —
    two solid-fallback blocks dropped, so a couple of glass surfaces stay translucent.
    Diff and restore.
17. **[X][major]** No global modal/z-order arbiter (upstream `modalManager`/`escMenuStack`
    not ported) — two overlays can stack, Esc is ambiguous. Adopt one modal stack.
18. **[X][major]** Iconography inconsistent — hand-rolled brand SVG (index.html:1206) +
    mixed inline glyphs, no `--icon-size`/stroke token. Standardize one SVG sprite.
19. **[X][major]** First-run home is bare mesh + washed wordmark + "Type /setup" — reads
    broken, not intentional (upstream dresses its empty state as the "house is dark"
    card). Give the pre-setup home a designed glass welcome card that launches the wizard.
20. **[H][minor]** Scrollbars: only one `::-webkit-scrollbar` rule; no Firefox
    `scrollbar-width/color`. Add a tokenized overlay-scroller treatment.
21. **[H][minor]** Frosted tier has no specular rim (gates on `glass-full` only,
    appkitGlass.js:867) → flat frosted panels ("without specular it's not glass"). Add a
    CSS inset rim highlight for `theme-frosted:not(.glass-full)`.
22. **[P][minor]** Vibrancy differs by tier: `glass-full` gets in-filter `saturate(1.4)`,
    Frosted gets none. Add `backdrop-filter: saturate(140%)` to the frost block.
23. **[X][minor]** No modular type scale — sizes are ad-hoc; headings don't map to HIG
    Large Title/Title/Body/Caption. Add `--text-*` ramp; migrate headings.
24. **[H][minor]** Large-surface chrome flip fully retired (appkitGlass.js:1759) — light
    chrome is fixed regardless of a bright wallpaper lobe behind it. Re-enable the
    flip-free large-surface adaptive veil.

## §B — Shell / Sidebar / Portal

25. **[P][major]** Portal titlebar hand-rolls `✖`/`–` boxed buttons instead of the kit
    traffic-lights (`.ow-controls`, appkitWindow.js:531). Render Portal via `.ow-window`
    (applicantPortal.js:279).
26. **[H][blocker]** "Refresh" shows a **persistent** system-blue focus ring at rest —
    reads as a bug + breaks tint discipline. Scope the ring to `:focus-visible` only
    (applicantPortal.js:285).
27. **[X][major]** Refresh is the most-emphasized control on a queue whose meaning is the
    per-row primary; it also already polls 60s. Demote to a plain neutral icon
    (applicantPortal.js:285).
28. **[H][major]** Gated empty state uses a warning `circle+!` glyph for a healthy
    unconfigured state. Use a neutral/inbox mark (applicantPortal.js:332).
29. **[H][major]** Empty copy is thin, centered, `opacity:0.85` — raise to Semibold body,
    left-align, drop blanket opacity for a real secondary-label token (applicantPortal.js:331).
30. **[X][major]** Gated empty state is a dead end — no button to the wizard. Add one
    tinted "Finish setup" CTA → `launchApplicantSetup()` (applicantPortal.js:327).
31. **[P][major]** Sidebar is light glass over a dark desktop; upstream floats a **dark**
    sidebar over a lighter hero — reconcile the material to the reference (style.css:32500).
32. **[H][blocker]** Composer glass bar and the Portal window **overlap/intersect** (the
    window edge crosses the composer, clipping its text) — glass-on-glass in a steady
    state. Dim/reflow the composer when a window is open (applicantPortal.js:278).
33. **[H][major]** Verify the Portal (large surface) is excluded from the small-element
    luminance flip (style.css:32500).
34. **[H][major]** Titlebar mixes text "Refresh" with `–`/`✖` symbols in one cluster —
    separate the text action; ≤3 groups (applicantPortal.js:284).
35. **[H][major]** Titlebar buttons are fixed-radius boxes, not concentric with the
    window corner. Use `.ow-controls` capsules (applicantPortal.js:285).
36. **[H][major]** Titlebar/close hit region <44px. Pad the hit target to 44 (keep glyph
    32) (applicantPortal.js:286).
37. **[H][major]** Mobile sheet header has no Cancel-leading/Done-trailing order and a
    tinted Refresh; sheet should go more opaque at full height (applicantPortal.js:279).
38. **[H][major]** Multiple neutral controls tinted while the actual primary is absent —
    one system-blue CTA per view only (applicantPortal.js:285).
39. **[X][major]** Gated view drops the "what Applicant never does" trust list that
    `_neverDoesHTML()` exists to show. Render it beneath the gate (applicantPortal.js:338).
40. **[P][minor]** Composer trades the reference's single paperclip for a chevron+search+
    terminal chip cluster — collapse to one attach control (style.css:32502).
41. **[H][minor]** Wordmark/hero use a very light weight over dark → ghosted. Floor at
    500+; don't lean on opacity (style.css:32957).
42. **[H][minor]** Empty state leans on wrapper `opacity` for hierarchy — replace with
    semantic label tokens that survive Reduce Transparency (applicantPortal.js:314).
43. **[X][minor]** Sidebar `locked` items look identical to truly `disabled` — give
    `locked` a lock glyph + tooltip routing to setup (app.js feature consumer).
44. **[H][nit]** Empty-state padding asymmetric, body not optically centered on the 640px
    window. Normalize to a 24pt rhythm (applicantPortal.js:331).

## §C — Chat / Composer / Mind

45. **[P][major]** Composer placeholder diverged — restore `Say or do something…`
    (style.css:35362 comment still cites it).
46. **[P][blocker]** The assistant opens as a centered `.modal` slab floating **over** the
    live composer + welcome — glass-on-glass-on-content. Render the stream **inline** in
    the content plane docked to the real composer (applicantChat.js:72).
47. **[H][major]** Assistant + mind render in monospace — set to the UI system stack;
    reserve mono for `pre`/`code` (applicantChat.js modal, applicantMind.js:43).
48. **[H][major]** Mind "Close" is a system-blue-ringed pill reading as the one primary
    CTA, but it's a dismiss. Make it neutral (applicantMind.js:41).
49. **[H][major]** Every mind empty value is italic gray — drop italic; use secondary-label
    weight (applicantMind.js:88).
50. **[H][major]** Mind label↔value have a huge horizontal gap (value floats center-right)
    — left-align the hint under its header (applicantMind.js:85).
51. **[H][major]** Empty-state icon is a 34px hairline (stroke 1.5, 0.5 opacity) — raise
    to stroke 2, legible opacity, ~40px (applicantChat.js:108).
52. **[X][major]** "isn't connected yet / Connect a model in Settings" is a dead end — add
    a primary "Connect a model" → `launchApplicantSetup` (applicantChat.js:105).
53. **[P][major]** Bubble tail is a hard 0px corner (`.msg-user` 18px…0 18px) — use a small
    non-zero tail radius (~6px) (style.css:1918/1933).
54. **[H][minor]** `.msg-ai` pinned `width:85%` in base (only `fit-content` under frosted)
    — default `fit-content` + `max-width:85%` (style.css:1935).
55. **[H][major]** No reading-measure cap — cap `.applicant-mind-body` + message `.body` to
    ~62-68ch (applicantMind.js:43; style.css:1970).
56. **[H][major]** Offline/empty has only a bare "Loading…" text node — reuse the native
    thinking spinner/pill for load + streaming (applicantChat.js:82).
57. **[H][minor]** Circular send is filled system-blue even when the field is empty — gate
    to the disabled style until there's content (style.css:33391/33470).
58. **[P][minor]** Composer exposes agent-only web/bash toggle icons — hide them on the
    assistant composer (chat.js:733).
59. **[H][minor]** Send `svg` stroke 2.5 in a 48px disc — normalize to ~2.0 SF `arrow.up`
    weight across idle/streaming (chat.js:184,211).
60. **[H][major]** Mind overlay is a hand-rolled `rgba` scrim on a raw `.admin-card` with
    an unassigned `_modalA11yCleanup` (no focus trap). Mount via `appkitWindow`/`initModalA11y`
    (applicantMind.js:34).
61. **[H][major]** Mobile assistant sheet body is left-aligned monospace, edge-to-edge —
    inset the body, cap measure, dim the content-plane welcome behind (chat-mobile).
62. **[X][minor]** Mind repeats "What the assistant remembers" as header **and** inner
    section — drop the duplicate (applicantMind render).
63. **[H][minor]** Desktop empty state drops the whole block to `opacity:0.75` incl. the
    headline — keep headline full, dim only the secondary line (applicantChat.js:107).
64. **[P][nit]** Assistant modal header uses bordered square window controls — render via
    `.ow-window` so the titlebar matches every other window (applicantChat.js:73).

## §D — Onboarding / Settings

65. **[H][blocker]** Settings sheet wears a system-blue border/glow (reads as a persistent
    focus ring on the container). Neutral 1px `--border` + shadow (style.css:4613/32215).
66. **[H][blocker]** Fields show **no** focus ring and focus paints `border-color:var(--red)`
    — 3px `#0a84ff` ring, drop the red (`.settings-select:focus`, style.css:18814).
67. **[H][major]** Fields miss ≥44px — `.settings-select` is `padding:5px 8px`/12px, no
    `min-height`. Add `min-height:44px` (style.css:18788).
68. **[P][major]** Welcome stacks two bordered `.admin-card` boxes + footer rule + nav rule
    in one plane — flatten to hairline groups for the one-plane read (applicantOnboarding.js:301).
69. **[H][major]** Two stacked action rows (blue "Let's get started" + separate "Skip") —
    fold Skip into one terminal action bar (applicantOnboarding.js:272; style.css:32228/32260).
70. **[H][major]** Settings empty states render "None" in **red** — use muted "None yet";
    reserve red for errors (style.css:14).
71. **[H][major]** Section header "ADMIN" is all-caps — title-style "Admin"
    (`.settings-sidebar-label`, style.css:6174).
72. **[P][major]** Settings sidebar + `(Endpoints)` sub-labels tinted brand hue — recolor to
    `--chrome-ink` (settings-desktop).
73. **[H][major]** Panel subtitle ("Toggle on/off visibility…") doesn't match the open
    "Add Models" pane — per-pane descriptions or drop it (settings-desktop).
74. **[H][major]** Mobile stepper truncates ("3. Your pro…") — collapse to "Step N of 3 ·
    Your profile" on narrow (applicantOnboarding.js:179; style.css:16567).
75. **[P/H][major]** Steps use `.admin-tab` (interactive tab) but are non-clickable progress —
    give a real stepper (dots/numerals, `aria-disabled`) (applicantOnboarding.js:185).
76. **[X/H][major]** "The only required step" is prose, but the rail gives all 3 steps equal
    weight — mark "Connect a model" required, de-emphasize optional profile (applicantOnboarding.js:305).
77. **[H][major]** Secondary buttons match the primary's 44px pill size/adjacency — give
    plain `.cal-btn` a quieter treatment so the one CTA dominates (style.css:30786).
78. **[H][minor]** `?` help bubbles hard-code a dark bg (`#20232a`) — source from the theme
    material token (style.css:32249).
79. **[H][minor]** Settings sheet has no grabber (mobile does) — add sheet affordances or
    confirm fixed panel (settings-desktop).
80. **[H][minor]** Form grouping uses inline styles for spacing/heading sizes — move to
    shared classes/type ladder (applicantOnboarding.js:1165).
81. **[X/H][minor]** Welcome front-loads intro + 2 lists + a dense paragraph + a 4-item list
    before any action — trim to the one-line promise + the required step (applicantOnboarding.js:293).
82. **[H][nit]** "Add/Added Models" + `(Endpoints)` are engineering labels — plain-language
    "Local model"/"Cloud API" (settings-desktop).
83. **[H][nit]** Two progress indicators for one flow (rail + in-body "Profile step N of M")
    — keep one (applicantOnboarding.js:1238).
84. **[P][nit]** Steps left-align everything + right-align the CTA; upstream centers a calm
    single column — adopt a consistent max-width content column.

## §E — Observability (Activity / Debug / Compare)

85. **[P][major]** Active tab is a hued blue underline — neutral ink/pill; reserve blue for
    the CTA (`.admin-tab.active`, style.css:19292).
86. **[H][major]** Debug has **8** tabs (> the 5-7 ceiling) — collapse Sources/Tools/Update
    into one Config pane (applicantDebug.js:50).
87. **[H][major]** Debug header packs 4+ groups (picker + status text + 2 text buttons) —
    leading=title+picker, trailing=one overflow; move engine badge to the body (applicantDebug.js:78).
88. **[P][major]** Run-controls status chip built from raw hex + a pulsing dot — neutral
    label + system-token dot, drop the pulse (applicantDebug.js:496).
89. **[P][major]** Compare diff is a hand-rolled `<table>` with inline per-cell borders on
    the modal glass — render into a content-material section (applicantCompare.js:211).
90. **[H][major]** Native `<select>` in Compare/Debug (OS chrome dropdown) — route through
    the kit select (applicantCompare.js:76; applicantDebug.js:81).
91. **[P][major]** Activity live dot uses `var(--accent,#3a8)` — use `--sys-green` live /
    neutral paused (applicantActivity.js:207).
92. **[H][major]** All-caps 9.5px micro-labels ("Now/Up next", "Recently I…") — sentence-case
    Medium/Semibold; hierarchy from weight not caps (applicantActivity.js:193).
93. **[P][major]** Debug source/tool toggles are one bordered `.admin-card` per row →
    stacked tiles; group into one list with hairline dividers (applicantDebug.js:663).
94. **[H][major]** Debug Activity list stacks a bordered card per app, each with two neutral
    buttons — one list, one primary per row, demote the other (applicantDebug.js:292).
95. **[X][major]** Logs are a raw `<pre>` blob — structured rows (time · level · plain
    message) with neutral level chips; keep raw for Download (applicantDebug.js:440).
96. **[H][minor]** "Comparing…"/"Working…" text-only, no progress affordance or cancel —
    reuse the shared spinner; add Cancel where interruptible (applicantCompare.js:169).
97. **[P][minor]** Compare diff signal is opacity-dimmed text/`—` only — flag differing rows
    with neutral-ink weight/bg in the content layer (applicantCompare.js:229).
98. **[X][major]** Compare result is a dead-end table — link entity labels into the Debug
    detail/Gallery so it's navigable (applicantCompare.js:216).
99. **[H][minor]** Activity header mixes a text Refresh with the `✖` icon — make Refresh an
    icon or move to the body (applicantActivity.js:151).
100. **[P][minor]** `.admin-card` (panel bg + border + radius) stacked inside the modal =
    glass-on-glass tiling — one content-material body with hairline dividers (style.css:10623).
101. **[X][minor]** "Ask the assistant" renders then no-ops to a toast if chat is absent —
     gate its visibility on the module presence (applicantDebug.js:119).
102. **[H][nit]** Insights funnels render as dot-joined prose ("N matched · N approved…") —
     an aligned mini key/value so numbers compare down a column (applicantDebug.js:393).
103. **[P][nit]** Close is the literal glyph `✖` as text across Activity/Debug/Compare — use
     the kit's borderless symbol close (applicantDebug.js:76).

## §F — Vault / Remote / Gallery

104. **[P][major]** Vault sheet has a hued teal rim (`border:1px solid var(--border)`) — a
     secrets sheet is one opaque plane, edge by shadow/luminous hairline, not a hued stroke
     (style.css:4709).
105. **[H][blocker]** Three co-equal blue "Save …" primaries in one view — one/two prominent
     max; demote per-section saves; the active card's is prominent (applicantVault.js:77/90/110).
106. **[H][major]** Secrets sheet not verifiably opaque under glass tiers — pin
     `#applicant-vault-modal .modal-content` fully opaque, `backdrop-filter:none` (style.css:4614).
107. **[P][minor]** Vault inner cards aren't concentric with the sheet — derive inner radius =
     window-radius − pad; prefer a hairline divider (applicantVault.js:60/95/114).
108. **[H][major]** Password fields reuse `.settings-select` (picker chrome) — give a plain
     neutral text-field class (applicantVault.js:75/88/107).
109. **[X][major]** The "sites with a saved sign-in" trust payoff sits last, below three forms
     — lead with the trust affordance + saved count (applicantVault.js:114).
110. **[P][blocker]** Remote "Finish the application" card has a custom blue border
     (`border-color:var(--accent-color,#5b8def)`) — delete it (applicantRemote.js:121).
111. **[H][blocker]** Two equally-tinted primaries ("Take control" + "Authorize the assistant
     to finish") — demote Take control; one CTA (applicantRemote.js:83).
112. **[H][blocker]** The **irreversible** final-submit is styled system-blue Primary — it's
     the Destructive role; give the authorize button the red destructive weight so its gravity
     is unmistakable (applicantRemote.js:130).
113. **[X][major]** The two terminal choices (self-submit vs authorize-engine) read as siblings —
     present as an explicit decision pair (calm secondary vs weighted red), visually separated
     (applicantRemote.js:127).
114. **[P][major]** Live-view frame uses a custom hard border + `#0b0b0b` fill — neutral inset,
     let it read as content (applicantRemote.js:71).
115. **[H][major]** A blocking "Connect an AI model first" notice renders as a bare tooltip
     colliding with the header — route through the notice/`appkitChatHint` kit in-flow
     (applicantRemote.js intro).
116. **[H][minor]** Dormant desktop-help + resume cards push the irreversible action below the
     fold — collapse the dormant card to a disabled row (applicantRemote.js:104).
117. **[P][major]** Gallery tiles are `.admin-card` chrome — they ARE the content; make them flat
     content cells (no card chrome/shadow) (applicantGallery.js:115/142).
118. **[P][minor]** Close glyph inconsistent (`✖` vs `×`, `.close-btn` vs `.modal-close`) —
     standardize one close control + glyph (applicantGallery.js:47).
119. **[H][major]** Close/dismiss controls are 24×24px, below 44px, no dedicated focus ring —
     grow the hit region to ≥44px (padding) + a `#0a84ff` ring (style.css:4768; .cal-btn:30786).
120. **[X][minor]** Gallery empty state points at a disabled "No job searches yet" picker — a
     dead end; offer the real next step (create a job search) (applicantGallery.js:157/101).
121. **[P][nit]** Vault reads busy (title + 3 sub-headed forms + list, 12-14px gaps) vs the
     reference's calm single-CTA sheet — increase rhythm, lean on the type scale (applicantVault.js:53).

## §G — Content routes (Calendar / Tasks / Email / Library / Memory / Notes / Gallery)

122. **[P][blocker]** Memory rows are framed glass tiles (border + `--fg 3%` + 8px) — flat
     separator rows, hover-only fill (style.css:7752).
123. **[H][blocker]** Perpetual `memory-synapse-sweep` `::after` on every row (5 stagger loops)
     — delete the sweep + keyframes + `@property --sweep` (style.css:7777).
124. **[H][major]** Memory-modal "breathing" radial-glow pulse — remove `memory-synapse-pulse`
     (style.css:7210).
125. **[P][major]** `.memory-pinned` tints the row red — convey pinned with a neutral glyph,
     not `border-left-color:var(--red)` (style.css:7834).
126. **[P][blocker]** `.cal-event-tag` sets both `color:` and `border-color:` from the type
     palette — monochrome label ink, move hue to a leading dot (calendar.js:1549).
127. **[H][major]** Month event rows at `font-size:9px` / bars `8px` — raise to ≥11px, truncate
     not shrink (style.css:29920/29932).
128. **[P][major]** Multiday/all-day bars paint the whole bar with a raw saturated fill under
     white text — low-alpha tint + neutral ink (calendar.js:983/1149).
129. **[H][major]** Calendar toolbar > 3 groups + text/icon mixing — collapse to nav | view-
     segment | +New; filters to overflow (calendar.js:789).
130. **[H][minor]** Month event cells `padding:1px 2px`, radius 2 — far under 44px, no focus —
     add ≥28px min-height + focus ring (style.css:29916).
131. **[X][major]** Tasks reuse `class="memory-item task-card"` — inherit glass tiles + synapse
     sweep bleed; give tasks their own flat row class (tasks.js:656).
132. **[P][major]** Task status dot uses double `box-shadow` glow + colored pills — drop the
     glow, neutralize the badge (tasks.js:310/664).
133. **[P][minor]** Task log rows hard-code `color:${color}` on text — neutral text, color only
     the tiny glyph (tasks.js:760).
134. **[P][major]** Library `.doclib-card` docs are bordered glass tiles — flat separator rows;
     card only for the expanded reader (style.css:12425).
135. **[P][major]** Selection highlight is `color-mix(var(--red) 40%)` across all card types —
     selection is system-blue, not red (style.css:12451).
136. **[H][major]** Library empty-state uses `color:var(--accent,var(--red))` underlined text as
     the CTA — make Import a proper button (documentLibrary.js:393; calendar.js:728).
137. **[P][major]** Gallery tiles carry border + hover box-shadow/transform lift — media is
     content; flat gutter grid, selection by ring not lift (style.css:14012/14209).
138. **[X][minor]** Two distinct "Gallery" surfaces (engine captures vs workspace photos) both
     nav as "Gallery" — label/route distinctly (applicantGallery.js).
139. **[X][major]** Notes render as colored sticky tiles (pastel `note-color-*` on the body) —
     move color to a thin edge marker, keep the body neutral (notes.js:1801/2823).
140. **[H][minor]** Verify `note-card-reminder-due` isn't a perpetual glow — one-shot 3s
     highlight; persistent due = static border (notes.js:971/1051).
141. **[H][major]** Email empty state reuses `.email-loading` — give a first-class empty state
     (symbol + guidance + Connect/Compose) (emailInbox.js:441).
142. **[P][minor]** Standardize the email unread indicator on a single system-blue dot + flat
     separator row (emailInbox.js:24/74).
143. **[H][major]** No shared list-row primitive — Memory/Tasks/Library/Email hand-roll framing.
     Extract `.ow-list-row` (hairline, ≥44px, hover, blue focus) and adopt across all five.
144. **[H][minor]** Several `infinite` keyframes are ungated for reduce-motion (`rail-notes-pulse`
     style.css:750, `rail-min-pulse` 792) — wrap every infinite anim in a reduce-motion block.
145. **[P][nit]** `.cal-wk-block:hover { filter:brightness(1.05) }` compounds the saturated fill —
     use a neutral hover/selection ring (style.css:30216).
146. **[H][minor]** `.memory-item`/`.doclib-card` use `transition: all` (animates layout/paint) —
     scope to `background-color, border-color` (style.css:7762/12430).

---

## §H — Journey-ranked (the trust arc)

Ranked by which trust beat the fix protects (the highest-leverage cut, per the journey map):

- **Beat 1 — OOBE first impression (make-or-break funnel):** #19 (designed welcome card,
  not raw wallpaper text), #9/#41 (hero legibility), #30/#52 (dead-end → wizard CTA),
  #65-#67 (settings/field focus + 44px), #74-#76 (stepper + required-step emphasis).
- **Beat 2 — review → approve (trust earned daily):** *unaudited* (no data) — see §I; but
  #143 (one list-row), #85-#95 (observability legibility), and the missing `appkitSheet` (#3)
  for the redline flow are the substrate.
- **Beat 3 — takeover / final-submit (highest gravity, irreversible):** #110-#113 (remote:
  kill the blue custom border, one CTA, final-submit = destructive red, explicit decision
  pair), #104-#109 (vault trustworthiness).
- **Beat 4 — steady state (glance & trust):** #25-#39 (Portal as a real home/inbox), #46-#47
  (chat inline not modal, system font), #122-#124 (kill perpetual memory motion).
- **Beat 5 — outcome / learning:** #48-#50/#62 (mind panel), #95 (structured logs), #98
  (navigable compare).

## §I — Coverage gaps (what we have NOT audited)

1. **The trust-core flows** — a live conversation with bubbles, a **populated Portal** with
   pending-action rows, the **digest → redline → approve** loop, the **live takeover / final
   submit**. All were empty (no model/data). These are the highest-leverage journey beats and
   are **unjudged**. Next step: connect a model + seed data, render + audit them.
2. **Dynamic optics** — adaptive-ink flip, specular tracking, lensing-on-scroll, materialize-
   via-lensing, streaming/thinking spinners, toasts. Not visible in stills.
3. **First screen** — login + landing were not captured/audited.
4. **A11y states rendered** — the reduce-transparency/contrast/motion fallbacks were wired but
   never rendered to confirm the glass truly degrades.
5. **Responsive breadth** — desktop + a few mobile only; tablet/very-narrow/very-wide untested.
6. **Full-glass performance** — the refraction cost across every window with real content is
   unmeasured (relevant to the earlier no-perf-hit concern; Frosted stays a Settings opt-out).
