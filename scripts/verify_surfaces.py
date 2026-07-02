#!/usr/bin/env python3
"""Screenshot-verify every Applicant front-door surface (acceptance-criterion gate).

A lean, robust complement to playtest_crawl.py: it opens each surface via its JS
seam (or route), waits, screenshots it, and records console/pageerror/HTTP-5xx —
but deliberately does NOT click controls (the monkey-crawl's control-exercising
phase is what destabilises Chromium under load). One browser, sequential, short
per-surface timeouts, per-surface try/except so one bad surface can't abort the run.

Reuses SURFACES / ROUTED_PAGES / login / BASE / CHROMIUM from playtest_crawl.py so
the surface inventory stays in one place.

Usage:
  PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers \
  FRONTDOOR_URL=http://127.0.0.1:7000 ADMIN_USER=admin ADMIN_PASSWORD=playtest1234 \
  python scripts/verify_surfaces.py
Output:
  playtest-screens/<surface>-<viewport>.png
  surface-verify-results.json  (per-surface rendered/console/pageerror/5xx)
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from playwright.async_api import async_playwright  # noqa: E402
import playtest_crawl as C  # noqa: E402

OUTDIR = Path(os.environ.get("CRAWL_OUT", "playtest-screens"))
OUTDIR.mkdir(parents=True, exist_ok=True)
RESULTS = Path(os.environ.get("VERIFY_RESULTS", "surface-verify-results.json"))
BASE = C.BASE


async def shoot(page, name, tag, rec):
    shot = OUTDIR / f"{name}-{tag}.png"
    try:
        await page.screenshot(path=str(shot), full_page=True)
        rec["screenshot"] = str(shot)
    except Exception as e:
        rec["notes"].append(f"screenshot failed: {str(e).splitlines()[0][:120]}")


async def open_surface(page, name, opener, root, tag):
    rec = {"surface": name, "viewport": tag, "console": 0, "pageerr": 0,
           "http_5xx": 0, "rendered": None, "root_found": None, "notes": []}
    console, perr, x5 = [], [], []
    page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: perr.append(str(e)))
    page.on("response", lambda r: x5.append(r.url) if r.status >= 500 else None)
    try:
        if opener:
            if opener.startswith("CLICK:"):
                sel = opener.split("CLICK:", 1)[1]
                el = await page.query_selector(sel)
                if el:
                    try:
                        await el.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    try:
                        await el.click(timeout=4000)
                    except Exception:
                        try:
                            await el.click(timeout=2000, force=True)
                        except Exception as e:
                            rec["notes"].append(f"opener click failed: {str(e).splitlines()[0][:100]}")
                else:
                    rec["notes"].append(f"opener selector {sel} not found")
            else:
                try:
                    await page.evaluate(f"() => {{ {opener}; }}")
                except Exception as e:
                    rec["notes"].append(f"opener threw: {str(e).splitlines()[0][:120]}")
            await page.wait_for_timeout(1400)
        if root:
            try:
                await page.wait_for_selector(root, timeout=4000, state="visible")
                rec["root_found"] = True
            except Exception:
                rec["root_found"] = False
                rec["notes"].append(f"root {root} not visible")
        rec["rendered"] = True
    except Exception as e:
        rec["rendered"] = False
        rec["notes"].append(f"FATAL: {str(e).splitlines()[0][:160]}")
    await shoot(page, name, tag, rec)
    rec["console"] = len(console)
    rec["console_texts"] = [c[:200] for c in console[:8]]
    rec["pageerr"] = len(perr)
    rec["pageerr_texts"] = [e[:200] for e in perr[:8]]
    rec["http_5xx"] = len(x5)
    return rec


async def main():
    results = []
    async with async_playwright() as p:
        kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}
        if C.CHROMIUM:
            kwargs["executable_path"] = C.CHROMIUM
        browser = await p.chromium.launch(**kwargs)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        ok, status, body = await C.login(ctx)
        print(f"[login] ok={ok} status={status}", flush=True)
        if not ok:
            RESULTS.write_text(json.dumps({"login_ok": False, "status": status, "body": body}, indent=2))
            await browser.close()
            return 1
        # Desktop: JS-seam surfaces (fresh page each so state can't leak / crash-cascade)
        for name, opener, root, _purpose in C.SURFACES:
            page = await ctx.new_page()
            try:
                await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(800)
                rec = await open_surface(page, name, opener, root, "desktop")
            except Exception as e:
                rec = {"surface": name, "viewport": "desktop", "rendered": False,
                       "notes": [f"FATAL: {str(e).splitlines()[0][:160]}"],
                       "console": 0, "pageerr": 0, "http_5xx": 0}
            print(f"[{name}] rendered={rec.get('rendered')} console={rec['console']} "
                  f"pageerr={rec['pageerr']} 5xx={rec['http_5xx']} notes={rec['notes'][:1]}", flush=True)
            results.append(rec)
            await page.close()
        # Routed vendored pages
        for path in C.ROUTED_PAGES:
            name = "route_" + path.strip("/").replace("/", "_")
            page = await ctx.new_page()
            rec = {"surface": name, "viewport": "desktop", "console": 0, "pageerr": 0,
                   "http_5xx": 0, "rendered": None, "notes": []}
            console, perr = [], []
            page.on("console", lambda m: console.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: perr.append(str(e)))
            try:
                r = await page.goto(BASE + path, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(1000)
                if r and r.status >= 500:
                    rec["http_5xx"] = 1
                rec["rendered"] = True
            except Exception as e:
                rec["rendered"] = False
                rec["notes"].append(f"FATAL: {str(e).splitlines()[0][:160]}")
            await shoot(page, name, "desktop", rec)
            rec["console"] = len(console)
            rec["pageerr"] = len(perr)
            print(f"[{name}] rendered={rec.get('rendered')} console={rec['console']} pageerr={rec['pageerr']}", flush=True)
            results.append(rec)
            await page.close()
        await browser.close()
    RESULTS.write_text(json.dumps({"login_ok": True, "surfaces": results}, indent=2))
    issues = sum(1 for r in results if r.get("pageerr") or r.get("http_5xx")
                 or r.get("rendered") is False or r.get("root_found") is False)
    print(f"\nWrote {RESULTS} ({len(results)} surfaces); screens in {OUTDIR}", flush=True)
    print(f"Surfaces with notable issues: {issues}/{len(results)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
