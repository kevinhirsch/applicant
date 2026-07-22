import sys, asyncio
from playwright.async_api import async_playwright
BASE = "http://applicant-e2e:80"; USER = "e2etest"; PW = "e2etestpw123456"
PANELS = ["digest.html", "today.html"]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
        pg = await b.new_page()
        await pg.goto(BASE + "/login", wait_until="domcontentloaded", timeout=30000)
        await pg.fill("#username", USER); await pg.fill("#password", PW)
        await pg.click("button[type=submit]"); await pg.wait_for_load_state("networkidle")
        # wait for shell openModal to exist
        for _ in range(20):
            has = await pg.evaluate("typeof window.openModal === 'function'")
            if has: break
            await pg.wait_for_timeout(500)
        print("openModal available:", has)
        for panel in PANELS:
            errs = []
            handler = lambda exc, _e=errs: _e.append(str(exc)[:160])
            pg.on("pageerror", handler)
            await pg.evaluate(f"window.openModal('/plugins/applicant/webui/{panel}')")
            await pg.wait_for_timeout(2500)
            # is the modal visible + does it have rendered content?
            body = await pg.evaluate("document.body.innerText.length")
            print(f"\n== {panel}: pageerrors={len(errs)} bodylen={body} ==")
            for e in errs[:4]:
                print("   ERR:", e)
            pg.remove_listener("pageerror", handler)
            # close modal (Escape) before next
            await pg.keyboard.press("Escape"); await pg.wait_for_timeout(600)
        await b.close()

asyncio.run(main())
