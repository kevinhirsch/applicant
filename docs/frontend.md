# Frontend: how to add a surface

Applicant's own surfaces live under `frontend/static/applicant/` and are served by
the `ui` router (`src/applicant/app/routers/ui.py`). They are deliberately
**vanilla, no-build** — they reuse the vendored MIT Applicant design system the same
way Applicant itself does (hand-authored HTML + ES modules, no bundler, no new
runtime deps). Two requirements govern the look:

- **FR-UI-1 — pixel-faithful clone.** Surfaces reuse the vendored design-system
  classes from `../style.css`. Do not restyle the design system; do not fork its
  files. Our only stylesheet is `applicant.css`.
- **FR-UI-2 — scaffold-and-gray.** A surface (or section) whose backend is not yet
  wired is present but dormant, grayed via `.applicant-dormant`, never shown as if
  live.

## The shared module: `js/applicant-ui.js`

One small ES module centralizes what every surface needs, so each page is just its
content plus a one-line import. It exports (and bundles as `ApplicantUI`):

- `apiFetch(path, opts)` — JSON `fetch` with shared error handling **and the
  LLM-gate redirect (FR-UI-5)**: a `409` from the setup / automated-work gate routes
  the user to the wizard (the wizard itself is exempt — it is how the gate opens).
  Returns parsed JSON, or `null` for `204`.
- `mountShell({ active })` / `mount({ active })` — inject the shared Applicant-styled
  nav into a `#applicant-nav` container (opt-in: surfaces without that container
  render unchanged), marking the active link.
- `el(tag, attrs, children)` — the tiny DOM builder shared by every surface's glue.
- Design-system component helpers that reuse the vendored CSS: `openModal` /
  `closeModal` (toggle `.hidden` on a `.modal`), `bindToggle` (wire a
  `.toggle-switch` input, reverting on failure), and `toast` (the `.toast` notice).

The surface list lives in one place — the `SURFACES` array in `applicant-ui.js`.

## Recipe: add a new surface

1. **HTML fragment** — `frontend/static/applicant/<name>.html`: the page content
   only, using existing design-system classes (`.admin-card`, `.admin-btn`,
   `.admin-badge`, `.toggle-switch`, …). Link both stylesheets in `<head>`:

   ```html
   <link rel="stylesheet" href="../style.css" />   <!-- vendored, do not edit -->
   <link rel="stylesheet" href="applicant.css" />  <!-- our shared styles -->
   ```

   End the body with a module script:

   ```html
   <script type="module" src="./js/<name>.js"></script>
   ```

2. **Glue module** — `frontend/static/applicant/js/<name>.js`:

   ```js
   import { ApplicantUI, apiFetch, el } from "./applicant-ui.js";
   document.addEventListener("DOMContentLoaded", () => {
     ApplicantUI.mountShell({ active: "<name>" });
     // ... use apiFetch / el / ApplicantUI.toast / bindToggle ...
   });
   ```

   Use `apiFetch` for every call so the surface shares the gate redirect and
   graceful-degradation behavior. Never present a failed fetch as live data
   (FR-UI-2) — show a note instead.

3. **Nav entry** — add `{ key, href, label }` to `SURFACES` in `applicant-ui.js`.

4. **Route** — add a handler in `src/applicant/app/routers/ui.py` that serves the
   new file (mirror the existing `wizard` / `digest` / … handlers).

5. **Dormant?** If the backend is not wired yet, wrap the section in
   `class="applicant-dormant" aria-disabled="true"` and badge it
   `.admin-badge-off` so it is visibly grayed (FR-UI-2), exactly like the existing
   dormant sections in `digest.html` / `debug.html`.

## Styling rules

- All `applicant-*` / `review-*` / `chat-*` rules live in **`applicant.css`** — one
  source of truth. No per-file `<style>` blocks.
- `applicant.css` also defines the two `.admin-*` classes the canonical MIT CSS is
  missing — `.admin-btn` (sibling of `.admin-btn-add`) and `.admin-badge-on`
  (sibling of `.admin-badge-off`) — so surfaces using the bare classes render like
  their suffixed siblings.
- Never edit the vendored design system: `style.css`, `app.js`, `js/`, `lib/`,
  `fonts/`, `css/`, `index.html`, `login.html`, `sw.js`, `manifest.json`.
