# Applicant UIKit Standards

> Practical design-system reference for the **a0-applicant** plugin UI — the live
> Applicant surface that runs inside the Agent-Zero webui shell (per
> `[[Applicant — UI Deploy & Verify]]`: @8090 `docker-a0-1`, plugin UI baked into the
> image, hot-patched via `docker cp`). Every fact below was read directly out of the
> files cited next to it. Where the codebase disagrees with itself, that is written
> up as a **gap**, not smoothed over into an invented rule. Nothing here was
> deployed, run, or screenshotted to produce this doc (static source read only) —
> see the "Not yet verified visually" callouts.

## Scope note — two UI stacks exist, this doc covers the live one

There are **two, unrelated** front-end token systems in this repo:

1. **In scope here:** `a0-applicant/webui/*.html` + `a0-applicant/webui/applicant-theme.css`,
   layered on top of the Agent-Zero base shell (`agent-zero/webui/index.css`,
   `agent-zero/webui/css/*.css`). This is the plugin UI actually shipped today — CSS
   custom properties named `--color-*`, theming via a `.light-mode` class on
   `<body>`, buttons/cards/badges built out of `.btn`/`.card`/`.badge`.
2. **Out of scope, do not conflate:** `workspace/static/style.css` +
   `frontend/static/` — an older/parallel "front-door" surface described in
   `docs/frontend-audit-protocol.md`, with its own, completely different token
   vocabulary (`--bg`, `--fg`, `--panel`, `--sys-blue`, `--chrome-ink`, a
   "Liquid Glass"/HIG-discipline system, `theme.js`-driven). There is also a
   not-yet-vendored "AppKit" harvest (`docs/HARVEST-UIKIT-MAP.md`,
   `spec/ui-kit-migration.md`) pulling a `.ow-*`/`.on-*`/`.og-*` kit from an
   upstream project — that kit is **planned, not integrated**, and shares no
   tokens with what's documented below. If a future task touches either of
   those surfaces, treat this document as non-authoritative for them and audit
   separately.

---

## 1. Theming mechanism — `.light-mode` on `<body>`, and the leak trap

**Source of truth:** `agent-zero/webui/index.css:10-116`,
`a0-applicant/webui/applicant-theme.css:4-72`,
`agent-zero/webui/components/sidebar/bottom/preferences/preferences-store.js:117-150`.

- Every real color is a two-layer alias: a `-dark`/`-light` suffixed literal, then a
  bare semantic name that points at one of the two, e.g.
  `--color-panel-dark: #1a1a1a` / `--color-panel-light: #f0f0f0` →
  `--color-panel: var(--color-panel-dark)`.
- `:root` declares the **dark** literal-to-semantic mapping directly (index.css:51-68).
  Dark is the default theme — there is no `.dark-mode` override block needed because
  `:root` already *is* dark.
- `.light-mode { --color-panel: var(--color-panel-light); ... }` (index.css:98-116)
  re-declares each semantic alias when the class is present. The class is applied to
  `document.body` (not `<html>`) by `preferences-store.js:144-150`, driven by a
  `darkMode` boolean persisted to `localStorage`, **defaulting to `true`**
  (`preferences-store.js:24`: `_darkMode: true`) — i.e. **dark is the shipped
  default; light is opt-in** via the sidebar preferences toggle.

### The leak trap (already hit twice in this codebase — treat as a standing hazard)

A CSS custom property's value is fixed **at the element that declares it** and then
inherits unchanged. If a token is aliased with `var(--color-x, fallback)` **only at
`:root`**, that alias is frozen to whatever `--color-x` equals at `:root` — always
dark, since `:root` never carries `.light-mode`. Descendant elements under
`.light-mode` still inherit the frozen (dark) value, **not** the light one, unless
the alias is *itself* re-declared inside a `.light-mode { }` block.

This has already produced two real, documented incidents in this repo:

