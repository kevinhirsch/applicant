# Work order: fix Applicant sidebar/panel theming bugs

**Branch:** `claude/refactor-agent-zero-applicant-xn7xoc` (you are already on it). Commit locally, **do NOT push**.
**Scope:** exactly the edits below. Do the minimal change. Do not refactor anything not listed. Do not touch any file not named here.

## The three reported bugs (from the running UI)
1. **Light-mode flip** — clicking some Applicant panels flips the WHOLE app from dark to light.
2. **Nav buttons look like white chips** — the "Applicant" sidebar buttons render with native white/gray button chrome, crammed into a narrow column, clashing with the dark sidebar.
3. **Bottom nav item clipped** — the last buttons (from "Criteria" down) are cut off with no scrollbar.

---

## FIX A — sidebar nav (fixes bugs 2 and 3). File: `a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html`

**HARD CONSTRAINT:** `tests/unit/test_az2_sidebar_nav.py` pins every button and label in this file. You must NOT change, rename, reorder, add, or remove any `<button>`, any `.label` text, or the `data-extension-id="applicant-hello-world"` attribute. You may ONLY (a) add an `id` to the existing wrapper `<div>` and (b) append a `<style>` block. Run that test after editing and it must still pass.

1. On the existing top-level wrapper `<div data-extension-id="applicant-hello-world">`, add an id so it becomes:
   `<div id="applicant-hello-world-nav" data-extension-id="applicant-hello-world">`
   (keep `data-extension-id` exactly as-is — the test checks it).

2. Append this `<style>` block to the end of the file. It mirrors A0's own already-correct dark row pattern (`agent-zero/webui/index.css` `.dropdown-item`/`.dropdown-header`) and uses ONLY A0's real theme tokens, so it always matches the live theme and can never leak a color:

```html
<style>
  /* Applicant nav: span full sidebar width, stack vertically, own scroll. */
  #applicant-hello-world-nav {
    display: flex;
    flex-direction: column;
    grid-column: 1 / -1;      /* was crammed into 1 of 5 grid columns */
    gap: 2px;
    max-height: 45vh;         /* bug 3: bound height so it can't be clipped */
    overflow-y: auto;         /* ...and expose its own scrollbar instead */
  }
  #applicant-hello-world-nav .sidebar-action {
    display: flex; align-items: center; gap: var(--spacing-sm);
    width: 100%; padding: var(--spacing-sm) var(--spacing-md);
    background: transparent; border: none; border-radius: 0.4rem;
    color: var(--color-text); font-family: var(--font-family-main);
    font-size: var(--font-size-small); text-align: left; opacity: .8;
    cursor: pointer; transition: background-color .15s ease; white-space: nowrap;
  }
  #applicant-hello-world-nav .sidebar-action:hover {
    background-color: var(--color-background-hover); opacity: 1;
  }
  #applicant-hello-world-nav .sidebar-group-label {
    padding: var(--spacing-xs) var(--spacing-md);
    font-size: .7rem; color: var(--color-primary);
    text-transform: uppercase; letter-spacing: .05em; opacity: .8;
  }
</style>
```

If any `.sidebar-action` button contains an icon element (svg/img), leave it — `display:flex; align-items:center; gap` already lays icon+label correctly.

---

## FIX B — shared panel stylesheet (fixes bug 1, categorical). File: `a0-applicant/webui/applicant-theme.css`

This file currently declares, in its own `:root {…}`, the SAME custom-property names that A0's shell owns (`--color-primary`, `--color-text`, `--color-background`, `--color-panel`, `--color-border`) but hard-coded to a LIGHT palette. If this sheet is ever attached to the live document, those win the cascade and flip the whole app light. Neutralize it:

1. In the `:root { … }` block, for each of these five properties — `--color-primary`, `--color-text`, `--color-background`, `--color-panel`, `--color-border` — **rename** it to an `--ap-`-namespaced name AND make it inherit A0's real token with the old hex as fallback. E.g.:
   - `--color-text: #2c2c2c;` -> `--ap-color-text: var(--color-text, #2c2c2c);`
   - `--color-background: #f5f7fa;` -> `--ap-color-background: var(--color-background, #f5f7fa);`
   - `--color-panel: #e8ecf1;` -> `--ap-color-panel: var(--color-panel, #e8ecf1);`
   - `--color-border: #d4d9e0;` -> `--ap-color-border: var(--color-border, #d4d9e0);`
   - `--color-primary: #4361ee;` -> `--ap-color-primary: var(--color-primary, #4361ee);`
   (Any OTHER `--` vars in this `:root` that do NOT collide with A0's names — leave them unchanged.)
2. Update **every reference** within THIS file that used the old names (`var(--color-text)` -> `var(--ap-color-text)`, etc.).
3. **Delete** the rule that targets the real document `body { … }` (it sets `background`/`color` on the actual page body — a plugin sheet must never style `body`/`html`). The panel-scoped rules elsewhere in the file already set color on the panel root classes.
4. In the selector `.btn, .sidebar-action, button { … }`, **remove the bare `button` element selector** (keep `.btn, .sidebar-action`). The bare `button` restyles every button in the whole A0 shell.

After editing, `grep -nE '\-\-color-(primary|text|background|panel|border)\b' a0-applicant/webui/applicant-theme.css` must return **only** occurrences that are the fallback inside `var(--color-x, …)` — no bare `var(--color-text)` uses and no bare `--color-text:` definitions should remain.

---

## FIX C — kill the confirmed bleed path. Files: `a0-applicant/webui/help.html` AND `a0-applicant/webui/shortcuts.html`

These two are full `<!DOCTYPE html>` documents (not fragments); their `<style>` blocks are reliably captured by the panel loader and contain a bare `body { … }` rule (e.g. `body { color: #1a1a2e; … }`) that bleeds a hardcoded color into the real app body when opened.

In each file, **change the bare `body` selector in the `<style>` block to the panel's own root wrapper class** (use whatever top-level class that panel's markup already has, mirroring how `notifications.html`/`main.html` scope their styles to `.anotifications`/`.aoobe`). If a rule is purely a `body { … }` reset with nothing panel-specific, scope it to that panel root class. Do NOT leave any bare `body { … }` or `html { … }` rule in these files.

---

## EXPLICITLY OUT OF SCOPE (do NOT do these now)
- Do NOT change the top-of-file `<link rel="stylesheet" href="…applicant-theme.css">` in the other panel fragments to `@import`. Leave every panel's `<link>` as-is.
- Do NOT edit any file under `agent-zero/webui/` (A0 core). This fix is plugin-only.
- Do NOT touch any panel other than help.html and shortcuts.html.

## Verify before committing
1. `cd /a0/usr/projects/applicant && python -m pytest tests/unit/test_az2_sidebar_nav.py -q` -> must pass.
2. `grep -nE '\-\-color-(primary|text|background|panel|border)\b' a0-applicant/webui/applicant-theme.css` -> only `var(--color-x, fallback)` fallback forms remain.
3. `grep -nE '^\s*(body|html)\s*[,{]' a0-applicant/webui/help.html a0-applicant/webui/shortcuts.html a0-applicant/webui/applicant-theme.css` -> **no matches** (no bare body/html rules left in these three files).
4. Report the exact files changed and the diff summary.

## Commit
One focused commit on the current branch (no push):
`fix(ui): dark-theme the Applicant sidebar nav (full-width, scrollable, A0 tokens) + stop panel stylesheet from flipping the app to light mode [FR-UI]`
