# Redesign: left sidebar = one cohesive scrolling column

Status: SPEC (not implemented). Read-only investigation, no source files changed.

## Problem

The left sidebar reads as several stacked, independently-clipped widgets
instead of one list: the Applicant nav (40 buttons) scrolls inside its own
45vh box, Chats scrolls inside its own box, Tasks is capped at 40% height
and scrolls inside its own box, and Preferences sits in a region that
doesn't scroll at all. Two prior commits on this branch (`e0de09f7f`,
`aa03fe903`) already unified the *visual* style of the rows (font,
padding, color) but did not touch the *flex/overflow* structure that
causes the clipping — that structure is this task's target.

Target: brand header fixed at top (doesn't scroll), then ONE
`flex:1; min-height:0; overflow-y:auto` region containing, in order, the
Applicant nav items, Tasks, and Preferences — all styled as identical
rows, no distinct section-header treatment.

Per instructions, this spec excludes the Chats list from the target
design (it's being replaced by a single-conversation entry in a separate
workstream) but still specifies what to do with `#chats-section` today so
the flex fix doesn't leave it broken in the interim.

## Current structure (verified against source)

```
.sidebar-shell
├─ <x-component .../header-icons.html>   position:fixed overlay, NOT a child of #left-panel
└─ #left-panel                            height:100vh; overflow:hidden; flex column
   ├─ x-extension#sidebar-start
   ├─ .left-panel-top.no-scrollbar        flex:1 1 auto; overflow:hidden; margin-top:6.5rem
   │  ├─ <x-component .../sidebar-top.html>
   │  │  └─ .sidebar-top-wrapper           flex-shrink:0 (i.e. flex:0 0 auto)
   │  │     └─ <x-component .../quick-actions.html>  (display:contents)
   │  │        └─ #quick-actions           display:grid, 5 cols
   │  │           └─ x-extension#sidebar-quick-actions-main-start (display:contents)
   │  │              └─ #applicant-hello-world-nav    max-height:45vh; overflow-y:auto ← INNER SCROLL #1
   │  ├─ #chats-section.config-section     flex:1 1 auto; max-height:100%; overflow:hidden
   │  │  └─ ... .chats-config-list         overflow:scroll                ← INNER SCROLL #2
   │  └─ #tasks-section.config-section     flex:0 0 auto; max-height:40%; overflow:hidden
   │     └─ ... .tasks-config-list         overflow-y:auto                ← INNER SCROLL #3
   ├─ .left-panel-bottom                   flex-shrink:0; flex-grow:0 (never scrolls, never clips)
   │  └─ <x-component .../sidebar-bottom.html>
   │     └─ .sidebar-bottom-wrapper
   │        ├─ <x-component .../preferences-panel.html>
   │        └─ .version-info
   └─ x-extension#sidebar-end
```

Key citations:
- `agent-zero/webui/components/sidebar/left-sidebar.html:14-15` — header-icons
  is a sibling of `#left-panel`, not inside it.
- `left-sidebar.html:43-62` — `#left-panel` base rule: `height:100vh`,
  `overflow:hidden`, `justify-content:space-between`.
- `left-sidebar.html:64-75` — `#left-panel>.left-panel-top` gets `flex:1;
  min-height:0`; `#left-panel>.left-panel-bottom` only gets
  `display:flex;flex-direction:column` (no flex-grow).
- `left-sidebar.html:81-93` — `.left-panel-top { flex:1 1 auto; overflow:
  hidden; justify-content:space-between; margin-top:6.5rem; ... }`.
- `left-sidebar.html:95-100` — `.left-panel-bottom { flex-shrink:0;
  flex-grow:0 }` — this is why Preferences never scrolls with the rest.
- `left-sidebar.html:103-112` (`#chats-section`) and `:115-127`
  (`#tasks-section`) — both `overflow:hidden` with a `max-height`
  constraint, each forcing their inner list to carry its own scrollbar.
- `left-sidebar.html:138-149` — `#tasks-section .collapse { flex:1;
  min-height:0 }` / `.collapsing { flex:0 0 auto !important }` — Bootstrap
  collapse-driven sizing that assumed a height-constrained parent.
- `left-sidebar.html:151-168` — the shared `.section-header` /
  `.section-header-collapsible` rule (uppercase, 11px, letter-spacing).
- `agent-zero/webui/components/sidebar/top-section/sidebar-top.html:22-31`
  — `.sidebar-top-wrapper { flex-shrink:0 }` (effectively `flex:0 0 auto`)
  is the direct cause named in the structural findings: it can't grow, so
  its child (`#quick-actions` → the Applicant nav) can't get real height
  from the flex chain and had to invent its own `max-height:45vh` escape
  hatch.
- `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html:174-175`
  — `#applicant-hello-world-nav { max-height: 45vh; overflow-y: auto; }`
  is that escape hatch. (Note: the task brief's "max-height:none override
  already appended" does not match what's on disk — current value is
  `45vh`, confirmed via `git show HEAD:...hello-world.html` with no
  uncommitted diff on this file. Treat `45vh` as the current value; this
  spec removes the rule entirely rather than changing its value.)
- `hello-world.html:204-209` — a second `<style>` block already applies
  most of the requested row look globally: `#left-panel .sidebar-action,
  .chat-container, .task-container { padding:6px 16px; font-size:13px;
  font-weight:400; color:rgba(255,255,255,.9); ... }` (line 206) is
  **already exactly the spec's ask** — but the paired rule on line 205,
  `#left-panel .section-header, #left-panel h3 { text-transform:uppercase;
  font-size:11px; font-weight:600; ...}`, is the uppercase-grey treatment
  the new design explicitly wants removed.
- `agent-zero/webui/components/sidebar/chats/chats-list.html:14-15,25` —
  `<h3 class="section-header">Chats</h3>` + `.chats-config-list`.
- `agent-zero/webui/components/sidebar/tasks/tasks-list.html:12-22` —
  `<h3 class="section-header section-header-collapsible">Tasks` +
  collapse toggle bound to `$store.sidebar.toggleSection('tasks')`
  (`sidebar-store.js:54-58`). Also note lines **70-73**: a pre-existing
  duplicate `</template></div>` closing-tag bug in this file (dead
  markup, browsers silently ignore it) — not part of this task, flagging
  for awareness only.
- `agent-zero/webui/components/sidebar/tasks/tasks-list.html:89-94` —
  `.tasks-list-container .section-header { position:sticky; top:0; ... }`.
- `agent-zero/webui/components/sidebar/bottom/preferences/preferences-panel.html:12-20`
  — `<h3 class="section-header section-header-collapsible pref-header">
  Preferences` + collapse toggle bound to `$store.sidebar
  .toggleSection('preferences')`.
- `agent-zero/webui/components/sidebar/bottom/sidebar-bottom.html:10-20,27-31`
  — `.sidebar-bottom-wrapper` (holds Preferences + `.version-info`),
  `flex-shrink:0`.
- `agent-zero/webui/components/sidebar/sidebar-store.js:10-13,49-58` —
  collapse state model (`sectionStates: {tasks:false, preferences:false}`,
  localStorage-persisted); untouched by this spec.
- Confirmed via `js/components.js:11-56` — `x-component`/`x-extension`
  are light-DOM fragment injections (`innerHTML`, no Shadow DOM), and
  `index.css:142-151` gives `x-extension` a global `display:contents`
  (non-empty) / `display:none` (empty) base rule. A bare `<x-component>`
  with no matching rule still participates correctly as a flex item
  because flex items are blockified automatically by the flex layout
  algorithm — no new `display:contents` rules are needed purely to make
  `.sidebar-scroll`'s direct `<x-component>` children stack in the new
  column (verified: `.sidebar-bottom-wrapper` already does this today as
  a child of `.left-panel-bottom` with no extra flatten rule).
- Confirmed via test file (`git show HEAD:tests/unit/test_az2_sidebar_nav.py`,
  219 lines) — pinned assertions are pure substring checks on
  `hello-world.html`'s raw text (button labels + `window.openModal(...)`
  URLs + absence of `showPanel`). None assert on CSS classes, DOM
  nesting, or layout. This means the whole restructure below is free to
  change markup/class names in `left-sidebar.html`,
  `tasks-list.html`, `preferences-panel.html`, and the `<style>` blocks
  in `hello-world.html`, as long as every button's label text and
  `openModal` call stays in the file untouched.
