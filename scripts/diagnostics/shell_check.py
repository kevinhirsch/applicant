import asyncio
from playwright.async_api import async_playwright
BASE="http://applicant-panels:80"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-gpu","--disable-dev-shm-usage"])
        pg=await b.new_page()
        await pg.goto(BASE+"/login",wait_until="domcontentloaded"); await pg.fill("#username","paneltest"); await pg.fill("#password","paneltestpw123456"); await pg.click("button[type=submit]"); await pg.wait_for_timeout(2500)
        r=await pg.evaluate("() => ({ openModal: typeof window.openModal, callJsonApi: typeof window.callJsonApi, url: location.href, hasApplicantSidebar: !!document.querySelector('[onclick*=applicant],[class*=applicant]') })")
        print("SHELL RUNTIME:", r)
        await b.close()
asyncio.run(main())
