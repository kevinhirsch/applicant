#!/usr/bin/env python3
"""Automated low-contrast (two-ink leak) audit across every front-door surface.

For each surface, walks every VISIBLE element that renders its own text, computes
the WCAG contrast ratio between the element's computed text color and its effective
background (walking ancestors until an opaque background is found, defaulting to the
page background), and flags any text with contrast below a threshold. This objectively
catches "light ink on light glass" (and any other low-contrast) text on ANY page,
rather than relying on visual inspection.

Reuses SURFACES / login / BASE / CHROMIUM from playtest_crawl.py.

Usage:
  PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers FRONTDOOR_URL=http://127.0.0.1:7000 \
  ADMIN_USER=admin ADMIN_PASSWORD=playtest1234 python scripts/contrast_audit.py
Output: contrast-audit-results.json + a console summary.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import playtest_crawl as C  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

BASE = C.BASE
THRESHOLD = float(os.environ.get("CONTRAST_MIN", "3.0"))  # WCAG AA large-text floor
RESULTS = Path(os.environ.get("CONTRAST_RESULTS", "contrast-audit-results.json"))

# JS injected into each surface: returns low-contrast text elements.
SCAN_JS = r"""
(threshold) => {
  const toRGB = (s) => {
    if (!s) return null;
    const m = s.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(',').map(x => parseFloat(x.trim()));
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };
  const lin = (c) => { c /= 255; return c <= 0.03928 ? c/12.92 : Math.pow((c+0.055)/1.055, 2.4); };
  const lum = (c) => 0.2126*lin(c.r) + 0.7152*lin(c.g) + 0.0722*lin(c.b);
  const ratio = (a, b) => { const L1=lum(a), L2=lum(b); const hi=Math.max(L1,L2), lo=Math.min(L1,L2); return (hi+0.05)/(lo+0.05); };
  // effective background: walk ancestors until an opaque-ish bg; default page bg.
  const pageBg = toRGB(getComputedStyle(document.body).backgroundColor) || {r:255,g:255,b:255,a:1};
  const effBg = (el) => {
    let e = el;
    while (e && e !== document.documentElement) {
      const bg = toRGB(getComputedStyle(e).backgroundColor);
      if (bg && bg.a >= 0.6) return bg;
      e = e.parentElement;
    }
    return pageBg;
  };
  const out = [];
  const seen = new Set();
  const els = document.querySelectorAll('body *');
  for (const el of els) {
    // only elements with their OWN visible text (a direct non-empty text node)
    let ownText = '';
    for (const n of el.childNodes) if (n.nodeType === 3) ownText += n.textContent;
    ownText = ownText.trim();
    if (!ownText || ownText.length < 2) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.15) continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 4 || rect.height < 4) continue;
    const fg = toRGB(cs.color);
    if (!fg || fg.a < 0.3) continue;
    const bg = effBg(el);
    const r = ratio(fg, bg);
    if (r < threshold) {
      const key = ownText.slice(0,40) + '|' + el.className;
      if (seen.has(key)) continue;
      seen.add(key);
      out.push({
        text: ownText.slice(0, 60),
        tag: el.tagName.toLowerCase(),
        cls: (typeof el.className === 'string' ? el.className : '').slice(0, 80),
        color: cs.color,
        bg: `rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})`,
        ratio: Math.round(r * 100) / 100,
      });
    }
  }
  out.sort((a,b) => a.ratio - b.ratio);
  return out;
}
"""


async def main():
    all_findings = {}
    async with async_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}
        if C.CHROMIUM:
            kw["executable_path"] = C.CHROMIUM
        browser = await p.chromium.launch(**kw)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        ok, status, _ = await C.login(ctx)
        print(f"[login] ok={ok} status={status}", flush=True)
        if not ok:
            return 1
        for name, opener, _root, _purpose in C.SURFACES:
            page = await ctx.new_page()
            try:
                await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(700)
                if opener:
                    if opener.startswith("CLICK:"):
                        el = await page.query_selector(opener.split("CLICK:", 1)[1])
                        if el:
                            try:
                                await el.click(timeout=4000)
                            except Exception:
                                pass
                    else:
                        try:
                            await page.evaluate(f"() => {{ {opener}; }}")
                        except Exception:
                            pass
                    await page.wait_for_timeout(1600)
                findings = await page.evaluate(SCAN_JS, THRESHOLD)
            except Exception as e:
                findings = [{"error": str(e).splitlines()[0][:160]}]
            all_findings[name] = findings
            n = len([f for f in findings if "error" not in f])
            worst = findings[0]["ratio"] if findings and "ratio" in findings[0] else "-"
            print(f"[{name}] low-contrast text elements: {n} (worst ratio {worst})", flush=True)
            for f in findings[:6]:
                if "error" in f:
                    print(f"    ERROR: {f['error']}")
                else:
                    print(f"    {f['ratio']:>5} | {f['color']} on {f['bg']} | .{f['cls'][:40]} | {f['text'][:38]!r}")
            await page.close()
        await browser.close()
    RESULTS.write_text(json.dumps(all_findings, indent=2))
    total = sum(len([x for x in v if "error" not in x]) for v in all_findings.values())
    print(f"\nWrote {RESULTS}. Total low-contrast (<{THRESHOLD}:1) text elements across all surfaces: {total}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
