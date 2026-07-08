// workspace/tests/visual/png.js
//
// Minimal, dependency-free PNG codec + pixel comparator for the visual
// regression harness (P0-6). Pure Node (node:zlib only) so the harness needs
// no npm install — the same reason the JS unit suite runs on node:test alone.
//
// Scope is deliberately narrow: 8-bit-depth, non-interlaced RGB/RGBA PNGs —
// exactly what Playwright's Chromium screenshots and this module's own
// encoder produce. Anything else is rejected loudly (a harness input bug,
// not something to silently mis-decode).
//
// API:
//   decodePNG(buf)                 -> { width, height, data }  (data = RGBA Buffer)
//   encodePNG(width, height, data) -> Buffer   (RGB when fully opaque, max deflate)
//   comparePNG(bufA, bufB)         -> { equal, diffCount, total, width, height,
//                                       note, diffImage }  (diffImage = PNG Buffer
//                                       highlighting differing pixels, null when equal)

'use strict';

const zlib = require('node:zlib');

const SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

// ── CRC32 (PNG chunk checksums) ──────────────────────────────────────────────
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// ── Decode ───────────────────────────────────────────────────────────────────

function paeth(a, b, c) {
  const p = a + b - c;
  const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a;
  if (pb <= pc) return b;
  return c;
}

function decodePNG(buf) {
  if (!Buffer.isBuffer(buf) || buf.length < 8 || !buf.subarray(0, 8).equals(SIGNATURE)) {
    throw new Error('not a PNG (bad signature)');
  }
  let off = 8;
  let width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0;
  const idat = [];
  while (off + 8 <= buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('latin1', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === 'IDAT') {
      idat.push(data);
    } else if (type === 'IEND') {
      break;
    }
    off += 12 + len; // len + type + data + crc
  }
  if (!width || !height) throw new Error('PNG missing IHDR');
  if (bitDepth !== 8) throw new Error(`unsupported PNG bit depth ${bitDepth} (harness handles 8)`);
  if (colorType !== 2 && colorType !== 6) {
    throw new Error(`unsupported PNG color type ${colorType} (harness handles RGB/RGBA)`);
  }
  if (interlace !== 0) throw new Error('unsupported interlaced PNG');

  const channels = colorType === 6 ? 4 : 3;
  const raw = zlib.inflateSync(Buffer.concat(idat));
  const stride = width * channels;
  const out = Buffer.alloc(width * height * 4);

  let pos = 0;
  const prev = Buffer.alloc(stride); // previous unfiltered scanline (zeros for row 0)
  const cur = Buffer.alloc(stride);
  for (let y = 0; y < height; y++) {
    const filter = raw[pos++];
    for (let x = 0; x < stride; x++) {
      const rawByte = raw[pos + x];
      const left = x >= channels ? cur[x - channels] : 0;
      const up = prev[x];
      const upLeft = x >= channels ? prev[x - channels] : 0;
      let v;
      switch (filter) {
        case 0: v = rawByte; break;
        case 1: v = rawByte + left; break;
        case 2: v = rawByte + up; break;
        case 3: v = rawByte + ((left + up) >> 1); break;
        case 4: v = rawByte + paeth(left, up, upLeft); break;
        default: throw new Error(`bad PNG filter ${filter} at row ${y}`);
      }
      cur[x] = v & 0xff;
    }
    pos += stride;
    // Expand to RGBA.
    let o = y * width * 4;
    for (let x = 0; x < width; x++) {
      const i = x * channels;
      out[o] = cur[i];
      out[o + 1] = cur[i + 1];
      out[o + 2] = cur[i + 2];
      out[o + 3] = channels === 4 ? cur[i + 3] : 255;
      o += 4;
    }
    cur.copy(prev);
  }
  return { width, height, data: out };
}

// ── Encode ───────────────────────────────────────────────────────────────────

function _chunk(type, data) {
  const head = Buffer.alloc(8);
  head.writeUInt32BE(data.length, 0);
  head.write(type, 4, 'latin1');
  const crcBuf = Buffer.alloc(4);
  crcBuf.writeUInt32BE(crc32(Buffer.concat([head.subarray(4), data])), 0);
  return Buffer.concat([head, data, crcBuf]);
}

/**
 * Encode RGBA pixel data to a PNG Buffer. Drops the alpha channel (RGB
 * output) when every pixel is opaque — screenshots always are — for ~25%
 * smaller committed baselines. Lossless either way. Per-scanline adaptive
 * filtering (min sum-of-absolute-differences heuristic) + max deflate.
 */
