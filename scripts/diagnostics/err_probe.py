import sys, asyncio
from playwright.async_api import async_playwright
BASE = sys.argv[1]; USER = sys.argv[2]; PW = sys.argv[3]
PANELS = sys.argv[4].split(",")


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        ctx = await b.new_context(ignore_https_errors=True)
        pg = await ctx.new_page()
        # login
        await pg.goto(BASE + "/login", wait_until="domcontentloaded")
        try:
            await pg.fill('input[name="username"]', USER)
            await pg.fill('input[name="password"]', PW)
            await pg.click('button[type=submit], input[type=submit]')
            await pg.wait_for_load_state("networkidle")
        except Exception as e:
            print("login note:", str(e)[:60])
        for panel in PANELS:
            errs = []
            pg.on("pageerror", lambda exc: errs.append(exc))
            url = f"{BASE}/plugins/applicant/webui/{panel}.html"
            await pg.goto(url, wait_until="domcontentloaded")
            await pg.wait_for_timeout(2500)
            print(f"\n===== {panel} ({len(errs)} pageerrors) =====")
            for exc in errs[:3]:
                st = getattr(exc, "stack", None) or str(exc)
                print(st[:600])
            pg.remove_listener("pageerror", lambda exc: None)
        await b.close()

asyncio.run(main())