1. **`applicant-theme.css:53-72`** (fixed under APP-LP-1). The five `--ap-color-*`
   aliases (`--ap-color-primary`, `--ap-color-text`, `--ap-color-background`,
   `--ap-color-panel`, `--ap-color-border`) all resolve `var(--color-*, ...)` at
   `:root`. The file's own comment explains the fix verbatim: *"Without this block,
   `--ap-color-*` keeps whatever `--color-*` equalled at `:root` (always the dark
   default) no matter what `<body>` overrides — every panel that styles itself via
   `.btn`/`.badge`/`.card`/etc. rendered dark chips/borders even with light mode
   on."* The fix mirrors the alias block under `.light-mode` too.
2. **`a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html:203-217`**
   (same audit pass, `APP-LP-1 contrast pass`). Sidebar row/icon colors were
   hardcoded to `rgba(255,255,255,*)` — readable only against a permanently-dark
   assumption. In light mode this went **white-on-near-white**. Fixed by swapping to
   the adaptive `var(--color-text)` / `var(--color-text-secondary, #737a81)` tokens.

**Standing rule:** any token meant to look right in both themes must be
**re-declared inside `.light-mode`**, not just aliased once at `:root`. Never ship a
literal (hex/rgba) color for text or a text-bearing background without checking it
against *both* the dark default and an explicit `.light-mode` override.

### A live, unfixed mirror-image of the same trap (found while writing this doc)

`.card, .item, .surface` (`applicant-theme.css:132-138`) sets
`background: var(--color-input-bg)`, and `--color-input-bg: #ffffff`
(`applicant-theme.css:30`) is declared **once**, at `:root`, as a bare literal — it
has no `-dark`/`-light` pair and is never touched inside the `.light-mode` block.
Text color on those same panels comes from `.aXXX { color: var(--ap-color-text) }`
(applicant-theme.css:205-215), which in **dark mode** (no `.light-mode` class)
resolves to `--color-text-dark` = `#ffffff`. That means, in the shipped **dark**
default: white card background (`--color-input-bg`) + white inherited text
(`--ap-color-text`) = **1:1 contrast, i.e. invisible text**, on any `.card`/`.item`/
`.surface` that doesn't set its own `color`. `--color-hover-bg: #eef1f3`
(applicant-theme.css:31) and `--color-text-secondary: #5a5a5a`
(applicant-theme.css:11) have the identical problem — single literal, no
`.light-mode` counterpart, so they don't adapt at all. This is a **static-analysis
finding, not yet confirmed on screen** — verify in a real dark-mode screenshot
before treating it as a live bug (many per-panel `<style>` blocks, e.g.
`today.html:20`, override `.item` locally with the theme-aware `--color-background`
instead of `--color-input-bg`, which may mask it in practice on some panels but not
others). Flagging as the top item for a follow-up contrast pass.

---

## 2. Color tokens

### 2a. Agent-Zero base tokens (`agent-zero/webui/index.css:10-116`)

| Semantic token | Dark value | Light value |
|---|---|---|
| `--color-background` | `#131313` | `#fafafa` |
| `--color-text` | `#ffffff` | `#333333` |
| `--color-text-muted` | `#d4d4d4e4` | `#333333e4` |
| `--color-primary` | `#737a81` | `#384653` |
| `--color-secondary` | `#656565` | `#e8eaf6` |
| `--color-accent` | `#cf6679` | `#b00020` |
| `--color-message-bg` | `#2d2d2d` | `#ffffff` |
| `--color-highlight` | `#2b5ab9` | `#2563eb` |
| `--color-message-text` | `#e0e0e0` | `#333333` |
| `--color-panel` | `#1a1a1a` | `#f0f0f0` |
| `--color-border` | `#444444a8` | `#bdbdbdcf` |
| `--color-input` | `#131313` | `#e4e4e4` |
| `--color-input-focus` | `#101010` | `#dadada` |
| `--color-chat-background` | `#212121` | `#fafafa` |
| `--color-error-text` | `#e72323` | `#920000` |
| `--color-warning-text` | `#e79c23` | `#936214` |
| `--color-table-row` | `#272727` | `#edededf3` |
| `--color-background-hover` | `color-mix(in srgb, var(--color-border) 50%, transparent)` (both modes) | |

