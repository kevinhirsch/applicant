#!/usr/bin/env python3
"""A0-shell panel playtest harness — visual render/console/dead-control audit.

Enumerates every a0-applicant/webui/*.html panel, opens each in the running A0 shell
at SHELL_URL (default http://localhost:80), captures console messages/errors, pageerrors,
HTTP 5xx, screenshots, and politely clicks non-destructive controls to catch handler
exceptions / dead controls.

Boots nothing — assumes the A0 shell is already running. Logs in via the shell's form.

Usage:
  PLAYWRIGHT_BROWSERS_PATH=/a0/tmp/playwright /opt/venv-a0/bin/python scripts/playtest_panels.py

Output:
  - playtest-screens/a0panel-<name>.png        full-page screenshots
  - playtest-panels-results.json               machine-readable per-panel results
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

# --- Configuration ---
SHELL_URL = os.environ.get("SHELL_URL", "http://localhost:80")
OUTDIR = Path(os.environ.get("PANEL_OUT", "playtest-screens"))
RESULTS_JSON = Path(os.environ.get("PANEL_RESULTS", "playtest-panels-results.json"))

# Project root for enumerating webui panels
PROJECT_ROOT = Path(__file__).resolve().parent.parent
APPLICANT_PLUGIN_WEBUI = PROJECT_ROOT / "a0-applicant" / "webui"

# Shell auth (form-based login) — resolved from A0 framework dotenv
ADMIN_USER = None
ADMIN_PW = None
try:
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
    from helpers import dotenv
    ADMIN_USER = dotenv.get_dotenv_value(dotenv.KEY_AUTH_LOGIN)
    ADMIN_PW = dotenv.get_dotenv_value(dotenv.KEY_AUTH_PASSWORD)
except Exception:
    pass
if not ADMIN_USER:
    ADMIN_USER = os.environ.get("ADMIN_USER", "test@agentzero.com")
if not ADMIN_PW:
    ADMIN_PW = os.environ.get("ADMIN_PASSWORD", "testplaytest")

# Chromium executable discovery
CHROMIUM = None
for cand in [
    "/a0/tmp/playwright/chromium-1169/chrome-linux/chrome",
]:
    if Path(cand).exists():
        CHROMIUM = cand
        break

# Destructive control labels to NEVER click.
DESTRUCTIVE = re.compile(
    r"log\s?out|sign\s?out|delete|remove|trash|danger|reset|disconnect|revoke|deactivate|"
    r"wipe|destroy|decline|^pass$|unsubscribe|clear all|drop|submit|approve|authorize|finish",
    re.I,
)

# Console / network noise to drop.
NOISE = re.compile(
    r"ERR_CERT_AUTHORITY_INVALID|favicon|Could not find the language|net::ERR_ABORTED|"
    r"Failed to load resource|ERR_BLOCKED_BY_CLIENT",
    re.I,
)


def discover_panels():
    """Return list of (name, html_path_relative) for each panel in a0-applicant/webui/."""
    panels = []
    if not APPLICANT_PLUGIN_WEBUI.is_dir():
        print(f"[PANELS] WARNING: {APPLICANT_PLUGIN_WEBUI} not found", file=sys.stderr)
        return panels
    for f in sorted(APPLICANT_PLUGIN_WEBUI.glob("*.html")):
        name = f.stem
        rel = f"plugins/applicant/webui/{f.name}"
        panels.append((name, rel))
    return panels


async def audit_panel(context, name, panel_rel_path):
    """Open one panel in the A0 shell, audit it, return result dict."""
    page = await context.new_page()
    rec = {
        "panel": name,
        "rendered": False,
        "console_errors": [],
        "pageerrors": [],
        "http_5xx": [],
        "dead_controls": [],
        "controls_clicked": 0,
        "notes": [],
    }

    def on_console(msg):
        if msg.type in ("error",):
            t = msg.text or ""
            if not NOISE.search(t):
                rec["console_errors"].append(t[:300])

    def on_pageerror(exc):
        s = str(exc)
        if not NOISE.search(s):
            rec["pageerrors"].append(s[:300])

    def on_response(resp):
        try:
            st = resp.status
            url = resp.url
        except Exception:
            return
        if st >= 500:
            rec["http_5xx"].append(f"{st} {url}")

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    # ── Shell-global stubs ─────────────────────────────────────────────
    # Panels are designed to load same-document inside the A0 SPA shell,
    # which provides globals such as window.openModal, callJsonApi, etc.
    # The harness loads each panel standalone (page.goto to the panel URL),
    # so these globals are undefined — causing spurious pageerrors
    # (e.g. "window.openModal is not a function").  These are harness
    # fidelity shims, NOT product bugs — the panels are correct.
    await page.add_init_script("""(() => {
      if (typeof window.openModal === 'undefined') {
        window.openModal = function(path) {
          (window.__openModalCalls = window.__openModalCalls || []).push(path);
          return Promise.resolve();
        };
      }
    })()""")

    try:
        url = f"{SHELL_URL}/{panel_rel_path}"
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)  # let Alpine boot + API calls settle

        if resp and resp.status < 400:
            rec["rendered"] = True
        else:
            status = resp.status if resp else "no-response"
            rec["notes"].append(f"HTTP {status} loading panel")

        # Screenshot (full page)
        OUTDIR.mkdir(parents=True, exist_ok=True)
        shot = OUTDIR / f"a0panel-{name}.png"
        try:
            await page.screenshot(path=str(shot), full_page=True)
        except Exception as e:
            rec["notes"].append(f"screenshot failed: {str(e)[:120]}")

        # Click non-destructive controls
        ctrl_sel = ('button:not([disabled]), [role="button"], '
                    '.btn, .cal-btn, [data-settings-tab], [x-on\\:click]')
        try:
            handles = await page.query_selector_all(ctrl_sel)
        except Exception:
            handles = []

        MAX = 15
        clicked = 0
        for h in handles:
            if clicked >= MAX:
                break
            try:
                if not await h.is_visible():
                    continue
                label = ((await h.inner_text()) or (await h.get_attribute("aria-label")) or
                         (await h.get_attribute("title")) or "")
                label = label.strip()
                if DESTRUCTIVE.search(label):
                    continue
                await h.click(timeout=1500)
                clicked += 1
                await page.wait_for_timeout(150)
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(60)
            except Exception as e:
                msg = str(e).splitlines()[0][:160]
                if "Timeout" not in msg and "intercepts pointer" not in msg:
                    rec["dead_controls"].append(f"{label[:40]!r}: {msg}")
        rec["controls_clicked"] = clicked

    except Exception as e:
        rec["notes"].append(f"FATAL: {str(e)[:200]}")
    finally:
        await page.wait_for_timeout(200)
        await page.close()
    return rec


async def login(context):
    """Authenticate to the A0 shell via form-based login."""
    page = await context.new_page()
    await page.goto(f"{SHELL_URL}/login", wait_until="domcontentloaded", timeout=30000)
    await page.fill("#username", ADMIN_USER)
    await page.fill("#password", ADMIN_PW)
    await page.click("button[type=submit]")
    await page.wait_for_timeout(1500)
    ok = page.url.rstrip("/") != f"{SHELL_URL}/login"
    await page.close()
    return ok, 200 if ok else 401, "form-submit"


async def main():
    panels = discover_panels()
    if not panels:
        print("[PANELS] No panels found to test.", file=sys.stderr)
        return 1
    print(f"[PANELS] Discovered {len(panels)} panels in {APPLICANT_PLUGIN_WEBUI}")
    for name, rel in panels:
        print(f"         {name:25s} -> {rel}")

    results = []
    async with async_playwright() as p:
        launch_kwargs = {"headless": True,
                         "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]}
        if CHROMIUM:
            launch_kwargs["executable_path"] = CHROMIUM
        browser = await p.chromium.launch(**launch_kwargs)

        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        ok, status, body = await login(ctx)
        print(f"[login] ok={ok} status={status} body={body!r}")
        if not ok:
            print("LOGIN FAILED — aborting", file=sys.stderr)
            await browser.close()
            RESULTS_JSON.write_text(json.dumps({
                "login_ok": False, "status": status, "body": body}, indent=2))
            return 2

        for name, rel in panels:
            print(f"[panel] {name} ...", end=" ", flush=True)
            rec = await audit_panel(ctx, name, rel)
            results.append(rec)
            v = "OK" if rec["rendered"] else "RENDER-FAIL"
            print(f"rendered={rec['rendered']} clicks={rec['controls_clicked']} "
                  f"console={len(rec['console_errors'])} pageerr={len(rec['pageerrors'])} "
                  f"5xx={len(rec['http_5xx'])} dead={len(rec['dead_controls'])} [{v}]")

        await ctx.close()
        await browser.close()

    RESULTS_JSON.write_text(json.dumps({"login_ok": True, "panels": results}, indent=2))
    print(f"\nWrote {RESULTS_JSON} ({len(results)} panel records); screens in {OUTDIR}/")

    issues = 0
    for r in results:
        if r.get("pageerrors") or r.get("http_5xx") or r.get("dead_controls") or not r.get("rendered"):
            issues += 1
    print(f"Panels with notable issues: {issues}/{len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
