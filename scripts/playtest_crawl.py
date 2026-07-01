#!/usr/bin/env python3
"""Automated Playwright UI monkey/crawl of the Applicant front-door (docs/playtest-protocol.md §6a).

Boots nothing itself — assumes the engine (:8000) and front-door (:7000) are already up.
Logs in as admin, enumerates every front-door surface via its JS seam (and the URL-routed
pages), screenshots each, captures console + pageerror events, and politely clicks the
non-destructive controls in each surface to catch handler exceptions / dead controls.

Output:
  - playtest-screens/<surface>.png        full-page screenshots
  - playtest-crawl-results.json           machine-readable per-surface results

Usage: PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python scripts/playtest_crawl.py
"""
import asyncio
import json
import os
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

BASE = os.environ.get("FRONTDOOR_URL", "http://127.0.0.1:7000")
USER = os.environ.get("ADMIN_USER", "admin")
PW = os.environ.get("ADMIN_PASSWORD", "playtest1234")
OUTDIR = Path(os.environ.get("CRAWL_OUT", "playtest-screens"))
OUTDIR.mkdir(parents=True, exist_ok=True)
RESULTS_JSON = Path(os.environ.get("CRAWL_RESULTS", "playtest-crawl-results.json"))

CHROMIUM = None
for cand in [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]:
    if Path(cand).exists():
        CHROMIUM = cand
        break

# Surfaces: (name, opener-JS-or-None, root-selector-to-await-or-None, claimed-purpose)
SURFACES = [
    ("home", None, None, "Landing / workspace shell after login"),
    ("portal", "window.applicantPortalModule && window.applicantPortalModule.openApplicantPortal()",
     "#applicant-portal-modal", "Pending-actions home base: aggregated feed of everything awaiting input"),
    ("chat", "window.applicantChatModule && window.applicantChatModule.openApplicantChat()",
     "#applicant-chat-modal", "Conversational assistant that fills profile/criteria gaps + job actions"),
    ("vault", "window.openApplicantVault && window.openApplicantVault()",
     "#applicant-vault-modal", "Credential vault: per-tenant sign-ins sealed at rest"),
    ("remote", "window.openApplicantRemoteSession && window.openApplicantRemoteSession()",
     "#applicant-remote-modal", "Live remote view / takeover during irreducible human steps"),
    ("mind", "window.applicantMindModule && window.applicantMindModule.openApplicantMind && window.applicantMindModule.openApplicantMind()",
     None, "What the assistant remembers + saved playbooks (profile memory panel)"),
    ("activity", "window.applicantActivityModule && window.applicantActivityModule.openApplicantActivity && window.applicantActivityModule.openApplicantActivity()",
     None, "What the agent is doing now/next/recent"),
    ("debug", "window.applicantDebugModule && window.applicantDebugModule.openApplicantDebug()",
     None, "Activity/debug observability: history, logs, variants, run controls, update"),
    ("compare", "window.applicantCompareModule && window.applicantCompareModule.openApplicantCompare && window.applicantCompareModule.openApplicantCompare()",
     None, "Put two+ applications/postings side-by-side to see where they differ"),
    ("gallery", "window.applicantGalleryModule && window.applicantGalleryModule.openApplicantGallery && window.applicantGalleryModule.openApplicantGallery()",
     None, "Applicant gallery surface"),
    ("results", "window.openApplicantResults && window.openApplicantResults()",
     "#applicant-results-modal", "Non-admin Results: outcome funnel, per-source conversion, learned 'what converts for you' signature"),
    ("onboarding", "window.launchApplicantSetup && window.launchApplicantSetup()",
     "#applicant-onboarding-overlay", "OOBE wizard: Connect a model -> Your profile"),
    ("settings", "CLICK:#user-bar-settings", "#settings-modal", "Settings: AI, sandbox, tools, services, notifications, fonts, account, etc."),
]

# URL-routed vendored pages (open via goto, not a JS seam)
ROUTED_PAGES = ["/memory", "/library", "/calendar", "/notes", "/tasks", "/gallery", "/email"]

# Destructive control labels to NEVER click.
DESTRUCTIVE = re.compile(
    r"log\s?out|sign\s?out|delete|remove|trash|danger|reset|disconnect|revoke|deactivate|"
    r"wipe|destroy|decline|^pass$|unsubscribe|clear all|drop|submit|approve|authorize|finish",
    re.I,
)

# Console / network noise to drop (env + by-design).
NOISE = re.compile(
    r"ERR_CERT_AUTHORITY_INVALID|favicon|Could not find the language|net::ERR_ABORTED|"
    r"Failed to load resource",
    re.I,
)


def classify_4xx(url: str) -> bool:
    """Return True if this 4xx URL is genuinely-wrong (a defect), False if known-benign/gated."""
    benign = re.compile(
        r"/api/research/status/|/api/chat/stream_status/|/api/applicant/email/digest/|"
        r"favicon|/api/applicant/.*/(digest|portal|activity|status)",
        re.I,
    )
    return not benign.search(url)


