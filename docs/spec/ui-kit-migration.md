# UI-Kit migration — vendor the window kit and map every visible surface — `FR-UIKIT`

> **Status:** spec + tracked backlog (this document) → per-surface green-increment PRs.
> **Authority:** extends [`master-spec.md`](master-spec.md) `FR-UI` (the vendored, white-labeled
> front door). This document is white-label clean: it names no upstream codename. The upstream
> provenance, the file-by-file vendoring list, and the rename table live in the denylist-excluded
> harvest doc [`../HARVEST-UIKIT-MAP.md`](../HARVEST-UIKIT-MAP.md).

## 1. Why (context)

The white-labeled front door (`workspace/`) and the upstream **window kit** we are vendoring are
**forks of the same self-hosted AI-workspace app**. The upstream fork additionally carries a small,
self-contained **component design system** — a set of reusable *kits* — that the Applicant front door
does not yet use. Today each Applicant surface hand-rolls its chrome from the workspace base CSS
(`.cal-btn`, `.admin-card`, `.settings-*`, `.memory-*`) and ad-hoc primitives
(`modalManager.js`, `modalSnap.js`, `windowDrag.js`, `ui.js` `showToast`). The result is inconsistent
window/notification/decision affordances across surfaces.

This migration **vendors every usable kit once** and **maps it, drop-in, to the features we already
ship** — per binding principle #1 (lift-and-shift: copy verbatim, then adapt by extension/removal) and
principle #4 (the front door reuses the workspace design system; it does not hand-roll). The intended
outcome: one consistent, accessible component layer behind **every visible surface**, with zero dead
UI and zero regression to the existing reachability/a11y guarantees.

## 2. The kit catalogue (vendoring targets)

The vendored system is the **Applicant UI Kit** ("AppKit"). Each kit is vendored verbatim into
`workspace/static/` then white-labeled (§4). CSS class namespaces (`ow-`, `on-`, `og-`, `odec-`) are
**retained verbatim** — they are opaque, denylist-safe tokens, so retaining them is a true drop-in with
zero class churn. JS modules are renamed to the `appkit*` namespace.

| Kit | Purpose | CSS namespace | Vendored module(s) |
|---|---|---|---|
| **Elements** | atomic controls: button (variants/sizes/groups), text field, checkbox, radio, switch, select, slider | `.ow-btn*`, `.ow-field`, `.ow-check`, `.ow-radio`, `.ow-switch`, `.ow-select`, `.ow-slider` | `appkitElements.js` |
| **Window Kit** | titlebar + traffic-light controls, body, modal **and** dockable variants, drag + resize | `.ow-window`, `.ow-titlebar`, `.ow-controls`, `.ow-body` | `appkitWindow.js` (+ reconcile `windowDrag.js`) |
| **Notice Kit** | severity notification cards, unified iconography, top-banner placement | `.on-card`, `.on-sev-*`, `.on-icon` | `appkitNotice.js` |
| **Gadget Kit** | focusable widget cards + a gadget rail | `.og-card`, `.og-head`, `.og-body` | `appkitGadget.js`, `appkitGadgetRail.js` |
| **Decision Kit** | prompt → options → confirm, with a destructive/risk variant + badge | `.odec-*` (`-prompt`, `-opts`, `-opt`, `-confirm`, `-risk`) | `appkitDecision.js` |
| **Chat Hint** | above-composer guide tip | kit hint classes | `appkitChatHint.js` |
| **Foundation** | glass-surface system, design tokens, house themes, responsive tokens, layout slots | `--ow-glass-*`, `--ow-focus-ring*`, `--ow-radius`, `--ow-ui-font`, theme classes `theme-frosted` / `glass-full` | `appkitGlass.js` (glass + adaptive glass), `appkitSlots.js`; CSS `kit-themes.css`, `responsive-tokens.css`, `mesh-gradient.css` |

**Out of scope (left behind):** all game-specific upstream assets (eye/blink chrome, diary-room,
cast/headshot, finale/season/night-status widgets, game trim CSS). They are not part of the kit and
are not vendored. See `../HARVEST-UIKIT-MAP.md` for the exact include/exclude list.

## 3. Functional requirements — `FR-UIKIT`