- Confirmed no other test references `.section-header`, `.sidebar-action`,
  `left-sidebar`, `chats-list`, `tasks-list`, or `preferences-panel`
  (`git grep` across `tests/**` — the only two hits, in
  `test_cov_backlog_resumehealth.py` and `test_wtpar_ats_parseability.py`,
  are about résumé-text section headers for ATS parsing, unrelated).
- Confirmed `a0-applicant/webui/applicant-theme.css` (which also defines
  `.sidebar-action`, lines 62-84, 212-217) is only `<link>`-loaded inside
  the individual modal panel documents (`main.html`, `today.html`, etc.
  — 37 files), never inside the main webui shell, so it cannot cascade
  into `#applicant-hello-world-nav`. No conflict with the sidebar's own
  `.sidebar-action` rule.

## Decision needed: the "brand header" is not actually in the flex column

The task's target model — "brand = fixed (`flex:0 0 auto`), everything
else = one `flex:1` scroll region" — describes two siblings in the same
flex column. But the real "wordmark + icon row" component
(`header-icons.html`) is **not** a child of `#left-panel` today; it's a
`position:fixed` overlay panel, positioned independently
(`header-icons.html:174-196`, `z-index:1004`), that happens to sit
visually at the same top-left spot. `.left-panel-top`'s `margin-top:
6.5rem` (`left-sidebar.html:91`) is a manual offset that reserves space
so the floating panel doesn't cover the first row — not a real flex
relationship.

This split is deliberate, not an oversight: `header-icons.html` is kept
outside `#left-panel` specifically so it stays visible (as a collapsed
icon rail with a hover-to-peek expansion, `header-icons.html:366-399`)
even when the whole sidebar is toggled closed (`#left-panel.hidden {
margin-left: -250px }`, `left-sidebar.html:77-79`). If it moves inside
`#left-panel`, it would also side-swipe away when the sidebar collapses. This
is real, working functionality this spec must not silently break, and
the task's structural findings never examine `header-icons.html` at all.

