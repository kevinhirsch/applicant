// tests/js/visualPng.test.js
//
// Hermetic unit tests for the visual harness's dependency-free PNG codec +
// comparator (workspace/tests/visual/png.js). These ride the per-PR `npm test`
// lane so a codec regression can't silently corrupt the visual baselines,
// while the live screenshot walk itself stays in the on-demand visual lane
// (it needs a booted front-door + a browser).

'use strict';

const test = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

const { decodePNG, encodePNG, comparePNG, posterize } = require(path.join(__dirname, '..', 'visual', 'png.js'));

function gradient(width, height, alpha = 255) {
  const data = Buffer.alloc(width * height * 4);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = (y * width + x) * 4;
      data[i] = (x * 7) & 0xff;
      data[i + 1] = (y * 11) & 0xff;
      data[i + 2] = (x + y) & 0xff;
      data[i + 3] = alpha;
    }
  }
  return data;
}

test('encode/decode roundtrips RGBA pixels exactly (opaque -> RGB path)', () => {
  const w = 37, h = 23; // deliberately not powers of two
  const px = gradient(w, h);
  const png = encodePNG(w, h, px);
  const back = decodePNG(png);
  assert.equal(back.width, w);
  assert.equal(back.height, h);
  assert.ok(back.data.equals(px), 'decoded pixels must equal the encoded input');
});

test('encode keeps the alpha channel when pixels are not opaque', () => {
  const w = 9, h = 9;
  const px = gradient(w, h, 128);
  const back = decodePNG(encodePNG(w, h, px));
  assert.ok(back.data.equals(px));
});

test('comparePNG reports equal for identical images', () => {
  const png = encodePNG(16, 16, gradient(16, 16));
  const cmp = comparePNG(png, png);
  assert.equal(cmp.equal, true);
  assert.equal(cmp.diffCount, 0);
  assert.equal(cmp.diffImage, null);
});

test('comparePNG counts changed pixels and produces a diff image', () => {
  const w = 16, h = 16;
  const a = gradient(w, h);
  const b = Buffer.from(a);
  // flip three pixels
  for (const p of [0, 5, 200]) b[p * 4] = b[p * 4] ^ 0xff;
  const cmp = comparePNG(encodePNG(w, h, a), encodePNG(w, h, b));
  assert.equal(cmp.equal, false);
  assert.equal(cmp.diffCount, 3);
  assert.ok(Buffer.isBuffer(cmp.diffImage), 'diff image must be produced');
  const diff = decodePNG(cmp.diffImage);
  // the flipped pixel must be marked solid red
  assert.equal(diff.data[0], 255);
  assert.equal(diff.data[1], 0);
  assert.equal(diff.data[2], 0);
});

test('posterize is idempotent and keeps alpha exact', () => {
  const px = gradient(8, 8, 200);
  const once = posterize(Buffer.from(px));
  const twice = posterize(Buffer.from(once));
  assert.ok(once.equals(twice), 'a second posterize pass must be a no-op (baseline == re-shot)');
  for (let i = 3; i < px.length; i += 4) assert.equal(once[i], px[i], 'alpha untouched');
  // channels land on 32 replicated levels: (v & 0xf8) | (v >> 5)
  for (let i = 0; i < px.length; i++) {
    if ((i & 3) === 3) continue;
    assert.equal(once[i], (px[i] & 0xf8) | (px[i] >> 5));
  }
});

test('comparePNG flags a size mismatch instead of walking pixels', () => {
  const a = encodePNG(8, 8, gradient(8, 8));
  const b = encodePNG(9, 8, gradient(9, 8));
  const cmp = comparePNG(a, b);
  assert.equal(cmp.equal, false);
  assert.match(cmp.note, /size mismatch/);
});