async def crawl_surface(context, name, opener, root_sel, purpose, viewport_tag="desktop"):
    page = await context.new_page()
    rec = {
        "surface": name, "viewport": viewport_tag, "purpose": purpose,
        "rendered": False, "root_found": None, "controls_clicked": 0,
        "control_errors": [], "console_errors": [], "page_errors": [],
        "http_5xx": [], "http_4xx": [], "open_failed": False, "notes": [],
        "title_text": "", "screenshot": "",
    }

    def on_console(msg):
        if msg.type in ("error",):
            t = msg.text or ""
            if not NOISE.search(t):
                rec["console_errors"].append(t[:300])

    def on_pageerror(exc):
        s = str(exc)
        if not NOISE.search(s):
            rec["page_errors"].append(s[:300])

    def on_response(resp):
        try:
            st = resp.status
            url = resp.url
        except Exception:
            return
        if st >= 500:
            rec["http_5xx"].append(f"{st} {url}")
        elif st >= 400:
            if NOISE.search(url):
                return
            if classify_4xx(url):
                rec["http_4xx"].append(f"{st} {url}")

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)

    try:
        await page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
        # Wait for the app-loader splash to be removed (app.js finished booting),
        # otherwise the z-index:99999 overlay covers every control.
        # Wait for the app-loader splash to detach (app.js booted). Use
        # wait_for_selector(state=detached) — NOT wait_for_function, which uses
        # eval() and is blocked by the strict (no-unsafe-eval) CSP.
        try:
            await page.wait_for_selector("#app-loader", state="detached", timeout=15000)
        except Exception:
            rec["notes"].append("app-loader never detached within 15s (boot slow)")
        await page.wait_for_timeout(1000)
        # Dismiss the auto-opened OOBE wizard / Portal unless we're auditing them.
        # The wizard (.modal.ow-window) auto-opens (setup incomplete) and is
        # aria-modal, so it intercepts clicks on every other surface — by design
        # the wizard takes precedence. To audit the surface BEHIND it we remove the
        # overlay node the same way _dismiss() does (detach from DOM).
        if name not in ("onboarding",):
            await page.evaluate(
                "() => { document.getElementById('ao-finish')?.click(); "
                "document.getElementById('applicant-portal-close')?.click(); "
                "const o=document.querySelector('.modal.ow-window'); if(o&&o.parentNode) o.parentNode.removeChild(o); }"
            )
            await page.wait_for_timeout(300)

        if opener:
            if opener.startswith("CLICK:"):
                sel = opener.split("CLICK:", 1)[1]
                el = await page.query_selector(sel)
                if el:
                    # Resilient opener click: a not-yet-visible/off-screen control
                    # must not hang the default 30s or FATAL the whole surface — try
                    # to scroll it in, then click with a short timeout, then force,
                    # and record a note on failure so the surface still screenshots.
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
                            rec["notes"].append(f"opener click failed: {str(e).splitlines()[0][:120]}")
                else:
                    rec["notes"].append(f"opener selector {sel} not found")
            else:
                try:
                    await page.evaluate(f"() => {{ {opener}; }}")
                except Exception as e:
                    rec["notes"].append(f"opener threw: {str(e)[:160]}")
            await page.wait_for_timeout(1200)

        # Determine the surface root + render.
        if root_sel:
            try:
                await page.wait_for_selector(root_sel, timeout=4000, state="attached")
                root = await page.query_selector(root_sel)
                visible = await root.is_visible() if root else False
                rec["root_found"] = bool(root)
                rec["rendered"] = bool(visible)
                if not visible and root:
                    rec["notes"].append("root present but not visible")
            except Exception:
                rec["root_found"] = False
                rec["open_failed"] = True
                rec["notes"].append(f"root {root_sel} never appeared")
        else:
            rec["rendered"] = True  # no modal root; the surface mutates the page in place
            rec["root_found"] = True

        # Capture a bit of visible text for the claim check.
        try:
            scope = root_sel if (root_sel and rec["root_found"]) else "body"
            txt = await page.evaluate(
                "(sel) => { const el = document.querySelector(sel); "
                "return el ? (el.innerText || '').slice(0, 1200) : ''; }", scope)
            rec["title_text"] = (txt or "").replace("\n", " ⏎ ")[:600]
        except Exception:
            pass

        # Screenshot.
        shot = OUTDIR / f"{name}-{viewport_tag}.png"
        try:
            await page.screenshot(path=str(shot), full_page=True)
            rec["screenshot"] = str(shot)
        except Exception as e:
            rec["notes"].append(f"screenshot failed: {str(e)[:120]}")

        # Click non-destructive controls within the surface scope.
        scope_sel = root_sel if (root_sel and rec["root_found"]) else "body"
        ctrl_sel = ('button:not([disabled]), .cal-btn, .admin-tab, [role="button"], '
                    '[data-settings-tab], [data-settings-panel], .applicant-portal-refresh')
        try:
            handles = await page.query_selector_all(f"{scope_sel} {ctrl_sel}")
        except Exception:
            handles = []
        MAX = 22
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
                # Dismiss popovers.
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(60)
            except Exception as e:
                msg = str(e).splitlines()[0][:160]
                # timeouts on overlapped/animated controls are not handler bugs
                if "Timeout" not in msg and "intercepts pointer" not in msg:
                    rec["control_errors"].append(f"{label[:40]!r}: {msg}")
        rec["controls_clicked"] = clicked

    except Exception as e:
        rec["notes"].append(f"FATAL: {str(e)[:200]}")
        rec["open_failed"] = True
    finally:
        await page.wait_for_timeout(200)
        await page.close()
    return rec