**Recommendation: leave `header-icons.html` exactly as-is.** It already
renders as a fixed, non-scrolling element at the top of the sidebar
visually; there is no user-visible difference between "true flex sibling"
and "position:fixed overlay + reserved top offset" for the open-sidebar
case this task is about. Carry the existing `margin-top: 6.5rem` forward
unchanged onto the new unified scroll wrapper (see below) so the reserved
space is preserved with zero regression risk to the collapse/hover-peek
behavior.

*Alternative (not recommended, flag only):* if the product intent really
is to make the header a literal flex child, `.sidebar-shell` would need
to become the flex column (header item 1, `#left-panel`'s scroll content
item 2) and the whole shell — not just the inner content — would need to
collapse/expand together, which changes today's collapsed-sidebar UX
(header no longer independently accessible when collapsed). That's a
product decision, not a layout bug fix; don't implement it under this
spec without separately confirming that trade-off is wanted.

## Recommended implementation

### 1. `agent-zero/webui/components/sidebar/left-sidebar.html`

Markup (currently lines 15-36): merge `.left-panel-top` and
`.left-panel-bottom` into a single wrapper, renamed `.sidebar-scroll` for
clarity (old name is confusing once it holds everything, and nothing
outside this file references `.left-panel-top`/`.left-panel-bottom` —
confirmed via repo-wide grep). Move
`<x-component path="sidebar/bottom/sidebar-bottom.html">` to be the last
item inside the same wrapper, after `#tasks-section`:

