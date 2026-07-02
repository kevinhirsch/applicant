# Liquid Glass — design research, decisions & implementation log

Durable record of the Apple "Liquid Glass" (iOS 26 / macOS 26 "Tahoe", WWDC25 June 2025)
parity work. **This folder is the authoritative design reference for the glass system** — all
of it was researched from Apple-authentic sources and is logged here so it survives (the live
work happened in an ephemeral scratchpad). It was vendored from the upstream fork's design corpus
into Applicant, whose implementation lives in the `appkit*` kits under `workspace/static/` (the
white-labeled public front-door). When changing any glass surface, read this first.

> **See also:** [`../APPLE_GENIUS.md`](../APPLE_GENIUS.md) — the "apple genius" design-reviewer SOUL: the operating distillation of this knowledge base into a reusable HIG-parity review voice.

## Contents

| File | What it is |
|---|---|
| `LIQUID_GLASS_REFERENCE.md` | The compiled, fully-sourced reference — every Apple rule with a **verbatim quote + source URL**, grouped by topic (layering, controls-vs-content, Regular/Clear variants + dimming, concentricity/toolbars/sidebars/sheets/menus, accessibility, optics). Lead section answers "does Apple do glass-on-glass?". |
| `ADAPTIVE_LEGIBILITY_REFERENCE.md` | Deep-dive on the **exact adaptive legibility mechanism** (size-dependent symbol flip, vibrancy, continuous luminosity adjust, Clear's 35% dimmer) + the most accurate **web replication** (CSS/SVG) with code. |
| `REFERENCE_MANIFEST.md` | Table of every authentic Apple image: filename / what it shows / source URL / authoritative. |
| `sources/` | **Verbatim** Apple source extracts — HIG pages (from the `/tutorials/data/*.json` endpoints) + WWDC25 219/356 transcripts. The raw material behind the quotes. |
| `images/` | The authentic Apple reference images (HIG asset CDN + apple.com Newsroom) used for pixel comparison. |

> Apple HIG/dev pages are JS SPAs — the HTML has no body text. Fetch the JSON data endpoints
> (`https://developer.apple.com/tutorials/data/design/human-interface-guidelines/<page>.json`)
> via curl with a browser UA + `--cacert /root/.ccr/ca-bundle.crt`. WebFetch only returns titles.

## The non-negotiable principles (owner directives)

1. **Authentic Apple always wins.** If there's no Apple element to mirror, don't invent one. Match
   pixel-for-pixel against the authentic references; iterate **3–10 parity passes per surface**
   (render → compare to the Apple ref → tune → repeat).
2. **The material is colorless/neutral.** Liquid Glass has no hue of its own; it takes color from the
   content behind it. No accent on the glass — **except** the two sanctioned, reference-backed accents:
   Apple **blue** on toggles, **green** on sliders, and a single **tinted primary-action CTA** (system
   blue background) per view.
3. **One glass layer over content — never glass-on-glass.** Liquid Glass is the *functional* layer
   floating above a *content* layer; "glass cannot properly sample other glass." Controls ride the
   parent material (vibrant fills), they don't carry their own glass.
4. **Legible over ANY background** (a photo, a light theme, a gradient, the dark chat) — via Apple's
   adaptive mechanism, not a static veil.
5. **Chromium-only refraction is a progressive enhancement** over a CSS-blur baseline; the fallback is
   pixel-identical except the lensing.

## Key decisions (what we built & why)

- **Material:** neutral frosted glass — gentle luminosity lift + a thin **directional** edge rim +
  soft float shadow + very-rounded **concentric** corners. Sheen is *subtle* (Apple is subtle); the
  broad top-gradient wash was dialed back.
- **Refraction (the lensing):** SVG `feImage`(squircle displacement map) → `feDisplacementMap` +
  in-filter blur + tint, applied via `backdrop-filter: url(#id)` — **Chromium-only**, set with inline
  `!important` so it beats the CSS `!important` blur (the bug that once made the whole effect invisible).
- **Specular:** the kube.io `feBlend` rim light = a **thin** highlight that "responds to geometry"
  (a hairline on the lit edge), NOT a wide glossy band.
- **macOS chrome:** traffic-light window controls top-left (the colored exception, not glass-refracted),
  3-light cluster (greyed when inert); Settings = sidebar app (title left over the content column);
  other windows center the title.
- **Glass-on-glass removed:** the gadget **rail** is a transparent container and the **cards** are the
  single glass tiles (Control Center model); in-window **buttons** are de-nested (vibrant fills, no
  nested backdrop-filter).
- **One tinted CTA:** composer Send + decision Confirm = a clean flat **system-blue** background +
  white glyph (Apple's usage-correct ref); everything else colorless.
- **Adaptive legibility (the adaptive layer in `appkitGlass.js`):** size-dependent, per Apple —
  - **Small** bars/tiles (composer, gadget cards, dock) stay **clear** and **flip the symbol** dark↔light
    by backdrop luminance (linear Y, flip at 0.36).
  - **Large** surfaces (sidebars, windows, modals, menus) **don't flip** (too big — distracting);
    the glass **mutes** adaptively (a stronger veil over bright) to keep the light `--fg` symbols legible.
  - Only sanctioned darkening is the Clear variant's 35% dimmer over bright media (not used — our
    surfaces carry text, so Regular is correct).
  - Accessibility wins: `prefers-contrast: more` drops the flip (black/white + border);
    `prefers-reduced-transparency` → opaque; `prefers-reduced-motion` → no elastic/specular motion.

## Implementation map

| Concern | Where |
|---|---|
| SVG refraction + specular (Chromium PE) | `workspace/static/js/appkitGlass.js` |
| Adaptive legibility (every engine) | `workspace/static/js/appkitGlass.js` (the adaptive-ink layer folded into the same file) |
| Material / chrome / CTA / traffic lights / tokens | `workspace/static/style.css` (`body.theme-frosted …`, the "AppKit design tokens" / ELEMENT KIT block) |
| Window kit (titlebar, controls, slots) | `workspace/static/js/appkitWindow.js` |
| Gadget kit (tiles) | `workspace/static/js/appkitGadget.js` |
| Atomic control primitives | `workspace/static/js/appkitElements.js` |
| Notice / decision / chat-hint kits | `workspace/static/js/appkitNotice.js`, `appkitDecision.js`, `appkitChatHint.js` |
| Gates | the front-door `workspace/tests/test_applicant_*` suite + the workspace JS `node --check` / compileall in CI (the original `frontend/tests/test_liquid_glass.py` etc. were engine-side gates that did not vendor across) |

## Verifying / parity passes

The parity loop is render-the-real-FE-under-Playwright → compose side-by-side with the authentic Apple
ref in `images/` → compare → tune → repeat (3–10×). Judge over a **realistic** backdrop (a photo and the
dark chat), never neon test bands. Before pushing, run the front-door checks CI gates
(`uv run pytest -q workspace/tests/test_applicant_*.py`, `node --check` on the touched
`workspace/static/js/*.js`, and `docs/playtest-protocol.md`'s Playwright UI crawl for live parity).

## Open / remaining polish

- **Vibrancy blend** — `mix-blend-mode: luminosity` on labels is the truest analog of Apple "vibrancy"
  (keep label lightness, pull hue/sat from backdrop); currently we do the color flip + halo only.
  Add carefully (needs `isolation: isolate`; can wash out — pair with the text-shadow floor).
- **Continuous** symbol adaptation for small bars (currently a discrete flip — which IS Apple-correct
  for small bars; the continuous part is the glass underneath).
- Mobile-first phase (iOS idioms) is tracked separately (#714).