function encodePNG(width, height, data) {
  if (data.length !== width * height * 4) {
    throw new Error(`pixel buffer length ${data.length} != ${width}x${height}x4`);
  }
  let opaque = true;
  for (let i = 3; i < data.length; i += 4) {
    if (data[i] !== 255) { opaque = false; break; }
  }
  const channels = opaque ? 3 : 4;
  const colorType = opaque ? 2 : 6;
  const stride = width * channels;

  // Repack RGBA -> RGB(A) scanlines.
  const lines = Buffer.alloc(height * stride);
  for (let y = 0; y < height; y++) {
    let o = y * stride;
    let i = y * width * 4;
    for (let x = 0; x < width; x++) {
      lines[o] = data[i];
      lines[o + 1] = data[i + 1];
      lines[o + 2] = data[i + 2];
      if (channels === 4) lines[o + 3] = data[i + 3];
      o += channels;
      i += 4;
    }
  }

  const filtered = Buffer.alloc(height * (stride + 1));
  const cand = Buffer.alloc(stride);
  const best = Buffer.alloc(stride);
  for (let y = 0; y < height; y++) {
    const row = lines.subarray(y * stride, (y + 1) * stride);
    const prev = y > 0 ? lines.subarray((y - 1) * stride, y * stride) : null;
    let bestFilter = 0;
    let bestScore = Infinity;
    for (let f = 0; f < 5; f++) {
      let score = 0;
      for (let x = 0; x < stride; x++) {
        const left = x >= channels ? row[x - channels] : 0;
        const up = prev ? prev[x] : 0;
        const upLeft = prev && x >= channels ? prev[x - channels] : 0;
        let v;
        switch (f) {
          case 0: v = row[x]; break;
          case 1: v = row[x] - left; break;
          case 2: v = row[x] - up; break;
          case 3: v = row[x] - ((left + up) >> 1); break;
          default: v = row[x] - paeth(left, up, upLeft); break;
        }
        v &= 0xff;
        cand[x] = v;
        score += v < 128 ? v : 256 - v; // minimize |signed residual|
        if (score >= bestScore) { score = Infinity; break; } // early out
      }
      if (score < bestScore) { bestScore = score; bestFilter = f; cand.copy(best); }
    }
    const o = y * (stride + 1);
    filtered[o] = bestFilter;
    best.copy(filtered, o + 1);
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;          // bit depth
  ihdr[9] = colorType;  // 2 = RGB, 6 = RGBA
  ihdr[10] = 0;         // compression
  ihdr[11] = 0;         // filter method
  ihdr[12] = 0;         // no interlace
  const idat = zlib.deflateSync(filtered, { level: 9 });
  return Buffer.concat([
    SIGNATURE,
    _chunk('IHDR', ihdr),
    _chunk('IDAT', idat),
    _chunk('IEND', Buffer.alloc(0)),
  ]);
}

// ── Posterize ────────────────────────────────────────────────────────────────

/**
 * Quantize color channels to 5 bits (32 levels, alpha untouched), in place.
 * Both the blessed baseline AND every compared screenshot pass through this
 * SAME transform, so the zero-diff determinism contract is unchanged — it
 * only shrinks the committed PNGs (the glass gradients deflate ~55% smaller).
 * Cost: a uniform color shift smaller than one 8/255 quantum in an otherwise
 * pixel-identical frame can quantize away; any real layout/text/theme
 * regression moves pixels far beyond that.
 */
function posterize(data) {
  for (let i = 0; i < data.length; i++) {
    if ((i & 3) === 3) continue; // keep alpha exact
    const v = data[i];
    data[i] = (v & 0xf8) | (v >> 5); // 5 significant bits, replicated to fill
  }
  return data;
}

// ── Compare ──────────────────────────────────────────────────────────────────

/**
 * Per-channel pixel comparison with a bounded GLYPH-EDGE tolerance. Returns a
 * diff image (baseline dimmed to grayscale, differing pixels solid red) when
 * the two differ. A size mismatch is reported as a total diff with a note (no
 * pixel walk).
 *
 * The tolerance (the standard anti-aliasing heuristic, cf. pixelmatch): a
 * differing pixel is excused when the CURRENT pixel's exact value appears
 * among the baseline's 8 neighbors at that location, or vice versa — i.e. the
 * paint moved by at most one pixel of glyph-edge/AA rounding, which Chromium's
 * per-launch glyph cache genuinely does to text edges (verified: runs within
 * one launch are byte-identical; separate launches disagree by ±1px on
 * scattered text rows). A REAL regression — moved, added, removed or recolored
 * UI — changes pixel blocks whose values match no neighbor, and still fails.
 * The excused count is capped (0.5% of the frame) so large coherent movement
 * can never hide inside the tolerance, and is reported in `note` honestly.
 */
function comparePNG(bufA, bufB) {
  const a = decodePNG(bufA);
  const b = decodePNG(bufB);
  if (a.width !== b.width || a.height !== b.height) {
    return {
      equal: false,
      diffCount: a.width * a.height,
      total: a.width * a.height,
      width: a.width,
      height: a.height,
      note: `size mismatch: baseline ${a.width}x${a.height} vs current ${b.width}x${b.height}`,
      diffImage: null,
    };
  }
  const total = a.width * a.height;
  const W = a.width, H = a.height;
  const sameRGBA = (buf, j, r, g, bl, al) =>
    buf[j] === r && buf[j + 1] === g && buf[j + 2] === bl && buf[j + 3] === al;
  // Does (x,y)'s exact RGBA in `self` appear among (x,y)'s 8 neighbors in `other`?
  const neighborMatch = (self, other, x, y) => {
    const i = (y * W + x) * 4;
    const r = self[i], g = self[i + 1], bl = self[i + 2], al = self[i + 3];
    for (let dy = -1; dy <= 1; dy++) {
      for (let dx = -1; dx <= 1; dx++) {
        if (!dx && !dy) continue;
        const nx = x + dx, ny = y + dy;
        if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
        if (sameRGBA(other, (ny * W + nx) * 4, r, g, bl, al)) return true;
      }
    }
    return false;
  };
  let diffCount = 0;
  let aaTolerated = 0;
  const toleratedIdx = [];
  let diff = null;
  const ensureCanvas = () => {
    if (diff) return;
    // Lazily build the diff canvas: grayscale-dimmed baseline.
    diff = Buffer.alloc(total * 4);
    for (let q = 0; q < total; q++) {
      const j = q * 4;
      const g = Math.round((a.data[j] * 0.299 + a.data[j + 1] * 0.587 + a.data[j + 2] * 0.114) * 0.4 + 140);
      diff[j] = g; diff[j + 1] = g; diff[j + 2] = g; diff[j + 3] = 255;
    }
  };
  for (let p = 0; p < total; p++) {
    const i = p * 4;
    if (a.data[i] !== b.data[i] || a.data[i + 1] !== b.data[i + 1] ||
        a.data[i + 2] !== b.data[i + 2] || a.data[i + 3] !== b.data[i + 3]) {
      const x = p % W, y = (p / W) | 0;
      if (neighborMatch(b.data, a.data, x, y) && neighborMatch(a.data, b.data, x, y)) {
        aaTolerated++;
        toleratedIdx.push(i);
        continue;
      }
      ensureCanvas();
      diff[i] = 255; diff[i + 1] = 0; diff[i + 2] = 0; diff[i + 3] = 255;
      diffCount++;
    }
  }
  // The tolerance is bounded: past 0.5% of the frame, "AA jitter" is not a
  // credible explanation and the frame fails outright — and the pixels that
  // blew the cap must appear IN the diff image (amber, vs red for hard
  // mismatches), or a tolerance-only failure would point at a diff artifact
  // that was never painted.
  if (aaTolerated > total * 0.005) {
    diffCount += aaTolerated;
    ensureCanvas();
    for (const j of toleratedIdx) {
      diff[j] = 255; diff[j + 1] = 165; diff[j + 2] = 0; diff[j + 3] = 255;
    }
  }
  return {
    equal: diffCount === 0,
    diffCount,
    aaTolerated,
    total,
    width: a.width,
    height: a.height,
    note: diffCount
      ? `${diffCount}/${total} pixels differ${aaTolerated ? ` (+${aaTolerated} within the glyph-edge tolerance)` : ''}`
      : (aaTolerated ? `equal (${aaTolerated} px within the glyph-edge tolerance)` : ''),
    diffImage: diff ? encodePNG(a.width, a.height, diff) : null,
  };
}

module.exports = { decodePNG, encodePNG, comparePNG, posterize, crc32 };