```html
<div id="left-panel" class="panel" x-data :class="{'hidden': !$store.sidebar.isOpen}">
  <x-extension id="sidebar-start"></x-extension>
  <div class="sidebar-scroll">
    <x-component path="sidebar/top-section/sidebar-top.html"></x-component>

    <!-- Chats: kept in the scroll flow for now (interim; see note below),
         not restyled — the separate Chats-removal workstream owns deleting
         this block outright. -->
    <div class="config-section" id="chats-section">
      <x-component path="sidebar/chats/chats-list.html"></x-component>
    </div>

    <div class="config-section" id="tasks-section">
      <x-component path="sidebar/tasks/tasks-list.html"></x-component>
    </div>

    <x-component path="sidebar/bottom/sidebar-bottom.html"></x-component>
  </div>
  <x-extension id="sidebar-end"></x-extension>
</div>
```

CSS changes:

- Delete the `.left-panel-bottom` rule (old lines 95-100) entirely.
- Replace `#left-panel>.left-panel-top, #left-panel>.left-panel-bottom {
  display:flex; flex-direction:column }` (old lines 64-69) with a single
  `#left-panel>.sidebar-scroll { display:flex; flex-direction:column }`.
- Replace `#left-panel>.left-panel-top { flex:1; min-height:0 }` (old
  lines 71-75) with the same selector renamed:
  `#left-panel>.sidebar-scroll { flex:1; min-height:0 }` (can merge with
  the rule above).
- Replace the `.left-panel-top` rule (old lines 81-93) with:
  ```css
  .sidebar-scroll {
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow-y: auto;
    margin-top: 6.5rem;               /* unchanged: clears the fixed header-icons panel */
    padding: var(--spacing-md) var(--spacing-md) var(--spacing-md) var(--spacing-md);
  }
  ```
  (Dropped: `overflow:hidden` → `overflow-y:auto` — this is the actual
  fix. Dropped: `justify-content:space-between`, a vestige of the old
  two-sibling top/bottom split that no longer applies with one child
  chain. Also drop the `no-scrollbar` class from the div in the markup
  above so the sidebar picks up the site's normal thin scrollbar,
  consistent with `#right-panel` — `index.css:1601-1627`.)
- `#chats-section` (old lines 103-112): change to
  `flex: 0 0 auto; overflow: visible;` (drop `max-height:100%` and
  `overflow:hidden` — it no longer needs to protect a bounded parent,
  and dropping the constraint lets `.chats-config-list`'s own
  `max-height:100%` resolve to `none` against an auto-height ancestor,
  which naturally kills its inner scrollbar since 100% keeps computing against
  an auto-height parent). Do not touch `chats-list.html` itself — this
  is the interim, minimum-effort fix; the separate Chats-removal
  workstream deletes this whole block later.
- `#tasks-section` (old lines 115-127): change to
  `flex: 0 0 auto; overflow: visible;` (drop `max-height:40%` and
  `overflow:hidden` for the same reason).
- `#tasks-section .collapse` (old lines 138-144): change `flex:1;
  min-height:0` → `flex:0 0 auto` (it should size to its content now,
  not stretch to fill a bounded parent). Leave `#tasks-section
  .collapsing { flex:0 0 auto !important }` (old 146-149) as-is — no
  change needed, already correct for the new model.
- `.section-header` / `.section-header-collapsible` (old lines 151-173):
  delete this rule block outright. Its job (uppercase small-caps look) is
  exactly what the new design removes; row styling for these headers now
  comes from the extended selector in `hello-world.html` (step 3 below).
- `@media (max-height: 600px)` block (old lines 197-207): delete. Both
  overrides it contained (`#chats-section{min-height:100%}` and
  `.left-panel-top{overflow-y:auto}`) are now redundant — the base rules
  already do this unconditionally.

### 2. `agent-zero/webui/components/sidebar/top-section/sidebar-top.html`