Fonts: `--font-family-main: "Rubik", Arial, Helvetica, sans-serif`,
`--font-family-code: "Roboto Mono", monospace` (index.css:85-86), both pulled via a
Google Fonts `@import` at the very top of the file (index.css:1) —
`https://fonts.googleapis.com/css2?family=Roboto+Mono...&family=Rubik...`.

Spacing/radius (index.css:70-94): `--spacing-xxs .15rem / -xs .3125rem / -sm .625rem
/ -md 1.25rem / -lg 2rem`; `--font-size-xs .7rem / -small .8rem / -smaller .9rem
/ -normal 1rem / -large 1.2rem`; `--border-radius 1.125rem`, `--border-radius-sm .5rem`.

### 2b. `a0-applicant` layer (`a0-applicant/webui/applicant-theme.css:4-51`)

These are additions/aliases the plugin stacks on top of the base tokens above.
**Only the five `--ap-color-*` aliases are theme-aware** (re-declared under
`.light-mode`, §1); everything else in this block is a **single literal shared by
both themes** — confirmed by grep, no `-dark`/`-light` pair exists anywhere in the
repo for any of them:

| Token | Value | Theme-aware? |
|---|---|---|
| `--ap-color-primary` | `var(--color-primary, #4361ee)` | Yes (`.light-mode` re-declare, line 67) — but see dead-fallback gap below |
| `--ap-color-text` | `var(--color-text, #2c2c2c)` | Yes (line 68) |
| `--ap-color-background` | `var(--color-background, #f5f7fa)` | Yes (line 69) |
| `--ap-color-panel` | `var(--color-panel, #e8ecf1)` | Yes (line 70) |
| `--ap-color-border` | `var(--color-border, #d4d9e0)` | Yes (line 71) |
| `--color-primary-hover` | `#3a56d4` | **No** — one literal |
| `--color-text-secondary` | `#5a5a5a` | **No** |
| `--color-success` / `-bg` / `-text` | `#2ecc71` / `#e8f8ef` / `#1a7a3a` | **No** |
| `--color-warning` / `-bg` / `-border` / `-text` | `#f39c12` / `#fef5e6` / `#f0d9a0` / `#8a6d1a` | **No** |
| `--color-danger` / `-bg` / `-border` / `-text` | `#e74c3c` / `#fdecea` / `#e8a0a0` / `#9b1c1c` | **No** |
| `--color-input-bg` | `#ffffff` | **No** — see live dark-mode gap in §1 |
| `--color-hover-bg` | `#eef1f3` | **No** |
| `--font-sm/base/lg/xl/h1/h2` | `.82rem / .92rem / 1.15rem / 1.5rem / 1.5rem / 1.1rem` | n/a |
| `--space-xs/sm/md/lg` | `4px / 8px / 14px / 20px` | n/a |
| `--radius-sm/md/lg` | `8px / 10px / 12px` | n/a |

**Gap — dead fallback color.** `--ap-color-primary: var(--color-primary, #4361ee)`
looks like it defines a vivid blue (`#4361ee`) brand primary. It doesn't, in
practice: `--color-primary` is *always* already defined by
`agent-zero/webui/index.css` (§2a) wherever this file is loaded (it's always loaded
inside the Agent-Zero shell), so the `#4361ee` fallback is unreachable — the
`var()` fallback only fires when the property is completely unset, not merely
"different." The **effective rendered primary** is Agent-Zero's
`--color-primary-dark #737a81` / `--color-primary-light #384653` (a slate
grey-blue), not the blue in the comment. Several per-panel `<style>` blocks
(e.g. `today.html:17`, `digest.html:15`) independently hardcode a *third*, also-dead
fallback, `var(--color-primary,#2d7ff9)` — a different blue again. Recommendation:
either delete these dead fallback literals (they mislead readers of the source) or
make `--color-primary` genuinely overridable per-surface if a distinct Applicant
brand blue is actually wanted.

