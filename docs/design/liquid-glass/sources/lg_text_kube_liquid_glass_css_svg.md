# Liquid Glass in the Browser: Refraction with CSS and SVG

> **Source:** kube.io — "Liquid Glass in the Browser: Refraction with CSS and SVG"
> **URL:** https://kube.io/blog/liquid-glass-css-svg/
> **Retrieved:** 2026-06-24 (via WebFetch; article reachable & complete).
> **Type:** Third-party technical write-up + author-published code snippets (NON-authoritative — it is
> a *web reimplementation* of Apple's effect, not an Apple source). Catalogs the CSS+SVG-displacement
> technique already **cited** in `ADAPTIVE_LEGIBILITY_REFERENCE.md` (line 342/531) and `README.md`
> (line 48 — the `feBlend` rim-light note).
>
> **Catalog note on completeness:** This is a faithful reproduction of *what the article publishes*.
> The author has **not** open-sourced the full implementation — there is **no linked CodePen / GitHub /
> JSFiddle**. In the article's own words: *"The code needs a cleanup pass and perf work before any
> possible open-source release."* The interactive demos exist on the page but their underlying source
> is **not** reproduced in the article body. So the verbatim code below (the displacement-map filter
> chain, the normal/derivative calc, the polar→Cartesian + RGB encoding, the surface equations, the
> `backdrop-filter` CSS) **is the complete published code set** — the full `feSpecularLighting` /
> `fePointLight` / `feComposite` specular filter markup and any `@supports` feature-detect are
> *described in prose but not shown as code* in the article.

---

## What this article is

Apple introduced **Liquid Glass** at WWDC 2025 — UI elements that look like curved, refractive glass.
This article presents a **web approximation** built with **CSS + an SVG displacement map** (NOT a
pixel-perfect recreation). It builds up from the physics of refraction, derives a displacement vector
field from a glass "surface function," bakes that field into an SVG displacement-map image, and applies
it through `feDisplacementMap` as a `backdrop-filter`. The live demo **only works in Chrome/Chromium**,
because Chromium is currently the only engine that exposes **SVG filters as `backdrop-filter`**.

Section order in the article:
1. Introduction
2. Understanding Refraction
3. Limitations in this project
4. Creating the Glass Surface
5. Surface Function
6. Equations
7. Simulation
8. Displacement Vector Field
9. Pre-calculating the displacement magnitude
10. Normalizing vectors
11. SVG Displacement Map
12. Scale
13. Vector to Red-Green values
14. Playground
15. Specular Highlight
16. Combining Refraction and Specular Highlight
17. SVG Filter as `backdrop-filter`
18. Bringing It All Together: Real UI Components
19. Magnifying Glass
20. Searchbox
21. Switch
22. Slider
23. Music Player
24. Conclusion

---

## The technique

### Understanding refraction (the physics)

Refraction is what happens when light changes direction as it passes from one material to another (e.g.
air → glass), because the speed of light differs between media. The governing relation is the
**Snell–Descartes law**:

```
n₁ · sin(θ₁) = n₂ · sin(θ₂)
```

where `n` is each medium's **index of refraction** and `θ` is the angle measured from the surface
**normal**. Consequences the author leans on:

- When the two indices match, light goes **straight through** (no bend).
- A **higher-index** material bends light **toward** the normal.
- A **lower-index** material bends light **away** from the normal (and past a critical angle gives
  **total internal reflection**).
- A ray **perpendicular** to the surface passes through **undeflected** regardless of the indices.

### Limitations the author imposes (to keep it tractable)

- Ambient medium index = **1** (air); the glass material index **> 1**, preferably **1.5** (glass).
- Only a **single** refraction event per ray.
- Incident rays are **perpendicular to the background**.
- The 2D shapes stay **parallel** to the background; **no gap** between object and background.
- **Circle shapes only** (other shapes need extra preliminary calculation).

### Creating the glass surface — the surface function

The glass is described by a **surface function** that gives the glass **height/thickness** at any point
from the **outer edge** to the **end of the bezel**. Its input is a value in `[0, 1]` (0 = outer edge,
1 = end of bezel / start of the flat interior); its output is the height at that point. The surface
**normal** is obtained from the function's **derivative** (a numerical central difference), then rotated
−90°:

```javascript
const delta = 0.001; // Small value to approximate derivative
const y1 = f(distanceFromSide - delta);
const y2 = f(distanceFromSide + delta);
const derivative = (y2 - y1) / (2 * delta);
const normal = { x: -derivative, y: 1 }; // Derivative, rotated by -90 degrees
```

```javascript
const height = f(distanceFromSide);
```

### Equations — the four surface profiles

`x` is the normalized distance-from-side in `[0,1]`; `y` is the normalized height.

**Convex circle** — easier than the squircle, but the transition into the flat interior is harsher,
producing sharper refraction edges:

```
y = √(1 - (1 - x)²)
```

**Convex squircle** — uses the **squircle Apple favors**: a softer flat→curve transition that keeps the
refraction gradients smooth even when the shape is stretched into a rectangle:

```
y = ⁴√(1 - (1 - x)⁴)
```

**Concave** — the complement of the convex function; a bowl-like depression:

```
y = 1 - Convex(x)
```

**Lip** — blends convex and concave via **Smootherstep** to make a raised rim with a shallow center dip
(used by the Switch component below):

```
y = mix(Convex(x), Concave(x), Smootherstep(x))
```

### Simulation & the displacement vector field

The simulation shows how surface shape steers rays: **concave** surfaces push rays **outside** the glass
boundary; **convex** surfaces keep them **inside**. Because displacement is **symmetric around the
bezel**, you *"compute once, reuse around the bezel/object."* The **displacement vector field** gives a
magnitude + direction at every surface position. Thanks to the radial symmetry, the author only
simulates a single **radius / half-slice** — **127 ray simulations** (count dictated by the SVG
displacement-map resolution) — and rotates the result around the z-axis (around the bezel) to fill the
whole object.

### Normalizing vectors

Vectors are normalized so the **maximum magnitude = 1**, giving a fixed `[0,1]` range that can be packed
into image channels:

```javascript
const maximumDisplacement = Math.max(...displacementMagnitudes);
displacementVector_normalized = {
  angle: normalAtBorder,
  magnitude: magnitude / maximumDisplacement,
};
```

### Scale (the `feDisplacementMap` `scale` attribute)

`<feDisplacementMap>` reads **8-bit channels (0–255)** where **128 = neutral / no displacement**. The
`scale` attribute multiplies the normalized displacement:

```
0   ↦ −scale
128 ↦  0
255 ↦ +scale
```

The author uses the **maximum displacement magnitude** directly as the filter's `scale`, turning the
normalized vectors back into real pixel shifts. Animating `scale` gives **fade in / out** of the effect
**without rebuilding the displacement map**.

### Vector → Red/Green values (encoding the map image)

Convert each polar vector (angle/magnitude) to Cartesian, then remap the `[-1, 1]` components into the
`[0, 255]` channel range. **Red = X-axis displacement, Green = Y-axis displacement**, Blue/Alpha fixed:

```javascript
// polar → cartesian
const x = Math.cos(angle) * magnitude;
const y = Math.sin(angle) * magnitude;

// cartesian (−1..1) → RGBA (0..255), 128 = neutral
const result = {
  r: 128 + x * 127,
  g: 128 + y * 127,
  b: 128,
  a: 255,
};
```

### Specular highlight (described; no code published)

A **rim-light** effect: the highlight appears **around the edges** of the glass object, and its
intensity varies with the **angle of the surface normal relative to a fixed light direction**. The demo
exposes controls (**Specular Angle** e.g. `-60°`, **Specular Opacity**, **Specular Saturation**). The
article does **not** publish the underlying `<feSpecularLighting>` / `<fePointLight>` / `<feComposite>`
markup. *(This is the `feBlend` rim-light the project's `README.md` line 48 cites as "a thin highlight
that responds to geometry.")*

### Combining refraction + specular highlight (described; partial code)

In the final filter, the **displacement map** (refraction) and the **specular highlight** are each
loaded as separate `<feImage>` elements and then **combined with `<feBlend>`** to overlay the highlight
on top of the refracted backdrop. The article shows the **refraction half** of the chain verbatim (see
the SVG filter below) but does **not** show the specular-blend step as code.

### SVG filter as `backdrop-filter` (the Chromium-only seam)

Only **Chrome/Chromium** currently supports using an **SVG filter as `backdrop-filter`**, which is what
makes the effect apply to live UI over arbitrary content:

```css
.glass-panel {
  backdrop-filter: url(#liquidGlassFilterId);
}
```

> Note (from the article): the `backdrop-filter` dimensions **do not** auto-adjust to the element size,
> so you must ensure the filter's images **match the size of the element** they're applied to.

### Real UI components built on it

- **Magnifying glass** — **two** displacement maps (one for side refraction, one for **zoom** with
  stronger refraction), plus shadow + scale for interaction.
- **Searchbox** — glass over a search input, with configurable specular opacity/saturation + refraction
  intensity.
- **Switch** — a **"lip" bezel** (convex outside, concave center): the slider looks zoomed-out while the
  edges refract the background.
- **Slider** — **convex** bezels let the user see the current level through the glass while the sides
  refract the backdrop.
- **Music player** — Apple-Music-style: convex bezels + subtle specular highlights, pulling album art
  via the iTunes Search API.

### Conclusion

The prototype distills Liquid Glass into **real-time refraction + simple rim highlighting**, flexible
within Chrome's constraints. Because *"only Chromium exposes SVG filters as `backdrop-filter`,"* it is
viable in Electron-based runtimes but needs **fallbacks** elsewhere. **Performance caveat:** dynamic
shape/size changes are costly because most tweaks force a **full displacement-map rebuild** (animating
`scale` is the cheap exception). **Open source:** not yet — *"The code needs a cleanup pass and perf
work before any possible open-source release."*

---

## Source code (verbatim, as published)

### SVG displacement-map filter (refraction)

The full filter chain the article publishes — an `feImage` of the pre-baked displacement-map data-URL
feeding `feDisplacementMap`, with **R → X** and **G → Y** channel selectors (JSX-style attribute
braces are the article's own):

```xml
<svg colorInterpolationFilters="sRGB">
  <filter id={id}>
    <feImage
      href={displacementMapDataUrl}
      x={0}
      y={0}
      width={width}
      height={height}
      result="displacement_map"
    />
    <feDisplacementMap
      in="SourceGraphic"
      in2="displacement_map"
      scale={scale}
      xChannelSelector="R" // Red Channel for displacement in X axis
      yChannelSelector="G" // Green Channel for displacement in Y axis
    />
  </filter>
</svg>
```

### CSS — apply the SVG filter as a backdrop filter (Chromium-only)

```css
.glass-panel {
  backdrop-filter: url(#liquidGlassFilterId);
}
```

### JS — surface height & normal (numerical derivative)

```javascript
const height = f(distanceFromSide);

const delta = 0.001; // Small value to approximate derivative
const y1 = f(distanceFromSide - delta);
const y2 = f(distanceFromSide + delta);
const derivative = (y2 - y1) / (2 * delta);
const normal = { x: -derivative, y: 1 }; // Derivative, rotated by -90 degrees
```

### JS — normalize displacement vectors (max magnitude → 1)

```javascript
const maximumDisplacement = Math.max(...displacementMagnitudes);
displacementVector_normalized = {
  angle: normalAtBorder,
  magnitude: magnitude / maximumDisplacement,
};
```

### JS — polar → Cartesian → RGBA channel encoding

```javascript
// polar (angle, magnitude) → cartesian (x, y)
const x = Math.cos(angle) * magnitude;
const y = Math.sin(angle) * magnitude;

// cartesian (−1..1) → RGBA (0..255); 128 = neutral (no displacement)
const result = {
  r: 128 + x * 127,
  g: 128 + y * 127,
  b: 128,
  a: 255,
};
```

### Math — surface profile equations

```text
Convex circle:    y = √(1 - (1 - x)²)
Convex squircle:  y = ⁴√(1 - (1 - x)⁴)        // the squircle Apple favors
Concave:          y = 1 - Convex(x)
Lip:              y = mix(Convex(x), Concave(x), Smootherstep(x))
```

### Math — Snell–Descartes law & the displacement-map scale mapping

```text
Snell–Descartes:  n₁ · sin(θ₁) = n₂ · sin(θ₂)

feDisplacementMap channel → displacement (scale attribute):
  0   ↦ −scale
  128 ↦  0          (neutral)
  255 ↦ +scale
```

---

## Linked code resources

**None.** The article does not link a CodePen / GitHub / JSFiddle; the author states the implementation
is **not yet open-sourced** ("needs a cleanup pass and perf work"). The verbatim snippets above are the
complete published code.