No change required. `.sidebar-top-wrapper`'s `flex-shrink:0` (line 25,
i.e. `flex:0 0 auto`) was flagged in the structural findings as part of
the clipping chain, but it's actually fine once its ancestor
(`.sidebar-scroll`) genuinely scrolls — a `flex:0 0 auto` item just means
"size to your content," which is correct for the nav block once nothing
above it is forcing a `max-height`.

### 3. `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`

First `<style>` block (lines 167-200, scoped to
`#applicant-hello-world-nav`):
- Delete lines 173-176 (`grid-column: 1 / -1; max-height: 45vh; overflow-y:
  auto;` and the comment above them) — no more inner scroll box, no more
  grid-column escape (the grid-column hack becomes moot too, see note
  below on `quick-actions.html`).
- Leave `.sidebar-action` rule (180-187) and its `:hover`/icon rules
  (188-193) as-is — this already matches the ask exactly (13px, 400,
  padding via the global override below, hover background).
- Leave `.sidebar-group-label { display:none }` (197-199) as-is —
  correctly already hidden, kept in DOM per its own comment for the
  pinned test's benefit.

Second `<style>` block (lines 203-209, the "unified sidebar visual
system"):
- Delete line 205 (`#left-panel .section-header, #left-panel h3 {
  text-transform:uppercase; ... }`) — this is the uppercase-grey
  treatment the new design explicitly forbids.
- Extend line 206's selector to also cover the (now de-uppercased)
  section headers, so Tasks/Preferences get exactly the same row look as
  every nav button and chat/task row:
  ```css
  #left-panel .sidebar-action,
  #left-panel .chat-container,
  #left-panel .task-container,
  #left-panel .section-header {
    display: flex !important;
    align-items: center !important;
    gap: 10px !important;
    padding: 6px 16px !important;
    font-size: 13px !important;
    font-weight: 400 !important;
    color: rgba(255, 255, 255, .9) !important;
    text-align: left !important;
  }
  ```
  (Identical values to today's line 206 — only the selector list grows.
  Confirms the padding/font/color values in the task brief were already
  implemented; the gap was purely that `.section-header` wasn't in this
  selector.)
- Line 207's icon-color rule: add `.section-header .material-symbols-outlined`
  to the same selector list, for the leading icons added to Tasks/
  Preferences in step 4/5 below.
- Leave `.empty-list-message` rule (208) untouched.

### 4. `agent-zero/webui/components/sidebar/tasks/tasks-list.html`

- Markup (lines 12-20): add a leading icon span so the Tasks row matches
  the icon+label pattern of every other row, and drop the now-redundant
  `section-header-collapsible` typographic hook (styling comes from the
  shared rule in step 3; the class can stay for the `data-bs-toggle`
  cursor/semantics if convenient, purely cosmetic either way):
  ```html
  <h3 class="section-header section-header-collapsible"
      data-bs-toggle="collapse"
      @click="$store.sidebar.toggleSection('tasks')"
      x-effect="!$store.sidebar.isSectionOpen('tasks') ? $el.classList.add('collapsed') : $el.classList.remove('collapsed')">
    <span class="material-symbols-outlined">checklist</span>
    <span class="label">Tasks</span>
    <svg class="arrow-icon" ...>...</svg>
  </h3>
  ```
  (Icon choice `checklist` is a suggestion, not load-bearing — pick
  whatever reads well next to the nav icons; not covered by the pinned
  test either way.) Give the row `justify-content: space-between` (see
  CSS below) so label+icon sit left and the chevron sits right, matching
  the existing accordion-toggle pattern already used in
  `header-icons.html:342-360` for "Chat Actions."
- CSS: delete `.tasks-list-container .section-header { position: sticky;
  top: 0; flex-shrink: 0; z-index: 10 }` (lines 89-94) — no more sticky
  sub-header; it's a form of visual distinction the new design doesn't
  want. Add `justify-content: space-between;` to the (now-shared)
  `.section-header` treatment via a scoped rule here:
  `.tasks-list-container .section-header { justify-content:
  space-between; cursor: pointer; }` (cursor was implicit before via
  `.section-header-collapsible`; keep it explicit since that class's
  visual role is going away).
- CSS: `.tasks-list-body` (line 83-88, `flex:1 1 auto; min-height:0`) →
  change to `flex: 0 0 auto` (content-sized, not stretch-to-fill).
- CSS: `.tasks-list-container` (line 96-103, `flex:1; min-height:0;
  overflow:hidden`) → change to `flex: 0 0 auto; overflow: visible;`.
- CSS: `.tasks-config-list` (line 106-113, `flex:1; min-height:0;
  overflow-y:auto; ...`) → change to `flex: 0 0 auto; overflow:
  visible;` — the whole task list now lays out to natural height inside
  the one outer scroll.
- Leave `.task-container` (139-152) untouched — already correct per the
  global override in `hello-world.html` (step 3).
- Not in scope, flagging only: the duplicate `</template></div>` at
  lines 70-73 is dead markup pre-dating this task; harmless (browsers
  silently drop unmatched closing tags) and unrelated to the flex fix.
  Worth a follow-up cleanup, not required here.

### 5. `agent-zero/webui/components/sidebar/bottom/preferences/preferences-panel.html`

- Markup (lines 12-20): same treatment as Tasks — add a leading icon and
  keep the label/chevron:
  ```html
  <h3 class="section-header section-header-collapsible pref-header"
      data-bs-toggle="collapse"
      @click="$store.sidebar.toggleSection('preferences')"
      x-effect="!$store.sidebar.isSectionOpen('preferences') ? $el.classList.add('collapsed') : $el.classList.remove('collapsed')">
    <span class="material-symbols-outlined">tune</span>
    <span class="label">Preferences</span>
    <svg class="arrow-icon" ...>...</svg>
  </h3>
  ```
- CSS: add `.pref-header { justify-content: space-between; cursor:
  pointer; }` alongside the existing `.pref-section` rules (this file has
  no sticky-header rule to remove, unlike Tasks).
- Leave everything below the header (the `<ul class="config-list ...">`
  of Dark mode / Width / Detail / Speech / Show utility messages toggles,
  lines 21-75) and its CSS (94-204) untouched. These are settings-form
  controls, not navigable rows — out of scope for the "uniform row" ask,
  which targets the top-level list entries (Setup…Help, Tasks,
  Preferences), not Preferences' own nested switches.

### 6. `agent-zero/webui/components/sidebar/bottom/sidebar-bottom.html`

- CSS: `.sidebar-bottom-wrapper { flex-shrink: 0 }` (line 30) can stay
  as-is — it's now just a normal block flowing at the end of
  `.sidebar-scroll`'s column instead of the end of a separate
  `.left-panel-bottom` sibling; `flex-shrink:0` is harmless/still correct
  (nothing here needs to shrink).
- `.version-info` (34-47): no change. It will now scroll with the rest
  of the list instead of being pinned to the viewport bottom — this is
  an intended consequence of "everything reads as one list," not a
  regression (it's a static label, not interactive functionality).

### 7. `agent-zero/webui/components/sidebar/top-section/quick-actions.html`

No required change. Optional cleanup: once
`#applicant-hello-world-nav` no longer needs `grid-column: 1 / -1` (step
3 removes that rule along with the max-height/overflow it was paired
with), it's still sitting inside `#quick-actions`'s `display:grid;
grid-template-columns: repeat(5, 1fr)` (lines 28-35) via
`display:contents` flattening. That still works exactly as it does
today (the existing `grid-column:1/-1` override — being removed — was
solving a *different* problem, spanning across grid columns, not
related to the scroll fix); leaving `#quick-actions` untouched is safe
and lower-risk. If the extension nav no longer needs grid layout at all
(it's a single vertical stack of buttons, not a toolbar grid), an
optional deeper cleanup would replace `#quick-actions`'s CSS grid with a
simple flex column — but nothing in this task requires that, and other
extensions may rely on the grid for icon-toolbar-style content dropped
into the same slot (`#sidebar-quick-actions-main-start`,
`#sidebar-quick-actions-main-end`), so don't change it without checking
for other consumers of that slot first.

## Result

```
.sidebar-shell
├─ <x-component .../header-icons.html>   UNCHANGED — position:fixed overlay, wordmark + icon row
└─ #left-panel                            height:100vh; overflow:hidden (unchanged container)
   ├─ x-extension#sidebar-start           unchanged
   ├─ .sidebar-scroll                     flex:1; min-height:0; overflow-y:auto  ← THE single scroll region
   │  ├─ sidebar-top.html → quick-actions.html → hello-world.html nav rows (no inner scroll)
   │  ├─ #chats-section                   flex:0 0 auto; overflow:visible (interim, unstyled, pending removal)
   │  ├─ #tasks-section                   flex:0 0 auto; overflow:visible; uniform disclosure row + rows
   │  └─ sidebar-bottom.html → preferences-panel.html (uniform disclosure row + controls) + version-info
   └─ x-extension#sidebar-end             unchanged
```

This satisfies: brand fixed at top (unchanged, already fixed via
`position:fixed`, functionality preserved), one scroll region filling
100% of the remaining height (`.sidebar-scroll`, `flex:1; min-height:0;
overflow-y:auto`), all Applicant nav + Tasks + Preferences rows visually
uniform (13px/400/rgba(255,255,255,.9)/padding 6px 16px/border-radius
6px/hover `var(--color-background-hover)` — all already-correct values
in `hello-world.html:206`, now applied to `.section-header` too), no
uppercase-grey section headers, and the pinned test untouched (no button
label, `openModal` URL, or `showPanel` string is touched anywhere in
this spec).

## Out of scope / do not confuse with this task

- Chats list removal/replacement with a single conversation entry —
  separate workstream, per the task brief. This spec only stops
  `#chats-section` from being independently clipped in the interim; it
  does not restyle or remove it.
- `header-icons.html`'s position:fixed / hover-expand mechanism — see
  "Decision needed" above. Not changed by this spec.
- Preferences' nested settings controls (Dark mode, Width, Detail mode,
  Speech, Show utility messages) — a form UI, not a navigable row, left
  as-is.
- The pre-existing duplicate closing-tag bug in `tasks-list.html:70-73`
  — unrelated dead markup, flagged for a separate cleanup.
- Light-mode color: the row color spec (`rgba(255,255,255,.9)`) is a
  hardcoded dark-theme value, already present verbatim in
  `hello-world.html:206` today. This spec does not add or fix light-mode
  handling — that condition pre-dates this task.

## Files touched by this change (spec only — none edited yet)

- `agent-zero/webui/components/sidebar/left-sidebar.html` — markup
  restructure (merge top/bottom into `.sidebar-scroll`), flex/overflow
  rewrite, delete `.section-header` uppercase rule and the
  `@media(max-height:600px)` block.
- `agent-zero/webui/components/sidebar/tasks/tasks-list.html` — add
  leading icon to Tasks header, drop sticky positioning, flex/overflow
  rewrite (`flex:0 0 auto; overflow:visible` throughout the collapse
  chain).
- `agent-zero/webui/components/sidebar/bottom/preferences/preferences-panel.html`
  — add leading icon to Preferences header, add
  `justify-content:space-between`.
- `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`
  — remove the nav's own `max-height:45vh; overflow-y:auto` escape
  hatch, delete the uppercase `.section-header` override, extend the
  existing row-style selector to include `.section-header`.
- No change needed: `agent-zero/webui/components/sidebar/top-section/sidebar-top.html`,
  `.../top-section/quick-actions.html`,
  `.../bottom/sidebar-bottom.html`,
  `.../chats/chats-list.html`, `.../sidebar-store.js`,
  `.../top-section/header-icons.html`.
- Not touched, verified safe: `tests/unit/test_az2_sidebar_nav.py`.