**Gap — inconsistent semantic-color paths.** Three different sources of truth exist
for "success/warning/danger" styling in the same UI:
- `applicant-theme.css:16-27` — the canonical `--color-success-bg/-text`, etc.
  (table above), used by `.badge.success/.warning/.sensitive`.
- `digest.html:8` — uses `--color-warn-bg`/`--color-warn-text` (**typo**: "warn" not
  "warning"). That token is never defined anywhere, so this rule silently always
  falls through to its own hardcoded fallback (`#fff8dc`/`#8a6d0b`), independent of
  the real warning tokens and never reachable via CSS-variable override.
- `documents.html:29-32` — `.doc-status.approved/.declined/.pending` use fully
  hardcoded Bootstrap-style literals (`#d4edda`/`#155724`,
  `#f8d7da`/`#721c24`, `#fff3cd`/`#856404`) with **no CSS variable at all**, a
  different green/red/yellow than the canonical tokens and permanently
  non-theme-aware.

Recommendation: pick one status-badge pattern and use it everywhere. The
`.badge.success/.warning/.sensitive` classes in `applicant-theme.css` are the
closest thing to a standard already in place — prefer reusing those over adding a
fourth variant.

### Contrast — measured, not assumed

Computed with the standard WCAG relative-luminance formula against the literal hex
values cited above (not estimated):

| Pair | Ratio | WCAG AA read |
|---|---|---|
| Dark body: `#fff` text on `#131313` bg | 18.6:1 | Pass (both text sizes) |
| Light body: `#333333` text on `#fafafa` bg | 12.1:1 | Pass |
| Light primary button: white text on `--color-primary-light #384653` | 9.7:1 | Pass |
| **Dark primary button: white text on `--color-primary-dark #737a81`** | **4.35:1** | **Borderline fail** for normal text (needs 4.5:1); the `.btn` label is ~.82rem/13px bold, under the 14pt-bold "large text" threshold, so the 3:1 relaxed target likely doesn't apply either. Verify visually. |
| `.badge.success` text `#1a7a3a` on bg `#e8f8ef` | 4.9:1 | Pass |
| `.badge.warning` text `#8a6d1a` on bg `#fef5e6` | 4.5:1 | Pass (exactly at threshold) |
| `.err`/danger text `#9b1c1c` on bg `#fdecea` | 7.1:1 | Pass |
| `--color-text-secondary #5a5a5a` on light bg `#f5f7fa` | 6.4:1 | Pass |
| **`--color-text-secondary #5a5a5a` on dark bg `#131313`** | **2.7:1** | **Fails** both AA thresholds. Because this token is a single literal (§2b), it's used unchanged in dark mode too — and it's used pervasively: every panel's `.sub`/`.meta`/`.role`/`.why` secondary-text line (`today.html`, `digest.html`, `discovery.html`, and ~15+ more) references `var(--color-text-secondary, #6b7683)`. |
| `--color-input-bg #ffffff` text at `--ap-color-text` white (dark mode) | **1:1** | Fails outright — see the live gap called out in §1 |
| `--color-border` composited over its own background (dark: `#444444` @66% over `#131313`; light: `#bdbdbd` @81% over `#fafafa`) | ~1.5:1 / ~1.6:1 | Well under the 3:1 WCAG 1.4.11 non-text/UI-component target. Borders here are a deliberately subtle hairline, not a load-bearing boundary — fine for decorative dividers, **not** fine if a border is the *only* affordance marking an interactive edge (e.g. an input field with no other cue). |

