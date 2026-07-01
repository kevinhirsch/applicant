# Apple Genius — Front-Door Visual Audit (Liquid Glass / HIG)

Standing design review of Applicant's white-labeled front-door, performed **as the
Apple Genius** (`docs/design/APPLE_GENIUS.md`) against the sourced corpus
(`docs/design/liquid-glass/` + `docs/design/hig/`). This is the "check our vendored
work visually with the playtest harness" pass the genius was brought in for.

## Method (how this was run)

- **Live harness, not guesswork.** Stood up the real stack (Postgres + engine `:8000`
  + front-door `:7000`) and ran the Playwright monkey/crawl (`scripts/playtest_crawl.py`,
  playtest-protocol §6a): logged in, opened every surface via its JS seam + URL routes,
  and screenshotted each at 1440×900 (+ mobile for portal/chat/vault/onboarding).
  23 surface renders, **zero console/page/5xx/handler errors** — so every finding below
  is pure design/HIG, not a functional bug.
- **Parallel, per-surface, corpus-grounded.** Eight surface-family auditors (+ a TUI
  pass) each read their renders against the Apple reference **images** and rules, and
  returned CONFIRMED findings anchored to `file:line`. This document is the overseer's
  synthesis.
- **Product fluency.** The genius reads `docs/design/APPLICANT_FEATURE_MAP.md` (25
  surfaces) so each critique respects what the surface is *for*.

## Headline verdict

**The bones are right; the discipline is not.** Across every surface the genius credited
the same structural passes — **Regular (not Clear)** is correctly chosen for these
text-bearing dark surfaces; the **one-glass-plane economy** holds (the inner `.admin-card`
correctly de-glasses inside a frosted modal, `style.css:31889`; note-cards carry no
`backdrop-filter`); **content-layer flatness** is right where visible (gallery upload zone,
email list, notes/library tiles are fills, not glass slabs); **concentric** nesting reads
correctly; and legibility survives with the glass stripped.

