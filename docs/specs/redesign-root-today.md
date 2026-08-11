# Redesign: root/landing view = Today

Status: SPEC (not implemented). Read-only investigation, no source files changed.

## Problem

Landing on the Applicant app (no chat selected) shows a generic AI-console
welcome screen — "Hello! I'm Applicant 👋" hero + a "Quick Actions" grid
(Projects / Memory / Tasks / Files / Settings / Plugins / Visit Website).
None of this reflects daily campaign state. The actual daily-review surface
("Today" — pending actions: digest approvals, material reviews, missing
attributes, etc.) exists but is buried a click away in the sidebar nav
(`Applicant > Today`), opened as a modal.

Goal: landing on the app = the Today view, unified into the root, with the
chat composer still present and usable (chat is core to the product, not a
side feature).

## How root/landing is currently chosen

- `agent-zero/webui/index.html:90-122` — the right panel has two
  mutually-exclusive slots, both keyed off one Alpine store getter:
  - `index.html:95-98`: `<div x-show="$store.welcomeStore && $store.welcomeStore.isVisible"><x-component path="welcome/welcome-screen.html">` — the welcome/root screen.
  - `index.html:99-100` and `:116-122`: `#chat-history` + the bottom
    `chat-bar.html` composer, shown when `!isVisible`, i.e. a chat is open.
- `agent-zero/webui/components/welcome/welcome-store.js:17-19`:
  ```js
  get isVisible() {
    return !chatsStore.selected;
  }
  ```
  `chatsStore.selected` (`agent-zero/webui/components/sidebar/chats/chats-store.js:19,290`)
  is `""` until a chat context is selected. So "root" = "no chat selected",
  and it reverts to root automatically whenever the user has no open chat
  (fresh load, after closing/deleting the active chat, etc.) — this is the
  existing, correct hook point; nothing about *when* root shows needs to
  change.
- The welcome screen's own composer is a **separate embed** of the chat
  input, not the bottom bar: `welcome-screen.html:22-25`
  (`<x-component path="chat/attachments/inputPreview.html">` +
  `<x-component path="chat/input/chat-bar-input.html">`), inside
  `<section class="welcome-composer">`. This is what must be preserved.
- The hero + Quick Actions to be replaced live in
  `agent-zero/webui/components/welcome/welcome-screen.html`:
  - Hero: lines **17-20** (`<header class="welcome-hero">…</header>`).
  - Quick Actions grid: lines **73-134**
    (`<section class="welcome-quick-section">…</section>`).
  - Left untouched: composer (22-25), banners/alerts section (27-71,
    important — surfaces missing-API-key/system warnings), and the
    system-resources card in `welcome-lower-grid` (136-171).

## How Today is normally opened

- Sidebar nav button: `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html:7-10`:
  ```html
  <button class="sidebar-action" @click="window.openModal('/plugins/applicant/webui/today.html')">
  ```
- `window.openModal` (`agent-zero/webui/js/modals.js:137,369`) creates a
  modal shell (`createModalElement`, `modals.js:76-125`) and calls
  `importComponent(modalPath, modal.body)` (`modals.js:172`) to fetch and
  inject the fragment. **`importComponent` is generic** — it's not
  modal-specific; it fetches an HTML fragment, inlines its `<style>`/`<script>`
  nodes into whatever `targetElement` it's given
  (`agent-zero/webui/js/components.js:11-176`), and returns. Any element
  works as the target, not just a modal body.
- `a0-applicant/webui/today.html` (143 lines) is exactly such a
  self-contained fragment: scoped `.atoday` CSS (lines 6-31), markup
  (33-69), and a plain `<script>` (71-143) that registers
  `window.Alpine.data("todayPanel", () => ({...}))` and calls
  `this.loadItems()` from `init()` (line 96-98), hitting
  `plugins/applicant/pending` (`action: "list"`) for pending-action items,
  with resolve/snooze/resolve-all actions.
- Embedding is trivial and already proven elsewhere in this exact file:
  `<x-component path="...">` tags are processed by a **global
  `MutationObserver`** watching `document.body` for added nodes matching
  `x-component` (`agent-zero/webui/js/components.js:246-260`), not by
  `importComponent` recursing into its own output — nesting one
  `x-component` inside another (already done at welcome-screen.html:23-24
  for the chat input) "just works" because the observer picks up newly
  inserted `x-component`/`x-extension` nodes anywhere in the DOM.

## Options considered

**(a) Render Today inline, alongside the existing hero/actions.**
Rejected — doesn't solve the actual complaint (clutter/indirection); just
adds a third block to an already busy screen.

**(b) Auto-open the Today modal on load (`openModal(...)` from
`welcome-store.js` `onCreate()` or an `x-init`).**
Rejected — a modal-on-top-of-a-welcome-screen is not "unified," it's a
forced click-through (must dismiss to reach the hero/composer), and it
fights the modal's own `modal-closed` event plumbing
(`welcome-store.js:26-30` already listens for that event to refresh
banners — auto-opening Today would re-trigger that loop every time the
user closes it while still on root).

**(c) Replace the hero + Quick Actions with the Today surface, keep the
chat composer. RECOMMENDED.**
Directly satisfies the ask: landing = Today, chat stays accessible, no
extra click, no modal stacking. It also matches the file's existing
convention — this fork already hardcodes Applicant-specific content
straight into `welcome-screen.html` (the "Hello! I'm Applicant" hero
itself is a hardcoded string, not an extension), so a direct edit here is
consistent with how this screen is already maintained, not a deviation
from it.

