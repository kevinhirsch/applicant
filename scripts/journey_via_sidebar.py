import asyncio, os
from playwright.async_api import async_playwright
BASE = os.environ.get("JBASE", "http://applicant-panels:80")
JUSER = os.environ.get("JUSER", "paneltest")
JPW = os.environ.get("JPW", "paneltestpw123456")
LAUNCHERS = ["Setup", "Today", "Digest", "Chat", "Documents", "Connections", "Vault", "Tiers",
             "Health", "Mind", "Tracker", "Screening", "Campaigns", "Criteria", "Profile",
             "Model Endpoints", "Easy Apply", "Ops", "Research", "Automation", "Save a Job"]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        pg = await b.new_page()
        perr, cerr = [], []
        pg.on("pageerror", lambda e: perr.append(str(e)[:130]))
        pg.on("console", lambda m: cerr.append(m.text[:130]) if m.type == "error" else None)
        await pg.goto(BASE + "/login", wait_until="domcontentloaded")
        await pg.fill("#username", JUSER)
        await pg.fill("#password", JPW)
        await pg.click("button[type=submit]")
        await pg.wait_for_timeout(3000)
        print(f"target={BASE}  logged-in-url={pg.url}\n")
        for label in LAUNCHERS:
            b0, c0 = len(perr), len(cerr)
            try:
                await pg.get_by_text(label, exact=False).first.click(timeout=4000)
                await pg.wait_for_timeout(1600)
                opened = await pg.evaluate("""() => {
                  const modals=[...document.querySelectorAll('iframe, .modal, [class*=modal], dialog')].filter(e=>e.offsetParent!==null);
                  return {modalVisible: modals.length>0};
                }""")
                np = list(perr[b0:])
                nc = [c for c in cerr[c0:] if "Whisper" not in c and "self-update" not in c and "enumerateDevices" not in c]
                flag = "" if not np else "  *** PAGEERR ***"
                print(f"{label:16s} modal={opened['modalVisible']} newpageerr={len(np)} newconsole={len(nc)}{flag}")
                for e in np[:2]:
                    print("      PAGEERR:", e)
                for c in nc[:1]:
                    print("      CONSOLE:", c)
            except Exception as e:
                print(f"{label:16s} CLICK-FAIL: {str(e).splitlines()[0][:70]}")
            try:
                await pg.keyboard.press("Escape")
                await pg.wait_for_timeout(400)
            except Exception:
                pass
        await b.close()

asyncio.run(main())
