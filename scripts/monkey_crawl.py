#!/usr/bin/env python3
"""Applicant monkey-crawl: open every plugin panel and log all errors
(uncaught JS, console errors/warnings, failed requests, HTTP>=400, visible
render-error text), grouped per page.

Design: the orchestrator runs ONE panel per child subprocess with a hard
wall-clock timeout. A panel that freezes the renderer only kills its own child
(recorded as FROZEN); the crawl continues. This is the only freeze-proof way to
guarantee "an entry for every page".

Usage:
  monkey_crawl.py [BASE_URL] [OUT_JSON]        # orchestrator (crawl all)
  monkey_crawl.py --one PANEL BASE_URL         # worker (crawl one, prints JSON)
"""
import sys, os, json, re, subprocess

BASE_DEFAULT = "http://10.0.1.11:8000"
OUT_DEFAULT = "/tmp/claude-1000/-home-kevin-Desktop/50600178-fbd3-43ab-b723-05ca278043a1/scratchpad/crawl_report.json"
PER_PANEL_TIMEOUT = 30  # seconds, hard kill

PANELS = ["activity","attributes","audit","automation","campaigns","channels",
"chat","compare","config","connections","conversion","criteria","debug","demo",
"digest","discovery","documents","dormant","easy_apply","feedback","gallery",
"health","help","interview_prep","main","mind","model_endpoints","notifications",
"ops","privacy","research","savejob","screening","shortcuts","takeover","tiers",
"today","tracker","update","vault"]

RENDER_ERR = re.compile(r"not found|failed to load|error loading|traceback|"
                        r"is not defined|cannot read|undefined is not|500 internal|"
                        r"could not load|failed to fetch|no campaign", re.I)


def crawl_one(base, name):
    """Worker: crawl a single panel, return a result dict."""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    errs = []
    status = "ok"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = ctx.new_page()
        page.set_default_timeout(10000)
        page.on("console", lambda m: errs.append({"type": "console." + m.type, "msg": (m.text or "")[:240]}) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: errs.append({"type": "pageerror", "msg": str(e)[:240]}))
        page.on("requestfailed", lambda r: errs.append({"type": "requestfailed", "msg": (r.url.replace(base, "") + " " + str(r.failure))[:240]}))
        page.on("response", lambda r: errs.append({"type": "http." + str(r.status), "msg": r.url.replace(base, "")[:200]}) if r.status >= 400 else None)
        try:
            page.goto(base + "/", wait_until="domcontentloaded", timeout=15000)
            page.wait_for_function("typeof window.openModal === 'function'", timeout=10000)
            # Wait for Alpine to be fully booted BEFORE opening the panel, else we
            # record false "window.Alpine undefined / X is not defined" cascades
            # that a real user (opening panels post-boot) never sees.
            page.wait_for_function("window.Alpine && window.Alpine.version && typeof window.Alpine.data === 'function'", timeout=10000)
            page.wait_for_timeout(1500)  # settle: let the app's own Alpine roots mount
            errs.clear()  # drop base-app-load noise; keep only panel-specific
            # fire-and-forget: openModal returns a promise that resolves only on
            # close, so DON'T let evaluate await it (evaluate awaits returned
            # promises with no timeout -> would hang forever).
            page.evaluate("(n) => { window.openModal('/plugins/applicant/webui/' + n + '.html'); return true; }", name)
            page.wait_for_timeout(3500)
            txt = page.evaluate("""() => {
                const ms=[...document.querySelectorAll('[class*="modal"]')].filter(x=>x.offsetParent);
                return ms.length ? (ms[ms.length-1].innerText||'') : '';
            }""")
            for line in (txt or "").splitlines():
                line = line.strip()
                if line and RENDER_ERR.search(line) and len(line) < 160:
                    errs.append({"type": "render.text", "msg": line[:160]})
        except PWTimeout as e:
            status = "TIMEOUT"
            errs.append({"type": "crawl.timeout", "msg": str(e).splitlines()[0][:180]})
        except Exception as e:
            status = "ERROR"
            errs.append({"type": "crawl.exception", "msg": (type(e).__name__ + ": " + str(e))[:180]})
        finally:
            try:
                browser.close()
            except Exception:
                pass
    # dedup
    seen, uniq = set(), []
    for e in errs:
        k = (e["type"], e["msg"])
        if k not in seen:
            seen.add(k); uniq.append(e)
    return {"panel": name, "status": status, "errors": uniq}


def main_worker():
    name = sys.argv[2]
    base = sys.argv[3] if len(sys.argv) > 3 else BASE_DEFAULT
    res = crawl_one(base, name)
    sys.stdout.write("@@RESULT@@" + json.dumps(res))
    sys.stdout.flush()


def main_orchestrator():
    base = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else BASE_DEFAULT).rstrip("/")
    out = sys.argv[2] if len(sys.argv) > 2 else OUT_DEFAULT
    report = {"base": base, "panels": {}}
    for name in PANELS:
        try:
            cp = subprocess.run(
                [sys.executable, os.path.abspath(__file__), "--one", name, base],
                capture_output=True, text=True, timeout=PER_PANEL_TIMEOUT)
            out_txt = cp.stdout
            if "@@RESULT@@" in out_txt:
                res = json.loads(out_txt.split("@@RESULT@@", 1)[1])
            else:
                res = {"panel": name, "status": "NO_RESULT",
                       "errors": [{"type": "worker.stderr", "msg": (cp.stderr or out_txt or "")[-180:]}]}
        except subprocess.TimeoutExpired:
            res = {"panel": name, "status": "FROZEN",
                   "errors": [{"type": "renderer.frozen", "msg": "panel hung > %ds — killed" % PER_PANEL_TIMEOUT}]}
        except Exception as e:
            res = {"panel": name, "status": "ORCH_ERROR", "errors": [{"type": "orchestrator", "msg": str(e)[:180]}]}
        report["panels"][name] = res
        flag = "" if not res["errors"] else ("  <-- %d err" % len(res["errors"]))
        print("[%-16s] %-10s%s" % (name, res["status"], flag), flush=True)

    with open(out, "w") as f:
        json.dump(report, f, indent=1)
    bad = {k: v for k, v in report["panels"].items() if v["errors"] or v["status"] not in ("ok",)}
    print("\n===== SUMMARY: %d/%d panels flagged =====" % (len(bad), len(PANELS)))
    for k, v in bad.items():
        print("\n### %s (%s)" % (k, v["status"]))
        for e in v["errors"][:8]:
            print("   - [%s] %s" % (e["type"], e["msg"]))
    print("\nfull report: " + out)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--one":
        main_worker()
    else:
        main_orchestrator()