Note on the extension-point (`<x-extension id="welcome-actions-start">` /
`welcome-actions-end"`, `welcome-screen.html:76,137`) alternative: these
slots only let a plugin **add** markup before/after the existing
hero/grid — there's no slot that lets a plugin **remove or replace** them.
Since (c) requires removing the hero and grid outright, a direct edit to
`welcome-screen.html` is unavoidable regardless of approach; extensions
can't achieve this task.

## Recommended implementation

### 1. `agent-zero/webui/components/welcome/welcome-screen.html`

- Delete the hero block, lines **17-20**:
  ```html
  <header class="welcome-hero">
      <h1>Hello! I'm Applicant <span aria-hidden="true">&#128075;</span></h1>
      <p x-text="$store.welcomeStore.heroSubtitle"></p>
  </header>
  ```
  (Optionally keep a slim greeting line above the composer instead of
  deleting outright — e.g. fold `heroSubtitle` into an
  `aria-label`/visually-hidden string on `.welcome-composer` — but a full
  removal is simplest and matches "replace hero+quick-actions".)

- Replace the Quick Actions section, lines **73-134**
  (`<section class="welcome-quick-section">…</section>`), with:
  ```html
  <section class="welcome-today" aria-label="Today">
      <x-component path="/plugins/applicant/webui/today.html"></x-component>
  </section>
  ```
  Drop a `.welcome-today { width: 100%; }`-style rule near the existing
  `.welcome-composer` CSS (~line 238-240) if the `.atoday` fragment's own
  `max-width:760px;margin:0 auto` (today.html:7) needs a wrapper — it
  likely doesn't, since it centers itself, but confirm in-browser.

- Leave the banners/alerts section (27-71) and `welcome-lower-grid`
  (136-171, system resources) in place — out of scope for this change and
  still useful (e.g. missing-API-key warnings must stay visible on root).

### 2. Freshness fix (required for correctness, not cosmetic)

`welcome-screen.html`'s outer node is only shown/hidden via `x-show`
(`index.html:96`) — the DOM is **not destroyed and recreated** when
toggling away from and back to root (only `template x-if="$store.welcomeStore"`
at `welcome-screen.html:11` gates real mount/unmount, and that condition
never flips once the store exists). That means the nested
`<x-component path="today.html">`'s Alpine `todayPanel()` instance mounts
**once** and its `init()` → `loadItems()` fires once — pending-action
counts will go stale after the user opens a chat and returns to root,
undermining the "unified daily view" goal.

`welcome-store.js` already solves this exact problem for banners via a
`$watch` in `welcome-screen.html:12`:
```html
x-init="$store.welcomeStore.init(); if ($store.welcomeStore.isVisible) { $store.welcomeStore.onCreate(); } $watch('$store.welcomeStore.isVisible', (visible) => { if (visible) { $store.welcomeStore.onCreate(); } });"
```
Mirror it for Today:

- In `welcome-screen.html`, extend the same `x-init` (or add a sibling
  `$watch`) to dispatch a DOM event when `isVisible` flips true:
  ```js
  $watch('$store.welcomeStore.isVisible', (visible) => { if (visible) { $store.welcomeStore.onCreate(); window.dispatchEvent(new CustomEvent('applicant:refresh-today')); } });
  ```
- In `a0-applicant/webui/today.html`, add a listener in `init()`
  (around line 96-98) so the existing Alpine component picks it up:
  ```js
  async init() {
    await this.loadItems();
    window.addEventListener('applicant:refresh-today', () => this.loadItems());
  },
  ```
  (Fine to leave the listener un-removed — the fragment is loaded once
  per page session, same lifetime as the event target.)

### 3. Nice-to-have (not required to close this task)

- Highlight the "Today" sidebar nav item as active while on root, since
  root now *is* Today (`a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html:7-10`).
- A settings toggle to opt back into the old hero/Quick-Actions view,
  if some users want it — no evidence this was requested; skip unless
  asked.

## Out of scope / do not confuse with this task

`docs/backlog/road-to-market.md` and `docs/proof/demo-script.md` describe
a *separate*, standalone "Portal" web app (`static/js/applicantPortal.js`,
hash-routed `#portal`, its own "Today" nav concept via `applicantNav.js:72`)
that is not part of the agent-zero-based webui investigated here. That is
a different frontend entirely (matches the user's own notes that Applicant
has its own standalone product stack, separate from any agent-zero
console). This spec only concerns the agent-zero-webui root/welcome
screen (`agent-zero/webui/...`, `a0-applicant/webui/today.html`) that the
task explicitly pointed at — the literal "Hello! I'm Applicant" screen.
Don't conflate the two when implementing.

## Files touched by this change (spec only — none edited yet)

- `agent-zero/webui/components/welcome/welcome-screen.html` (remove hero
  17-20, replace quick-actions 73-134, extend `$watch` at line 12)
- `a0-applicant/webui/today.html` (add refresh-event listener in `init()`,
  ~line 96-98)

No backend changes needed — `today.html` already calls the live
`plugins/applicant/pending` API for list/resolve/snooze/resolve_bulk.