The failure is **one systemic breach of the single most-cited discipline** (persona rule
#5 / #3, HIG Color): *glass on ⇒ NO accent hue on text or symbols — color tints the
background, chrome ink stays neutral.* A decorative brand palette — `--red:#e06c75`
(pink) and `--fg:#9cdef2` (cyan), `style.css:24,21` — is painted directly onto **labels,
headings, wordmarks, active tabs, filter chips, the focus ring, and the primary CTA**.
Everything else that failed flows from, or sits beside, that one breach.

> **Current tier context.** The crawl rendered the **Normal/flat** tier because
> `DEFAULT_GLASS_TIER = 'off'` (`theme.js:427`). The requested move — **make Frosted the
> default** (glass everywhere via CSS blur+saturate+rim, *without* the `glass-full`-gated
> SVG refraction / perf hit) — is a one-line flip to `'frosted'`. **But it must not ship
> until the color/metric fixes below land:** frosting glass *over* hued chrome makes the
> #1 violation worse, not better. Fix discipline first, then turn on the glass.

## Per-surface verdict

Legend: ✅ pass · ⚠️ issues · ⛔ blocker-class · (occ) occluded capture — needs re-shoot.

| Surface | One plane | Regular | **No hue on text** | ≤3 groups | 44px + focus | Notes |
|---|---|---|---|---|---|---|
| home / shell | ✅ | ✅ | ⛔ | ✅ | ⚠️ | nav labels+wordmark hued; send CTA wrong hue |
| portal | ✅ | ✅ | ⛔ | ⚠️ | ⚠️ | "Refresh" text button mixed into icon group; card straddles composer |
| chat / mind | ⚠️ | ✅ | ⛔ | ✅ | ⛔ | send-btn `--red`, **32px**; composer not adaptively flipping; modal-over-composer seam |
| vault | ✅ | ✅ | ⛔ | ✅ | ⚠️ | **three** red "Save" CTAs in one sheet; opaque sheet material ✅ |
| remote | ✅ | ✅ | ⛔ | ⚠️ | ⚠️ | custom **blue card border** (`applicantRemote.js:121`); two red primaries |
| activity | ⚠️ | ✅ | ⛔ | ✅ | ⚠️ | modal-over-composer glass; multiple tinted header buttons |
| debug | ⚠️ | ✅ | ⛔ | ⚠️ | ⚠️ | header >3 groups; active-tab hue; "Engine offline" correctly neutral ✅ |
| compare | ✅ | ✅ | ⛔ | ✅ | ⚠️ | native `<select>` off-kit (dark-on-dark chevron); hued field labels |
| onboarding | ✅ | ✅ | ⛔ | ✅ | ⛔ | `.cal-btn` **28px**; pink CTA + pink step-tab + pink focus ring; mobile stepper truncates |
| settings | ✅ | ✅ | ⛔ | ✅ | ⚠️ | active nav = pink-text-on-pink-tint; "None" empty-states read as errors |
| email | ✅ | ✅ | ⛔ | ⚠️ | ⚠️ | text+icon toolbar mix; blue-square window controls |
| gallery | ⚠️ | ✅ | ⛔ | ⚠️ | ⚠️ | segmented header >3 groups; window-over-wizard stacking |
| library | ✅ | ✅ | ⚠️ | ✅ | (occ) | cat-chips red; version badge/Import link red; framed tiles |
| memory | ✅ | ✅ | ⚠️ | ✅ | (occ) | **perpetual red "synapse sweep"** on every row (`style.css:7760`) |
| notes | ✅ | ✅ | ⚠️ | — | (occ) | red reminder/delete labels; content-fill tiles ✅ |
| calendar / tasks | (occ) | ✅ | ⛔ | ⚠️ | (occ) | **occluded by OOBE wizard** — re-shoot required |
| **installer TUI** | — | — | ✅ | — | — | mostly PASS; praised restraint; blue double-duty + warn-glyph nits |

## The fix list (deduplicated, severity-ranked, with anchors)

### ⛔ BLOCKER — the one fix that clears most of the debt
**B1 · Stop painting accent hue on chrome text/symbols (rule #5).** Retarget `--accent`/
`--red`/`--fg` so they only ever color **backgrounds / state fills**, never labels,
glyphs, headings, tabs, chips, or wordmarks. Chrome ink → neutral (`--ow-control-ink`/
neutral `--fg`). Selection = tint the **background**, not the label. Confirmed sites:
`.modal-header h4` (`style.css:4736`), `.settings-nav-item.active` (`:17794`),
`.admin-tab.active` (`:19262`), `.section-header-btn.active` (`:1227`),
`.mode-toggle-btn.active` (`:2496`), `.memory-cat-chip` hover/active (`:8087`),
tool indicators (`:2276-2286`); JS: `documentLibrary.js:396,512`, `applicantRemote.js`,
`calendar.js:728,951,1533,1551,1724`, `notes` labels (`style.css:753,26935,27676`).

**B2 · Primary CTA + focus ring = Apple system-blue `#0a84ff`, not the theme accent.**
`.cal-btn-primary`/`.send-btn` backgrounds are `var(--red)` (`style.css:30757, 2297`) →
`#0a84ff` with a **white** glyph. `:focus-visible` rings are `var(--red)` (`style.css:4951,
1442`) → fixed `#0a84ff`, ≥2–3px. This ring must be distinct from any theme accent so it
never reads as a hued label.

**B3 · 44px tap floor.** `.cal-btn { height:28px }` (`style.css:30755`) → `min-height:44px`;
`.send-btn` 32px (`:2302`) → ≥44px at all breakpoints. Applies to wizard buttons, selects,
titlebar controls.

### ⚠️ MAJOR
- **M1 · One prominent CTA per view.** Vault stacks three red "Save" plates, remote shows
  two red primaries. Demote per-section actions to neutral/secondary; keep exactly one
  prominent action (the final-submit in remote is the legitimate one, and is Apple's
  **Destructive role**, not brand pink). Prefer the kit's luminous-neutral `.ow-btn-prominent`
  over a solid color plate (219: a solid plate "breaks the character of Liquid Glass").
- **M2 · Toolbar grouping (≤3, no text+icon mixing, primary solo).** Email, Gallery,
  Calendar, Debug headers exceed three functional groups and mix text buttons with icon
  buttons on one plane. Regroup; float the primary solo. Ref `lg_hig_toolbar_grouping_correct.png`.
- **M3 · Audit out custom backgrounds/borders on sheets.** Remote's blue card border
  (`applicantRemote.js:121`, `#5b8def`) and the hard-black viewport (`:71`) — remove per
  HIG Sheets; convey emphasis with the one CTA, not a hued frame.
- **M4 · Neutral window controls.** Email/Gallery show blue-square minimize/close top-right;
  the only sanctioned colored window chrome is the top-left traffic-light cluster. Make them
  neutral monochrome.
- **M5 · Migrate legacy `cal-btn` surfaces to the `.ow-btn` kit.** Vault/remote/onboarding
  predate the kit; adopting it fixes size, focus, tint, and state discipline in one move.
  Also adopt `.ow-select` for the native `<select>` in Compare (dark-on-dark chevron).
- **M6 · Composer adaptive flip.** The composer is a "small element" and must flip
  light↔dark ink by backdrop luminance (~0.36); it currently uses static theme ink. The
  machinery exists (`appkitGlass.js`); wire the composer to it.

### 🟡 MINOR / MOTION
- **m1 · Kill the perpetual "synapse sweep."** `#memory-list .memory-item::after`
  (`style.css:7760-7787`) loops a red light sweep forever — gratuitous peripheral motion.
  Make it one-shot on insert, gate behind `prefers-reduced-motion`, and neutralize the hue.
- **m2 · Flatten stacked framed tiles** in memory/library lists to separator-delimited
  content rows (Apple floats one plane over flat content; it doesn't stack framed cards).
- **m3 · Route bespoke hint boxes through `AppkitNoticeKit`** (remote's opaque tooltip;
  the "Pro tip" gadget over content) so they share the material + reduce clutter.

### TUI (installer) — mostly PASS
Restraint, honest gated health bar, and a real NO_COLOR/ASCII fallback all earn praise.
Only: blue carries two meanings (URL vs emphasis — reserve it for URLs, drop the bold on
`APP_PORT`), and the warn glyph differs across paths (`ui_warn` `!` vs `render_health_block`
`○` — unify via a `G_WARN`). `scripts/install.sh` UI block `:99-201`.

## Capture gap (must re-shoot before sign-off)
The crawl ran on a fresh admin, so the **OOBE wizard occludes calendar/tasks/library/memory/
notes** (`route_notes` is byte-identical to `onboarding-desktop`). Re-run the crawl with
onboarding completed / the wizard dismissed to pixel-judge those content grids.

## The plan this audit sets up
1. Land **B1–B3** (+ the MAJORs) so the chrome is HIG-clean.
2. Flip **`DEFAULT_GLASS_TIER → 'frosted'`** (`theme.js:427`) — glass everywhere, no SVG
   perf hit — now that frosting won't amplify hued chrome.
3. Re-crawl (wizard dismissed) and re-audit the frosted result: render → compare to the
   Apple refs → tune, until each surface is indistinguishable from the reference *and*
   passes the a11y trio with glass stripped.