async def crawl_routed(context, path, viewport_tag="desktop"):
    name = "route" + path.replace("/", "_")
    page = await context.new_page()
    rec = {"surface": name, "viewport": viewport_tag, "purpose": f"URL-routed page {path}",
           "rendered": False, "console_errors": [], "page_errors": [], "http_5xx": [],
           "http_4xx": [], "notes": [], "screenshot": "", "controls_clicked": 0, "control_errors": []}

    def on_console(msg):
        if msg.type == "error" and not NOISE.search(msg.text or ""):
            rec["console_errors"].append((msg.text or "")[:300])

    def on_pageerror(exc):
        if not NOISE.search(str(exc)):
            rec["page_errors"].append(str(exc)[:300])

    def on_response(resp):
        try:
            st, url = resp.status, resp.url
        except Exception:
            return
        if st >= 500:
            rec["http_5xx"].append(f"{st} {url}")
        elif st >= 400 and not NOISE.search(url) and classify_4xx(url):
            rec["http_4xx"].append(f"{st} {url}")

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    try:
        resp = await page.goto(BASE + path, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector("#app-loader", state="detached", timeout=15000)
        except Exception:
            rec["notes"].append("app-loader never detached within 15s")
        await page.wait_for_timeout(800)
        rec["http_status"] = resp.status if resp else None
        rec["rendered"] = bool(resp and resp.status < 400)
        shot = OUTDIR / f"{name}-{viewport_tag}.png"
        await page.screenshot(path=str(shot), full_page=True)
        rec["screenshot"] = str(shot)
    except Exception as e:
        rec["notes"].append(f"FATAL: {str(e)[:200]}")
    finally:
        await page.close()
    return rec


async def login(context):
    page = await context.new_page()
    await page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=30000)
    # API login so the session cookie is shared by the whole context.
    resp = await context.request.post(BASE + "/api/auth/login",
                                      data={"username": USER, "password": PW},
                                      headers={"Origin": BASE, "Referer": BASE + "/login"})
    ok = resp.ok
    body = await resp.text()
    await page.close()
    return ok, resp.status, body[:200]


async def main():
    results = []
    async with async_playwright() as p:
        launch_kwargs = {"headless": True, "args": ["--no-sandbox", "--disable-gpu"]}
        if CHROMIUM:
            launch_kwargs["executable_path"] = CHROMIUM
        browser = await p.chromium.launch(**launch_kwargs)

        # Desktop context
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900})
        ok, status, body = await login(ctx)
        print(f"[login] ok={ok} status={status} body={body!r}")
        if not ok:
            print("LOGIN FAILED — aborting", file=sys.stderr)
            await browser.close()
            Path(RESULTS_JSON).write_text(json.dumps(
                {"login_ok": False, "status": status, "body": body}, indent=2))
            return 2

        for (name, opener, root, purpose) in SURFACES:
            print(f"[crawl] desktop {name} ...")
            rec = await crawl_surface(ctx, name, opener, root, purpose, "desktop")
            results.append(rec)
            v = ("RENDER-FAIL" if not rec["rendered"] else "ok")
            print(f"        rendered={rec['rendered']} clicks={rec['controls_clicked']} "
                  f"console={len(rec['console_errors'])} pageerr={len(rec['page_errors'])} "
                  f"5xx={len(rec['http_5xx'])} ctrlerr={len(rec['control_errors'])} [{v}]")

        for path in ROUTED_PAGES:
            print(f"[crawl] routed {path} ...")
            rec = await crawl_routed(ctx, path, "desktop")
            results.append(rec)

        await ctx.close()

        # Mobile pass over the modal surfaces.
        mctx = await browser.new_context(viewport={"width": 375, "height": 812})
        await login(mctx)
        mobile_targets = [s for s in SURFACES if s[0] in ("portal", "chat", "vault", "settings", "onboarding")]
        for (name, opener, root, purpose) in mobile_targets:
            print(f"[crawl] mobile {name} ...")
            rec = await crawl_surface(mctx, name, opener, root, purpose, "mobile")
            results.append(rec)
        await mctx.close()

        await browser.close()

    Path(RESULTS_JSON).write_text(json.dumps({"login_ok": True, "surfaces": results}, indent=2))
    print(f"\nWrote {RESULTS_JSON} ({len(results)} surface records); screens in {OUTDIR}/")

    # Quick triage summary.
    issues = 0
    for r in results:
        bad = (r.get("page_errors") or r.get("http_5xx") or r.get("control_errors")
               or (r.get("root_found") is False) or r.get("open_failed"))
        if bad:
            issues += 1
    print(f"Surfaces with notable issues: {issues}/{len(results)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
