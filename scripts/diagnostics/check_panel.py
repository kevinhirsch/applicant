import asyncio,sys
from playwright.async_api import async_playwright
PANEL=sys.argv[1]; BASE="http://applicant-panels:80"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-gpu","--disable-dev-shm-usage"])
        pg=await b.new_page(); perr=[]; cerr=[]
        pg.on("pageerror",lambda e:perr.append(str(e)[:140]))
        pg.on("console",lambda m:(cerr.append(m.text[:140]) if m.type=="error" else None))
        await pg.goto(BASE+"/login",wait_until="domcontentloaded",timeout=30000)
        await pg.fill("#username","paneltest"); await pg.fill("#password","paneltestpw123456")
        await pg.click("button[type=submit]"); await pg.wait_for_timeout(1200)
        r=await pg.goto(BASE+"/plugins/applicant/webui/"+PANEL,wait_until="domcontentloaded",timeout=30000)
        await pg.wait_for_timeout(1500)
        txt=await pg.inner_text("body")
        print(f"PANEL {PANEL}: http={r.status} bodylen={len(txt)} pageerrors={len(perr)} console_errors={len(cerr)}")
        if perr: print("  PAGEERR:",perr[:3])
        if cerr: print("  CONSOLE:",cerr[:3])
        await b.close()
asyncio.run(main())
