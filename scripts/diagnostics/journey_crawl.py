import asyncio
from playwright.async_api import async_playwright

BASE = "http://applicant-panels:80"
# journey-relevant panels (daily-use + setup surfaces)
PANELS = ["today", "digest", "main", "chat", "documents", "connections", "tiers",
          "channels", "notifications", "health", "mind", "tracker", "screening",
          "vault", "campaigns", "discovery", "criteria", "conversion",
          "model_endpoints", "takeover", "interview_prep", "easy_apply"]
DESTRUCTIVE = ["delete", "remove", "submit", "confirm", "send", "publish", "clear",
               "reset", "disconnect", "pause", "resolve", "approve", "reject",
               "decline", "save", "test", "apply", "logout", "sign out"]


async def crawl(ctx, name):
    pg = await ctx.new_page()
    perr, cerr, ctrlerr = [], [], []
    pg.on("pageerror", lambda e: perr.append(str(e)[:120]))
    pg.on("console", lambda m: cerr.append(m.text[:120]) if m.type == "error" else None)
    try:
        r = await pg.goto(BASE + "/plugins/applicant/webui/" + name + ".html",
                          wait_until="domcontentloaded", timeout=30000)
        await pg.wait_for_timeout(1800)
        status = r.status if r else "?"
        btns = await pg.query_selector_all("button, [role=button], a.btn, .card")
        clicked = 0
        for bt in btns:
            if clicked >= 10:
                break
            try:
                label = ((await bt.inner_text()) or "").strip().lower()
            except Exception:
                label = ""
            if not label or any(d in label for d in DESTRUCTIVE):
                continue
            try:
                await bt.click(timeout=1200)
                clicked += 1
                await pg.wait_for_timeout(250)
            except Exception as e:
                msg = str(e).splitlines()[0][:70]
                if "intercept" not in msg and "not visible" not in msg and "outside of the viewport" not in msg:
                    ctrlerr.append(label[:26] + " -> " + msg)
        # filter out the known shell-global console noise
        cerr_real = [c for c in cerr if "Whisper" not in c and "self-update" not in c
                     and "enumerateDevices" not in c]
        flag = "OK" if (not perr and not ctrlerr) else "*** ISSUE ***"
        print(f"{name:16s} http={status} clicked={clicked} pageerr={len(perr)} "
              f"console={len(cerr_real)} ctrl_err={len(ctrlerr)}  {flag}")
        for e in perr[:2]:
            print("      PAGEERR:", e)
        for e in ctrlerr[:3]:
            print("      CTRLERR:", e)
        for c in cerr_real[:2]:
            print("      CONSOLE:", c)
    except Exception as e:
        print(f"{name:16s} CRAWL-FAIL: {str(e).splitlines()[0][:80]}")
    finally:
        await pg.close()


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True,
                                    args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        ctx = await b.new_context()
        pg = await ctx.new_page()
        await pg.goto(BASE + "/login", wait_until="domcontentloaded", timeout=30000)
        await pg.fill("#username", "paneltest")
        await pg.fill("#password", "paneltestpw123456")
        await pg.click("button[type=submit]")
        await pg.wait_for_timeout(1500)
        print("logged in, crawling journey panels (clicking non-destructive controls):\n")
        await pg.close()
        for name in PANELS:
            await crawl(ctx, name)
        await b.close()


asyncio.run(main())
