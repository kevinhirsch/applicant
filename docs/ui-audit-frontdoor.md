# Front-Door HCI Design Audit — Applicant white-labeled UI

A theory-grounded UI/UX audit of the **white-labeled front-door** (`workspace/`), conducted with
autonomous visual telemetry (headless Chromium + Playwright) against a live stack, across the user's
state journey at two breakpoints. This is the reachability surface the product is judged on
(CLAUDE.md principle #2), so the audit targets `workspace/`, not the engine's internal `frontend/`.

## Method & environment

- **Live stack** stood up in-container: engine (`applicant.app.main:app`, Postgres 16, shim
  orchestrator) on `:8000`; front-door (`workspace/app.py`, SQLite) on `:7000` pointed at the engine
  via `ENGINE_URL`. Setup advanced to `current_step=onboarding` (LLM via OpenRouter configured,
  channels + sandbox + fonts complete) so the engine reports `engine_available:true` and sections
  resolve to real `active`/`locked` states rather than a blanket offline.
- **Telemetry**: `.audit-telemetry/capture*.js` (ephemeral, git-ignored) logs in once, then opens each
  surface in its own context and writes full-page PNGs at **Desktop 1440×900** and **Mobile 375×812**.
  Surfaces that open as JS modals (`#applicant-portal-modal`, `-chat-`, `-vault-`, `-remote-`) are
  driven via their `window.*` hooks and awaited on the modal element, not blind rail-clicks.
- **States captured**: login (logged-out), OOBE wizard ("Your profile" intake), Settings,
  Job Assistant chat, Pending-Actions Portal, Saved sign-ins (vault), Live application session
  (remote) — plus the workspace shell with its progressive section gating (`chat`/`email`/`debug`
  active, `documents`/`memory` locked, `compare` disabled).

## Lenses applied

1. **Spatial equilibrium & wayfinding** — visual hierarchy, flow, dead-ends, clutter.
2. **Gestalt** — proximity, similarity, enclosure, figure-ground, negative space.
3. **Cognitive load & affordance** — Sweller intrinsic/extraneous load; Norman/Gibson signifiers.
4. **Viewport agnosticism & micro-interactions** — 1440 vs 375; `:hover`/`:focus-visible`/`:active`.
5. **Architectural execution** — Flexbox/Grid correctness, positioning collisions, contrast.

## Headline finding: the front-door is coherent and well-built

The design system is intentional and largely self-consistent: a `:root` token system (One-Dark-derived
dark theme + `.light` variant), shared component classes (`.modal` / `.modal-content` / `.cal-btn` /
`.admin-card`), and a **single global focus ring** (`:focus-visible { outline: 2px solid var(--red) }`,
`style.css:4802`) that gives every focusable control a keyboard affordance despite the hover-heavy rule
mix (773 `:hover` vs 24 explicit `:focus-visible` — the global catch-all covers the gap). Copy is
plain-language and safety-forward throughout (no FR-/NFR- jargon, no upstream codenames — white-label
clean). What initially read as a defect — the Portal/Chat/Vault tool windows not dimming the app — is
**documented intentional design** (`style.css:4426`): `.modal` is deliberately `background:none;
pointer-events:none` so *tool windows* float without blocking, and only the OOBE wizard
(`#applicant-onboarding-overlay`) re-adds a scrim as the one blocking modal.

## State-by-state notes

- **Login** — centered card, coral accent, strong figure-ground (near-black card on `--bg`). Minor:
  the password field's clear-`✕` shows on an empty field; username carries a coral focus border while
  password reads neutral. (Generic vendored `login.html`; left untouched to keep the workspace diff
  minimal.)
- **OOBE wizard / "Your profile"** — status-tab rail (`✓ Welcome / ✓ Connect a model / 3. Your
  profile`), full-width stacked fields, proper backdrop+blur scrim, becomes a full-height bottom sheet
  with a drag handle at 375. Observation (not changed): the intake sub-step's **"Save & continue"**
  sits directly above a separate wizard-level **"Back / Finish"** row — two nav scopes stacked close
  together, a mild wayfinding ambiguity. Left as-is: it is functional and re-laying it risks the
  resumable 12-step intake flow (a JS concern, out of a CSS audit's safe blast radius).
- **Settings** — reuses the wizard renderers (`mountSettingsStep`); left sub-nav (Add Models → System),
  endpoint cards, configured OpenRouter endpoint. Renders cleanly; the right pane has some unused
  vertical space but no breakage.
- **Job Assistant / Portal / Vault / Remote** — excellent, safety-forward content. The Portal empty
  state ("You're all caught up") carries a **"What Applicant never does"** trust panel (never submits
  without approval, never solves CAPTCHAs, never guesses EEO answers); the Remote surface reinforces
  "nothing is submitted until you decide … it never submits on its own." Mobile renders these as
  full-height sheets correctly.

## Defect catalogue & remediation

| # | Severity | Surface | Finding | Disposition |
|---|----------|---------|---------|-------------|
| 1 | **Medium** | Portal / Chat / Vault / Remote (desktop ≥769px) | The four applicant tool windows were **omitted from the canonical tool-window re-centering rule** (`style.css:4466`). Every other tool window (`#calendar-modal`, `#settings-modal`, `#gallery-modal`, …) is offset by `--icon-rail-w + --sidebar-w` so it centers in the **chat area**; the applicant modals centered on the full viewport and sat ~120px shifted-left, half-behind the sidebar, with background text crowding the right edge (worst on the sensitive Vault form). | **Fixed** — added the four `#applicant-*-modal` IDs to the existing selector list (single source of truth), explicitly leaving the blocking `#applicant-onboarding-overlay` full-viewport. |
| 2 | Low | OOBE wizard | Dual nav rows ("Save & continue" vs "Back/Finish"). | Documented; not changed (JS layout, flow risk). |
| 3 | Low | Login | Empty-field clear-`✕`; asymmetric field focus borders. | Documented; vendored `login.html`, left to keep diff minimal. |
| — | Info | Generic chat | The base assistant self-describes as a generic "AI productivity platform," not the job-application product. | Content/prompt, not CSS; out of scope. |

### Fix #1 detail

```css
/* style.css @media (min-width: 769px) — tool-window re-centering list */
#email-lib-modal,
#applicant-portal-modal,
#applicant-chat-modal,
#applicant-vault-modal,
#applicant-remote-modal {
  left:  calc(var(--icon-rail-w, 48px) + var(--sidebar-w, 0px));
  width: calc(100% - (var(--icon-rail-w, 48px) + var(--sidebar-w, 0px)));
}
```

This fixes at the correct altitude: it reuses the exact existing mechanism (no new rule, no inline
hack, no divergence from the design system), is purely additive, is gated to desktop so the mobile
full-screen sheets are untouched, and keeps one list as the source of truth for "which modals live in
the chat area." Empirically validated by before/after capture: the Portal and Vault now center in the
chat area, clear of the sidebar, matching every other tool window.

## Validation (green-increment gates)

- Front-door proxy/lane tests: `pytest -q workspace/tests/test_applicant_*.py` → **290 passed**.
- White-label codename denylist over the diff → clean.
- Change is CSS-only (no JS/Python/compose touched); `@media (min-width:769px)` so mobile is unaffected.
- Empirical: 1440 before/after screenshots confirm the re-centering; mobile sheets unchanged.
