# HARVEST — UI-kit vendoring map (upstream `orwell` window kit → Applicant AppKit)

> **Why this file may name the upstream.** This is an internal harvest/planning doc. Per
> `.github/workflows/ci.yml`, the white-label codename denylist **excludes `docs/HARVEST-*`** precisely
> so the harvest analysis can name upstream sources by name. Nothing here ships to a user surface. The
> white-label-clean requirement specification is [`spec/ui-kit-migration.md`](spec/ui-kit-migration.md)
> (`FR-UIKIT`); this doc is its vendoring appendix.

## Source

Upstream: `https://github.com/kevinhirsch/orwell`, directory `frontend/static/`. The upstream repo is a
"Big Brother" simulation game, but its `frontend/` is a fork of the **same** self-hosted AI-workspace
app that Applicant's `workspace/` is forked from. It carries a self-contained component design system —
**"OrwellElement"** — demoed at `frontend/static/element_kit_demo.html`, which is the only part we
harvest. License: MIT (preserve notice in `NOTICE`).

## Kit inventory (what `element_kit_demo.html` wires)

CSS: `/static/style.css`. JS modules: `orwellSlots.js`, `orwellWindow.js`, `orwellGadgetRail.js`,
`orwellGadget.js`, `orwellNotice.js`, `liquidGlass.js`, `orwellElements.js` — plus `orwellDecision.js`
and `orwellChatHint.js` referenced by the Decision/ChatHint sections. Supporting foundation in
`frontend/static/css/`: `orwellHouseThemes.css`, `responsive-tokens.css`, `meshGradient.css`. Adaptive
glass: `adaptiveGlass.js`.

Named kits and their CSS namespaces:

- **OrwellElement / Elements** — `.ow-btn` (`-prominent|-secondary|-plain|-destructive|-icon`, sizes
  `-sm|-md|-lg|-xl`, `-group`, `-concentric`), `.ow-field` (`is-invalid`), `.ow-check`, `.ow-radio`,
  `.ow-switch` (`.ow-switch-track`), `.ow-select`, `.ow-slider`.
- **OrwellWindowKit** — `.ow-window`, `.ow-titlebar`, `.ow-controls` (`.ow-min`, `.ow-close`),
  `.ow-body`; modal + dockable variants.
- **OrwellNoticeKit** — `.on-card`, severity `.on-sev-*`, `.on-icon`; `placement:"top-banner"`.
- **OrwellGadgetKit** — `.og-card`, `.og-head`, `.og-body`; `:focus-visible`.
- **OrwellDecision** — `.odec-head|-title|-prompt|-opts|-opt|-row|-confirm|-note`, risk variant
  `.odec-risk` + `.odec-risk-badge`.
- **OrwellChatHint** — above-composer guide tip.
- **Foundation tokens** — `--ow-glass-backdrop|-rim-border|-float`, `--ow-btn-tint-primary`,
  `--ow-focus-ring|-w`, `--ow-parent-radius|-inset`, `--ow-slider-fill`, `--ow-ui-font|-mono-font`,
  `--ow-radius`; theme classes `theme-frosted`, `glass-full`.

## Include / exclude split

**Vendor (the kit):** `orwellElements.js`, `orwellWindow.js`, `orwellNotice.js`, `orwellGadget.js`,
`orwellGadgetRail.js`, `orwellDecision.js`, `orwellChatHint.js`, `orwellSlots.js`, `liquidGlass.js`,
`adaptiveGlass.js`; CSS `orwellHouseThemes.css`, `responsive-tokens.css`, `meshGradient.css`; the
`--ow-*` token block and `.ow-/.on-/.og-/.odec-` rules from `style.css`.

