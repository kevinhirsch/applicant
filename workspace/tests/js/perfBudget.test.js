// tests/js/perfBudget.test.js
//
// X-3 performance-budget regression guard — deterministic, no-browser source
// assertions for the CSS perf invariants X-3 relies on (see
// docs/performance-budget.md). These can't be pinned by the pixel harness
// (a compositing/GPU hint changes no pixels; reduced-motion isn't the harness's
// captured state), so they're guarded here in the CI-gated `npm test` suite the
// same way glassBackdropFallback.test.js guards the @supports fallback.
//
// Invariants asserted:
//   1. The aurora MESH animation stays gated behind prefers-reduced-motion
//      (belt-and-braces freeze) — no peripheral motion for motion-sensitive
//      users, and no continuous compositor work when they opt out.
//   2. The mesh drift + ray keyframes animate ONLY compositor-cheap properties
//      (transform / opacity) — never a repaint/reflow-forcing property
//      (background-position / filter / width / height / top / left), which would
//      re-rasterize the 54px gaussian blur every frame.
//   3. The frosted glass-BUTTON morph rule carries NO standing `will-change`
//      (X-3 cheap win): that selector matches every button in every glass
//      window/card/dock, so a permanent will-change promoted each to its own
//      GPU layer at rest. The press morph still transitions; the hint is gone.

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');

const STATIC = path.join(__dirname, '..', '..', 'static');
const MESH = fs.readFileSync(path.join(STATIC, 'css', 'meshGradient.css'), 'utf8');
const STYLE = fs.readFileSync(path.join(STATIC, 'style.css'), 'utf8');

const REPAINT_PROPS = ['background-position', 'filter', 'width', 'height', 'top', 'left'];

function keyframesBody(css, name) {
  const re = new RegExp('@keyframes\\s+' + name + '\\s*\\{', 'g');
  const m = re.exec(css);
  if (!m) return null;
  let i = m.index + m[0].length;
  let depth = 1;
  const start = i;
  for (; i < css.length && depth > 0; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') depth--;
  }
  return css.slice(start, i - 1);
}

test('aurora mesh animation stays gated behind prefers-reduced-motion', () => {
  const m = /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{([\s\S]*?)\}\s*$/.exec(MESH.trim());
  assert.ok(m, 'meshGradient.css must end with a prefers-reduced-motion block');
  const body = m[1];
  assert.match(body, /animation:\s*none\s*!important/,
    'reduced-motion must freeze the mesh animation');
  assert.match(body, /\.login-bg-gradient::before,\s*\.login-bg-gradient::after/,
    'reduced-motion must freeze BOTH the blurred mesh and the aurora ray layers');
});

test('mesh drift + ray keyframes animate only compositor-cheap props', () => {
  for (const name of ['login-mesh-drift', 'login-ray-sweep']) {
    const body = keyframesBody(MESH, name);
    assert.ok(body, `expected @keyframes ${name}`);
    assert.match(body, /transform:/, `${name} must animate transform`);
    for (const prop of REPAINT_PROPS) {
      assert.ok(
        !new RegExp('(^|[;{\\s])' + prop + '\\s*:').test(body),
        `${name} must not animate the repaint/reflow-forcing property '${prop}'`,
      );
    }
  }
});

test('frosted glass-button morph rule carries no standing will-change (X-3 win)', () => {
  // `body.theme-frosted .ow-window .ow-body button` heads several rules; the
  // MORPH rule is uniquely the one whose block carries the springy press
  // transition `cubic-bezier(.34,1.56,.64,1)`. Walk every occurrence, extract
  // its block, and pick that one — then assert the morph transition is still
  // there (right rule) and no standing `will-change` remains.
  const anchor = 'body.theme-frosted .ow-window .ow-body button';
  const MORPH = 'cubic-bezier(.34,1.56,.64,1)';
  let morphBlock = null;
  for (let at = STYLE.indexOf(anchor); at >= 0; at = STYLE.indexOf(anchor, at + 1)) {
    const open = STYLE.indexOf('{', at);
    const close = STYLE.indexOf('}', open);
    if (open < 0 || close < 0) continue;
    const block = STYLE.slice(open + 1, close);
    if (block.includes(MORPH)) { morphBlock = block; break; }
  }
  assert.ok(morphBlock, `expected the glass-button morph rule (${MORPH}) in style.css`);
  assert.match(morphBlock, /transition:[^;]*transform/,
    'the glass-button morph rule should still transition its press-morph transform');
  // Strip CSS comments so the rationale comment (which names will-change) can't
  // masquerade as a live declaration.
  const decls = morphBlock.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.ok(
    !/will-change/.test(decls),
    'the frosted glass-button morph rule must not carry a standing will-change — it ' +
    'promoted every glass button to its own GPU layer at rest (X-3 cheap win)',
  );
});