Note also: `input:focus`/`textarea:focus`/`select:focus`
(`applicant-theme.css:114-129`) sets `outline: none` and relies solely on
`border-color` shifting to `--ap-color-primary` as the keyboard-focus indicator — no
`:focus-visible` ring/box-shadow anywhere in this file or in `agent-zero/webui/index.css`.
Combined with the low intrinsic border contrast above, verify keyboard-focus
visibility explicitly; don't assume the border-color swap alone clears WCAG 2.4.7 /
1.4.11 in every theme.

---

## 3. Typography

- Font stack is inherited from the Agent-Zero shell — `"Rubik", Arial, Helvetica,
  sans-serif` for UI text, `"Roboto Mono", monospace` for code
  (`agent-zero/webui/index.css:85-86`). `applicant-theme.css` sets no font-family of
  its own (panels use `font-family: inherit`); its top-of-file comment
  ("CSP-safe: system font stack only, no `@import` or external fonts") is true of
  that file in isolation, but the shell it's always mounted inside *does* `@import`
  both fonts from Google's CDN (`index.css:1`) — if a strict-CSP / offline
  deployment is ever required, that's the line to fix, not `applicant-theme.css`.
- A type scale exists (`--font-sm .82rem / --font-base .92rem / --font-lg 1.15rem /
  --font-xl 1.5rem / --font-h1 1.5rem / --font-h2 1.1rem`,
  `applicant-theme.css:34-39`) — **but it's unused**. A repo-wide check found
  `var(--font-` appears in **0 of the 41** panel `.html` files under
  `a0-applicant/webui/`. Every panel hardcodes its own `font-size` in `rem`
  instead. The hardcoded values cluster tightly (most common, by occurrence count:
  `.85rem` ×116, `.82rem` ×96, `.95rem` ×42, `1.5rem` ×39, `.78rem` ×39, `.8rem`
  ×34, `1.2rem` ×32, `.72rem` ×22, `.75rem` ×20, `1.15rem` ×14, `.92rem` ×12) —
  roughly the same neighborhood as the declared scale, but with several extra
  ad hoc sizes never rolled into it (`.85rem`, `.95rem`, `.78rem`, `.8rem`,
  `.72rem`, `.75rem`, `1.2rem`, `.9rem`, `.88rem`).
- `h1`/`h2`/`h3` weights/margins are set once, globally, in
  `applicant-theme.css:78-80` (`h1`: 700 weight; `h2`/`h3`: 600). Panel headers
  follow a loose convention of `<h1>{optional emoji} Title <button class="help-btn">?</button></h1>`
  — present in 33 of 41 panels (grep for `help-btn`), but the leading emoji itself is
  inconsistent (present on e.g. `digest.html`'s "📋 Daily Digest", `activity.html`'s
  "🤖 Activity"; absent on e.g. `chat.html`, `fonts.html`, `channels.html`,
  `automation.html`) — treat the emoji as optional flavor, the `help-btn` as the
  closer-to-standard part.

**Recommendation:** when touching a panel, prefer `var(--font-sm)` /
`var(--font-base)` / etc. over a new hardcoded `rem` value; when a genuinely new
size is needed repeatedly, add it to the scale in `applicant-theme.css` rather than
letting another one-off literal propagate.

---

## 4. Spacing & radius