**Do NOT vendor (game-specific, not kit):** `orwellAvatar.js`, `orwellCast.js`, `orwellCastPin.js`,
`orwellChatGate.js`, `orwellComposerDraft.js`, `orwellDeals.js`, `orwellDiaryRoom.js`,
`orwellEngineStatus.js`, `orwellFinale.js`, `orwellFinalizing.js`, `orwellHaptics.js`,
`orwellHeadshot.js`, `orwellLayoutSync.js`, `orwellNewSeason.js`, `orwellNightStatus.js`,
`orwellOnboarding.js`, `orwellOocAside.js`, `orwellPremiereTutorial.js`, `orwellPresence.js`,
`orwellReport.js`, `orwellRetrospective.js`, `orwellSeasonProgress.js`, `orwellSheet.js`,
`orwellStatusPanel.js`, `orwellToolBeats.js`, `eyeBlink.js`, `faviconEye.js`; CSS `eyeBlink.css`,
`game-trim.css`, `meshGradient.css` game variants. (Anything game/season/diary/cast/eye-themed.)

## Rename table (`FR-UIKIT-4`)

The denylist forbids the literal substring `orwell` in shipped artifacts; the short CSS prefixes
`ow-/on-/og-/odec-` do **not** contain it, so they are **kept verbatim**. Only the `*orwell*` tokens are
renamed.

| Upstream (shipped string contains `orwell`) | Vendored (white-label) |
|---|---|
| `orwellElements.js` | `appkitElements.js` |
| `orwellWindow.js` | `appkitWindow.js` |
| `orwellNotice.js` | `appkitNotice.js` |
| `orwellGadget.js` | `appkitGadget.js` |
| `orwellGadgetRail.js` | `appkitGadgetRail.js` |
| `orwellDecision.js` | `appkitDecision.js` |
| `orwellChatHint.js` | `appkitChatHint.js` |
| `orwellSlots.js` | `appkitSlots.js` |
| `liquidGlass.js` + `adaptiveGlass.js` | `appkitGlass.js` (merge or keep two `appkit*` files) |
| `orwellHouseThemes.css` | `kit-themes.css` |
| `meshGradient.css` | `mesh-gradient.css` |
| `responsive-tokens.css` | `responsive-tokens.css` (no rename needed) |
| JS symbols/classes `Orwell*` / `OrwellElement` / `OrwellWindowKit` | `AppKit*` / `AppKitElement` / `AppKitWindow` |
| `.ow-* / .on-* / .og-* / .odec-*` CSS classes | **kept verbatim** (denylist-safe) |
| `--ow-*` tokens | **kept verbatim** (denylist-safe) |
| theme classes `theme-frosted` / `glass-full` | **kept verbatim** |

Post-vendor check: `git grep -i -E 'firehouse|orwell|odysseus|smokey' -- ':!.github' ':!*.lock' ':!docs/HARVEST-*'`
returns nothing.

## Destination layout (in `workspace/static/`)

```
workspace/static/
  js/
    appkitElements.js  appkitWindow.js  appkitNotice.js  appkitGadget.js
    appkitGadgetRail.js  appkitDecision.js  appkitChatHint.js  appkitSlots.js  appkitGlass.js
  css/                         # new dir (workspace ships a single style.css today)
    kit-themes.css  responsive-tokens.css  mesh-gradient.css
  style.css                    # receives the additive .ow-/.on-/.og-/.odec- rules + --ow-* tokens
```

`NOTICE` gains the upstream MIT attribution line for the harvested kit.

## Reconciliation with existing workspace primitives (`FR-UIKIT-3`)

| Existing primitive | Kit it reconciles with | Action |
|---|---|---|
| `windowDrag.js`, `modalManager.js`, `modalSnap.js`, `windowDrag.js` | Window Kit | Window Kit wraps/replaces; one window mechanism, not two |
| `ui.js` `showToast` | Notice Kit | `showToast` keeps its signature, re-backed by `.on-card` |
| `applicantPortal.js` notification center | Notice + Gadget + Decision | portal items render as gadget/notice/decision cards |
| `.cal-btn`, `.admin-card`, `.settings-*`, `.memory-*` | Elements | migrate call sites to `.ow-*`, retire bespoke button sizing |
