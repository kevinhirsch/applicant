#!/usr/bin/env python3
"""A0-shell panel playtest harness — visual render/console/dead-control audit.

Enumerates every a0-applicant/webui/*.html panel, opens each in the running A0 shell
at SHELL_URL (default http://localhost:80), captures console messages/errors, pageerrors,
HTTP failures (4xx/5xx), screenshots, unhandled promise rejections, UI artifact leaks
(undefined, null, NaN, [object Object], JSON blobs), blank-page detection, and politely
clicks non-destructive controls (buttons, toggles, tabs, accordions, select dropdowns)
to catch handler exceptions / dead controls.

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
        "failed_requests": [],
        "unhandled_rejections": [],
        "ui_leaks": [],
        "blank_after_load": False,
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
        if st >= 400:
            rec["failed_requests"].append({"url": url, "status": st})

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
      window.__unhandledRejections = [];
      window.addEventListener('unhandledrejection', function(event) {
        var val = '';
        if (event.reason) {
          if (event.reason.stack) val = event.reason.stack;
          else if (event.reason.message) val = event.reason.message;
          else val = String(event.reason);
        } else {
          val = String(event);
        }
        window.__unhandledRejections.push(val);
      });
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

        # Post-settle captures: unhandled rejections, UI leaks, blank page
        try:
            rec["unhandled_rejections"] = await page.evaluate("window.__unhandledRejections || []")
        except Exception:
            rec["unhandled_rejections"] = []
        try:
            body_text = await page.evaluate("document.body.innerText")
            leaks = []
            ui_leak_patterns = [
                "undefined", "null", "NaN", "[object Object]", "[object Promise]",
                "{{", "x-text",
            ]
            for pat in ui_leak_patterns:
                idx = body_text.find(pat)
                if idx != -1:
                    start = max(0, idx - 40)
                    end = min(len(body_text), idx + len(pat) + 40)
                    snippet = body_text[start:end]
                    leaks.append({"artifact": pat, "snippet": snippet})
            # Also check for JSON error blobs: starts with { and has "error" or "message"
            import re as _re
            for m in _re.finditer(r'\{[^}]{1,300}["\'](?:error|message)["\'][^}]*\}', body_text):
                blob = m.group()
                leaks.append({"artifact": "json-error-blob", "snippet": blob[:80]})
            rec["ui_leaks"] = leaks
        except Exception:
            rec["ui_leaks"] = []
        try:
            trimmed = await page.evaluate("document.body.innerText.trim().length")
            rec["blank_after_load"] = trimmed < 20
        except Exception:
            rec["blank_after_load"] = False

        # Click non-destructive controls
        ctrl_sel = ('button:not([disabled]), [role="button"], '
                    '.btn, .cal-btn, [data-settings-tab], [x-on\\:click], '
                    'select, [role="tab"], [role="button"], '
                    '.expander, [data-expander], .collapse-toggle, '
                    '[data-collapse-toggle], .accordion-trigger, '
                    '[aria-expanded]')
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
                tag = (await h.evaluate("el.tagName.toLowerCase()")) or ""
                label = ((await h.inner_text()) or (await h.get_attribute("aria-label")) or
                         (await h.get_attribute("title")) or "")
                label = label.strip()
                if DESTRUCTIVE.search(label):
                    continue
                if tag == "select":
                    # Open select dropdown then dismiss without submitting
                    await h.click(timeout=1500)
                    clicked += 1
                    await page.wait_for_timeout(150)
                    await page.keyboard.press("Escape")
                else:
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


async def audit_panel_with_error_injection(context, name, panel_rel_path):
    """Check how a panel behaves when callJsonApi ALWAYS returns a failure.

    Overrides callJsonApi to return a 500/error envelope, then loads the
    panel and checks whether it:
    - err_blank: shows nothing (body < 20 chars) under the error condition
    - err_no_message: renders but doesn't display any error indicator
    - err_leak: leaks raw error text or [object Object]/"500" into visible text
    """
    page = await context.new_page()
    rec = {
        "panel": name,
        "err_blank": False,
        "err_no_message": False,       "err_leak": False,
        "console_errors": [],
        "pageerrors": [],
        "unhandled_rejections": [],
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

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)

    await page.add_init_script("""(() => {
      window.callJsonApi = async () => ({ok:false, status:500, error:"harness-injected error"});
      if (typeof window.openModal === 'undefined') {
        window.openModal = function(path) {
          (window.__openModalCalls = window.__openModalCalls || []).push(path);
          return Promise.resolve();
        };
      }
      window.__unhandledRejections = [];
      window.addEventListener('unhandledrejection', function(event) {
        var val = '';
        if (event.reason) {
          if (event.reason.stack) val = event.reason.stack;
          else if (event.reason.message) val = event.reason.message;
          else val = String(event.reason);
        } else {
          val = String(event);
        }
        window.__unhandledRejections.push(val);
      });
    })()""")

    try:
        url = f"{SHELL_URL}/{panel_rel_path}"
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2000)

        if resp and resp.status < 400:
            pass
        else:
            status = resp.status if resp else "no-response"
            rec["notes"].append(f"HTTP {status} loading panel")

        # Screenshot
        OUTDIR.mkdir(parents=True, exist_ok=True)
        shot = OUTDIR / f"a0panel-einj-{name}.png"
        try:
            await page.screenshot(path=str(shot), full_page=True)
        except Exception as e:
            rec["notes"].append(f"screenshot failed: {str(e)[:120]}")

        # Evaluate error-handling signals
        try:
            rec["unhandled_rejections"] = await page.evaluate("window.__unhandledRejections || []")
        except Exception:
            rec["unhandled_rejections"] = []

        try:
            body_text = await page.evaluate("document.body.innerText")
        except Exception:
            body_text = ""

        # err_blank: body text < 20 chars despite error
        try:
            trimmed_len = await page.evaluate("document.body.innerText.trim().length")
            rec["err_blank"] = trimmed_len < 20
        except Exception:
            rec["err_blank"] = True

        # err_no_message: rendered but no error indicator in text or CSS class
        if not rec["err_blank"] and body_text:
            lower = body_text.lower()
            has_error_keyword = any(kw in lower for kw in ["error", "failed", "couldn't", "unable", "try again"])
            has_error_class = False
            try:
                els = await page.evaluate(
                    '''Array.from(document.querySelectorAll('*')).filter(
                       e => e.className && typeof e.className === 'string' &&
                            e.className.toLowerCase().includes('error')
                    ).length'''
                )
                has_error_class = els > 0
            except Exception:
                pass
            rec["err_no_message"] = not has_error_keyword and not has_error_class
        elif not rec["err_blank"]:
            rec["err_no_message"] = True

        # err_leak: leaked raw error text, [object Object], "undefined", "500" in visible text,
        #          OR a pageerror / unhandled rejection fired
        pageerrors = rec["pageerrors"]
        unrej = rec["unhandled_rejections"]
        if body_text:
            leak_patterns = ["harness-injected error", "[object Object]", "undefined", "\"500\"", " 500 "]
            text_leak = any(p in body_text for p in leak_patterns)
        else:
            text_leak = False
        rec["err_leak"] = bool(text_leak or pageerrors or unrej)

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
    error_injection_results = []
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
                  f"5xx={len(rec['http_5xx'])} dead={len(rec['dead_controls'])} "
                  f"failed_req={len(rec['failed_requests'])} unhandled_rej={len(rec['unhandled_rejections'])} "
                  f"ui_leaks={len(rec['ui_leaks'])} blank={rec['blank_after_load']} [{v}]")

        # --- Error-injection pass ---
        for name, rel in panels:
            print(f"[error-inject] {name} ...", end=" ", flush=True)
            rec = await audit_panel_with_error_injection(ctx, name, rel)
            error_injection_results.append(rec)
            print(f"blank={rec['err_blank']} no_msg={rec['err_no_message']} leak={rec['err_leak']} "
                  f"console={len(rec['console_errors'])} pageerr={len(rec['pageerrors'])} "
                  f"unhandled_rej={len(rec['unhandled_rejections'])}")

        await ctx.close()
        await browser.close()

    RESULTS_JSON.write_text(json.dumps({
        "login_ok": True,
        "panels": results,
        "error_injection": error_injection_results,
    }, indent=2))
    print(f"\nWrote {RESULTS_JSON} ({len(results)} panel records, {len(error_injection_results)} error-inject records); screens in {OUTDIR}/")

    # Normal pass summary
    issues = 0
    for r in results:
        if (r.get("pageerrors") or r.get("http_5xx") or r.get("failed_requests") or
            r.get("unhandled_rejections") or r.get("ui_leaks") or r.get("blank_after_load") or
            r.get("dead_controls") or not r.get("rendered")):
            issues += 1
    print(f"Panels with notable issues: {issues}/{len(results)}")

    # Error-injection summary
    blank_panels = [r["panel"] for r in error_injection_results if r["err_blank"]]
    no_msg_panels = [r["panel"] for r in error_injection_results if r["err_no_message"]]
    leak_panels = [r["panel"] for r in error_injection_results if r["err_leak"]]
    print(f"Error-injection results:")
    print(f"  err_blank (empty under error): {len(blank_panels)} panels — {blank_panels}")
    print(f"  err_no_message (no error shown): {len(no_msg_panels)} panels — {no_msg_panels}")
    print(f"  err_leak (leaks/errors fired): {len(leak_panels)} panels — {leak_panels}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