Same story as typography: `applicant-theme.css:42-50` declares
`--space-xs/sm/md/lg` (4/8/14/20px) and `--radius-sm/md/lg` (8/10/12px), and **0 of
the 41** panel files reference `var(--space-` or `var(--radius-` at all. Actual
practice (raw literals, by occurrence): `border-radius` is `8px` ×137 and `10px`
×54 overwhelmingly, with `6px`/`4px`/`12px`/`16px`/`99px` (pill) as minor variants;
`gap` clusters at `8px` ×97, `6px` ×33, `4px` ×10, `10px` ×9, `12px` ×8. In other
words the de-facto scale in the wild is close to — but doesn't literally reuse —
the declared one, and skips the `14px`/`20px` steps entirely in favor of `12px`.
`99px` (fully round) is the ad hoc convention for pill/badge shapes
(`applicant-theme.css:187`: `.badge, .tag { border-radius: 10px; }` — actually
10px, not a true pill; true pills (`border-radius:99px`) show up ad hoc in a couple
of panel-local styles for chips, e.g. `main.html`'s onboarding `.chip`).

**Recommendation:** same as typography — reuse `var(--space-*)`/`var(--radius-*)`
in new code; if the token set needs a `6px`/`12px` step to match what's already the
real convention, add it rather than reaching for another bare number.

---

## 5. Component patterns actually present

All in `a0-applicant/webui/applicant-theme.css` unless noted; every one of these is
already shared across the 41 panels via the single stylesheet link
`<link rel="stylesheet" href="/plugins/applicant/webui/applicant-theme.css">` that
opens nearly every panel file.

- **Buttons** — `.btn` / `.btn.primary` (or `.btn-primary`) / `.sidebar-action`
  (lines 83-111). Disabled state = `opacity: .55`. **Note:** this is a *second*,
  independent button system from Agent-Zero's own core one
  (`agent-zero/webui/css/buttons.css`), which uses `.button` / `.button.confirm` /
  `.button.cancel` / `.btn-action` / `.btn-icon` / `.btn-icon-action` against the
  base `--color-*` tokens directly (no `--ap-*` layer). The two don't collide by
  class name, but they are two separately-maintained visual languages for "a
  button" living in the same shipped product — new Applicant panels should use the
  `.btn` family (that's what all 41 existing panels use), not import the core
  `.button` classes, to stay consistent with what's actually there.
- **Inputs/selects** — themed to the same `--ap-color-*` tokens, `outline:none` +
  border-color-shift focus state (lines 113-129; see the focus-visible caveat in
  §2's contrast table).
- **Cards/surfaces** — `.card` / `.item` / `.surface` (lines 131-138), plus the
  collapsible `.surface-header` + `.surface-content` pair (lines 139-151) — note the
  `surface-header` uses an asymmetric corner radius
  (`border-radius: var(--radius-md) var(--radius-md) 0 var(--radius-md)`, i.e. the
  bottom-right corner stays square) as a deliberate "attached tab" look.
- **Empty state** — `.empty` + `.icon`/`.title`/`.subtitle` (lines 154-160); real
  usage example with an inline SVG checkmark icon in `today.html:64-68`.
- **Error/success inline boxes** — `.err` (lines 163-170, and independently
  redefined per-panel, e.g. `today.html:10`, `digest.html:7`); `.aXXX .feedback-confirm`
  style success boxes appear per-panel rather than as a shared class
  (`digest.html:35`).
- **Badges/pills** — `.badge`/`.tag` base + `.sensitive`/`.success`/`.warning`
  modifiers (lines 184-202). The **score badge** pattern (viability/match score,
  `digest.html:24,61`) is a plain inline pill: `font-size:.78rem; padding:2px 7px;
  border-radius:10px; background:var(--color-panel); ...` showing literal text
  (`"Score: " + value`), not a colored/graduated indicator — there is no
  color-coded score-tier convention in the codebase today (e.g. no green/yellow/red
  by score band); if one is wanted, it doesn't exist yet and would need to be
  designed, not "discovered."
- **Review / Approve / Snooze / Decline actions** — consistent verbs across panels:
  `today.html` uses **Resolve** / **Snooze** / a per-kind affordance button (label
  varies, e.g. "Review in Digest", "Review material" — see the `KIND_AFFORDANCE`
  map at `today.html:85-91`); `digest.html` uses **Approve** / **Pass** (its decline
  verb, with a required reason text field) / **Review** (opens `documents.html` in a
  modal); `documents.html` uses **Approve** / **Decline** / **Apply Redline**. There
  isn't one universal verb set — "Approve" is shared everywhere, but the
  negative/deferral action is named differently per surface (**Pass**, **Decline**,
  **Snooze**, **Resolve**) depending on what it actually does. Keep using the verb
  that matches the real action rather than forcing one generic label.
- **Sidebar navigation rows** — `.sidebar-action` in the global nav
  (`a0-applicant/extensions/webui/sidebar-quick-actions-main-start/hello-world.html:1-166`,
  one row per panel, `material-symbols-outlined` icon + `.label` span), restyled to
  match the base Chats/Tasks list rows via the block at lines 203-216 of that same
  file (explicitly commented as "Unified sidebar visual system" — this is also
  where the second documented light-mode leak, described in §1, was fixed).
- **Modals** — panels are opened via `window.openModal(path)`
  (`agent-zero/webui/js/modals.js:137`, exposed globally at line 369), which is how
  every sidebar row and most in-panel "Review"/deep-link buttons navigate (e.g.
  `digest.html:86`, `today.html:94`). Modal chrome itself
  (`agent-zero/webui/css/modals.css:1-60`) uses base `--color-background` +
  `rgba(0,0,0,0.5)` backdrop + `8px` radius — note the file's own header comment
  says `.modal-content`/`.modal-container`/`.modal-overlay` are the **old**,
  soon-to-be-deprecated modal system, kept alive only for the Settings modal; don't
  build new UI against those three classes.

---

## 6. HIG / accessibility rules learned in this codebase

Targets (standard WCAG 2.1 AA, restated for reference, not invented):
- **4.5:1** minimum contrast for normal body text.
- **3:1** minimum for large text (≥18pt / ≥14pt bold) and for UI-component /
  graphical-object boundaries that convey meaning (WCAG 1.4.11).
- Visible focus indicator for all keyboard-operable controls (2.4.7).

Do / don't, derived from the two real incidents and the additional gaps found while
writing this doc (§1, §2):

- **Do** re-declare every color token inside `.light-mode` if it's meant to look
  different — or even just correct — in light mode. A token only aliased once at
  `:root` is frozen to the dark value forever, regardless of what `<body>` carries.
  This is not a hypothetical: it has already caused two ship-then-fix incidents
  (`applicant-theme.css`'s `--ap-color-*` aliases; the sidebar's hardcoded
  `rgba(255,255,255,*)` rows).
- **Don't** hardcode a literal color (hex/rgb/rgba) for text or a text-bearing
  background "because it looks right in the theme I'm looking at right now." Check
  it against **both** themes before shipping — dark is the default, so a
  light-mode-only glance will miss dark-mode regressions and vice versa.
- **Do** treat single-literal tokens (`--color-text-secondary`, `--color-input-bg`,
  `--color-hover-bg`, and the whole success/warning/danger block in
  `applicant-theme.css`) as **not** currently theme-aware, even though they look
  like the other tokens. Confirm actual on-screen contrast in both modes before
  reusing one of these for new text, especially secondary/meta text in dark mode
  (measured 2.7:1 above — a real fail).
- **Do** verify contrast **and** basic legibility visually, via a zoomed screenshot
  in both themes, before calling a UI change done — this doc's own "live gap" in §1
  (white-on-white cards) was found by reading the CSS cascade, not by looking at a
  screenshot, which is exactly the failure mode a real render would have caught in
  seconds and a source read can miss for months.
- **No responsive breakpoints exist today.** A repo-wide grep found **zero**
  `@media` queries across all 41 `a0-applicant/webui/*.html` panels. Panels are
  fixed-max-width containers (`760px` for most `.aXXX` panels, `960px` for
  `.main-panel`/`.a-main`, per `applicant-theme.css:205-223`) that rely entirely on
  the surrounding modal being able to shrink/scroll. "Responsive" in the pre-ship
  checklist below means "still usable at the modal's narrow/mobile width," not
  "has a defined breakpoint" — there isn't one to check against yet.
- **Focus indicators are minimal.** No `:focus-visible` styling anywhere in
  `applicant-theme.css` or the base `index.css`; inputs get a border-color swap
  only, buttons get nothing beyond the browser default. If you add a new
  interactive control, don't assume it inherited a visible focus ring — check it
  tabs into view clearly in both themes.

---

## 7. Recipes

### Adding a new panel/gadget on-standard

1. **Reuse before you build.** Per the product's reuse-first rule
   (`[[Applicant — Product Philosophy]]`), a new panel should be a thin layer over
   existing data/actions, not a parallel implementation. Check whether an existing
   panel already renders something close (e.g. another list-of-items-with-actions
   like `today.html`/`digest.html`) before inventing new markup.
2. **Link the shared stylesheet first**, exactly like all 41 existing panels:
   `<link rel="stylesheet" href="/plugins/applicant/webui/applicant-theme.css">` at
   the top of the file.
3. **Scope your panel's own `<style>` block under one panel-specific class**
   (the `.aXXX` convention — `.atoday`, `.adigest`, `.acriteria`, etc.), and add
   that class name to the shared max-width rule at `applicant-theme.css:205-210` (or
   the wider `.main-panel`/`.a-main` rule at 218-223) if it needs the standard
   panel width instead of redefining `max-width`/`margin`/`padding` locally.
4. **Reuse the existing component classes** rather than reinventing them:
   `.btn`/`.btn.primary` for actions, `.card`/`.item`/`.surface` for content
   blocks, `.badge`/`.tag` (+ `.success`/`.warning`/`.sensitive`) for status pills,
   `.empty` for the zero-state, `.err` for inline errors, `.spinner`/`.loading`
   for async states, `.help-btn` next to the `<h1>` if the panel has help content
   at `/plugins/applicant/webui/help.html?surface=<name>`.
5. **Color everything via the existing `--ap-color-*` / `--color-*` tokens**, never
   a new hardcoded hex — and if a token you need turns out to be one of the
   single-literal ones flagged in §2b/§6 (text-secondary, input-bg, hover-bg,
   success/warning/danger), treat that as a known gap to route around (e.g.
   explicitly set your own `color` on cards instead of relying on inherited
   `--ap-color-text`, until that token is made theme-aware) rather than a safe
   default to build on.
6. **Name the negative/deferral action for what it actually does** (Decline, Pass,
   Snooze, Resolve — see §5) instead of defaulting to a generic "Cancel"/"Reject."
7. **Verify in both themes before calling it done** — toggle the dark-mode
   preference and re-check the same screen. This is a hard requirement per
   `[[Playtest Visual Verification]]`: UI changes must be rendered and checked in a
   real browser, not source-asserted.

### Pre-ship checklist

- [ ] Contrast checked in **both** dark (default) and light mode — not just the one
      you happened to be looking at.
- [ ] No text or text-bearing surface relies on a single-literal token
      (`--color-text-secondary`, `--color-input-bg`, `--color-hover-bg`, the
      success/warning/danger block) without confirming it's actually legible in
      dark mode specifically (§1, §6).
- [ ] No hardcoded hex color for anything text-adjacent; if a token had to be
      invented, it's declared inside **both** `:root` and `.light-mode`, not
      `:root` alone.
- [ ] Spacing/radius/font-size pulled from the existing `--space-*`/`--radius-*`/
      `--font-*` scale where a close-enough step exists, rather than a fresh
      one-off `rem`/`px` literal (§3, §4).
- [ ] Interactive elements (buttons, links, inputs) have a visible keyboard-focus
      state in both themes — don't assume one exists by default (§6).
- [ ] Panel still reads correctly at the modal's narrow/mobile width — there are no
      breakpoints to lean on (§6), so this has to be checked by hand.
- [ ] Verified with an actual browser screenshot in both themes, zoomed enough to
      read text — not just asserted from source (`[[Playtest Visual Verification]]`).