- **FR-UIKIT-1 (MUST — vendor verbatim, then adapt):** Every usable kit in §2 is vendored into
  `workspace/static/` (CSS + JS + tokens) **before** any surface is rewritten, copied working/unchanged
  first and only then adapted by extension/removal. No kit is re-implemented from scratch
  (principle #1). The MIT `NOTICE` is updated with the upstream attribution.
- **FR-UIKIT-2 (MUST — map every visible surface):** Every visible front-door surface in the §5 matrix
  is rendered through its mapped kit(s). "Visible surface" = every surface reachable through the
  `workspace/` chain (`docs/dormant-surfaces.md`), including the present-but-disabled Compare surface.
  A surface is **done** only when reachable/operable through the kit in the white-labeled front door
  (principle #2), not when the module merely exists.
- **FR-UIKIT-3 (MUST — drop-in, reconcile don't duplicate):** Where a kit overlaps an existing
  workspace primitive — Window Kit vs `windowDrag.js`/`modalManager.js`/`modalSnap.js`; Notice Kit vs
  `ui.js` `showToast` and the Pending-Actions Portal notification center — the kit **replaces or wraps**
  the primitive; the two MUST NOT coexist as parallel mechanisms. Toasts continue to flow through the
  single `showToast` entry point, now backed by the Notice Kit.
- **FR-UIKIT-4 (MUST — white-label / denylist clean):** No upstream codename appears in any shipped
  artifact. The CI denylist (`.github/workflows/ci.yml`) stays green. The retained `ow-`/`on-`/`og-`/
  `odec-` CSS prefixes are permitted (they are not the forbidden substring); every upstream-codenamed
  filename, symbol, and comment is renamed to `appkit*` during vendoring (§4; exact rename table in the
  harvest doc).
- **FR-UIKIT-5 (MUST — accessibility parity, no regression):** Kit components preserve every
  accessibility affordance already won on the front door — focus-into-dialog + focus restore, focus
  trapping, Escape-to-close, dialog ARIA roles, accessible labels (`for`/`id`), `aria-label` on
  glyph-only controls, and `prefers-reduced-motion` (issues #379–#394). Migrating a surface MUST NOT
  drop any of these.
- **FR-UIKIT-6 (MUST — progressive activation preserved):** Kit adoption does not change a surface's
  gate. `applicant_features.compute_features` state (`active`/`configured`/`locked`/`disabled`) and the
  dormant-surface registry still govern visibility; locked/disabled surfaces render the kit in their
  greyed state (Compare ships themed-but-disabled).
- **FR-UIKIT-7 (MUST — no build step):** Vendored modules are plain ES modules served statically
  (`workspace/app.py` re-reads assets per request); they pass `node --check` and add no bundler. The
  `style.css` payload budget is respected — kit CSS is additive and must not regress the render-blocking
  size concern (#398).
- **FR-UIKIT-8 (SHOULD — theming reachable):** The kit house themes (`theme-frosted`, `glass-full`,
  glass intensity) are selectable in **Settings**, reusing the exported `mountSettingsStep` renderer
  path rather than a bespoke control.
- **FR-UIKIT-9 (MUST — digest email exempt):** Per `FR-DIG-2` the **digest email artifact** is exempt
  from the Applicant visual style; only the **in-app** digest panel is mapped to the kit. The rendered
  email HTML is not restyled by this migration.

## 4. White-label / vendoring rules (binding detail for `FR-UIKIT-4`)

- **Keep:** the `ow-`/`on-`/`og-`/`odec-` CSS class prefixes and the `--ow-*` token names (opaque,
  denylist-safe; retaining them keeps the drop-in faithful and the diff small).
- **Rename:** every upstream-codenamed JS filename/symbol → `appkit*`; the upstream house-themes CSS →
  `kit-themes.css`, the upstream mesh-gradient CSS → `mesh-gradient.css`. The exhaustive file-by-file
  map (with upstream names) is in `../HARVEST-UIKIT-MAP.md`.
- **Strip:** game-only modules/assets (§2 "out of scope").
- **Verify:** the CI white-label codename denylist (`.github/workflows/ci.yml`) passes over all shipped
  paths; the only file permitted to name the upstream is the denylist-excluded harvest doc.

## 5. Surface → kit mapping matrix (`FR-UIKIT-2`)

Each row is a tracked issue. "Surface JS" names the existing module(s) the kit maps onto.

| # | Surface | Surface JS / source | Mapped kit(s) | Gate |
|---|---|---|---|---|
| S1 | Global shell — nav / sidebar / rail / modals / toasts | `index.html`, `login.html`, `landing.html`, `modalManager.js`, `ui.js` | Foundation + Window + Notice | always |
| S2 | OOBE onboarding wizard | `applicantOnboarding.js` | Window (modal) + Elements + Slots + Decision | gates the rest |
| S3 | Pending-Actions Portal + notification center | `applicantPortal.js` | Gadget + Notice + Decision | always |
| S4 | Documents / résumé redline review | `documentLibrary.js` | Window + Elements + Decision | `onboarding_complete` |
| S5 | Profile — criteria editor | criteria section / `index.html` | Elements + Gadget | `onboarding_complete` |
| S6 | Profile — attribute-cloud editor | attribute section / `index.html` | Elements + Gadget | `onboarding_complete` |
| S7 | Chat / assistant (job actions) | `applicantChat.js` | Chat Hint + Elements | `llm_configured` |
| S8 | Mind — remembers / playbooks / curation | `applicantMind.js` | Gadget + Decision | `llm_configured` |
| S9 | Email / digest panel (email artifact exempt, `FR-UIKIT-9`) | `applicantDigest.js`, `emailLibrary.js` | Notice + Gadget | `channels_configured` |
| S10 | Activity + Debug | `applicantActivity.js`, `applicantDebug.js` | Gadget + Window | `llm_configured` |
| S11 | Run controls / ops / Update | `applicantUpdate.js`, ops tab | Decision + Elements | `llm_configured` |
| S12 | Live remote view / takeover | `applicantRemote.js` | Window + Decision | from portal/chat |
| S13 | Credential vault | `applicantVault.js` | Elements + Window | `onboarding_complete` |
| S14 | Settings | `settings.js` + `mountSettingsStep` | Elements + Window | always |
| S15 | Connect-a-model / model ladder | `applicantModelLadder.js`, `modelPicker.js` | Elements + Gadget | always |
| S16 | Research | `researchSynapse.js` | Gadget | `llm_configured` |
| S17 | Compare (present-but-disabled) | `applicant_features.py` (`compare`) | Elements (themed-but-greyed) | `disabled` |

Foundation/cross-cutting tracked items: **F1** Foundation · **F2** Elements · **F3** Window ·
**F4** Notice · **F5** Gadget · **F6** Decision · **F7** Chat Hint · **X1** white-label/rename ·
**X2** a11y parity · **X3** CI/build budget · **X4** theming in Settings.

## 6. BDD acceptance (TDD harness)

Every tracked item carries a Gherkin `tests/bdd/features/enhancements/uikit_*.feature` paired with the
step module `tests/bdd/steps/test_enh_t13_uikit_steps.py`, following the house GREEN-vs-`@pending`
convention: an **un-tagged GREEN scenario** pins the pre-migration baseline that ships today (the
surface module exists / the overlapping primitive exists / the denylist gate exists), and a
**`@pending` scenario** is an honest red probing the migration target (the `appkit*` module is vendored
and the surface markup adopts the kit's classes). `conftest.pytest_bdd_apply_tag` maps `@pending` to a
non-strict xfail, so the suite stays green while the reds track the work.

Representative pattern (Decision Kit on the redline review surface, S4):

```gherkin
Feature: Documents / résumé redline review renders through the vendored Decision kit

  Scenario: the redline review surface ships and is reachable today   # GREEN baseline
    Given the UI-kit migration item "S4"
    Then its baseline anchor is satisfied today

  @pending
  Scenario: the redline approve/decline renders through the Decision kit   # red target
    Given the UI-kit migration item "S4"
    Then its migration target is satisfied
```

When a surface's PR lands the kit, its `@pending` tag is dropped and the scenario becomes a hard
regression gate (the kit module is present and the surface references the kit classes).

## 7. Out of scope / non-goals

- No change to engine logic, routers, gates, or the bridge — this is a front-door presentation layer.
- The engine's own internal `frontend/static/applicant/*` shell (the internal `api` service) is **not**
  the public surface and is not remapped here (principle #2: reachability is the `workspace/` chain).
- The digest **email** artifact (`FR-UIKIT-9` / `FR-DIG-2`).
- No new framework or build step (`FR-UIKIT-7`).

## 8. Verification

- Denylist green over shipped paths (`FR-UIKIT-4`).
- `uikit_*.feature` GREEN scenarios pass and `@pending` scenarios xfail under the hermetic lane
  (`DATABASE_URL='postgresql+psycopg://x:x@127.0.0.1:1/none' uv run pytest -q -m "not integration"`).
- `uv run ruff check .`, the front-door `test_applicant_*` tests, and `node --check` on every vendored
  module stay green; single Alembic head; `docker compose ... config` valid.
- Per-surface reachability proven through the front door per `docs/playtest-protocol.md` (incl. the
  §6a automated monkey/crawl) as each surface PR lands.
