import asyncio
from playwright.async_api import async_playwright
BASE="http://applicant-panels:80"
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(headless=True,args=["--no-sandbox","--disable-gpu","--disable-dev-shm-usage"])
        pg=await b.new_page(); perr=[]
        pg.on("pageerror",lambda e:perr.append(str(e)[:120]))
        await pg.goto(BASE+"/login",wait_until="domcontentloaded")
        await pg.fill("#username","paneltest"); await pg.fill("#password","paneltestpw123456")
        await pg.click("button[type=submit]"); await pg.wait_for_timeout(3000)
        launchers=await pg.evaluate("""() => {
          const out=[];
          document.querySelectorAll('*').forEach(e=>{
            const oc=(e.getAttribute && e.getAttribute('onclick'))||'';
            if(oc.includes('plugins/applicant')) out.push({t:(e.textContent||'').trim().slice(0,22), oc:oc.slice(0,64)});
          });
          return out;
        }""")
        print("applicant launchers in shell:", len(launchers))
        for l in launchers[:30]: print("  ", l)
        # what quick-action / sidebar buttons DO exist?
        qa=await pg.evaluate("""() => {
          const out=[];
          document.querySelectorAll('button, a, [role=button]').forEach(e=>{
            const t=(e.textContent||'').trim();
            if(t && t.length<30) out.push(t);
          });
          return [...new Set(out)].slice(0,40);
        }""")
        print("all shell buttons/links:", qa)
        # is the sidebar-quick-actions extension content present at all?
        ext=await pg.evaluate("""() => document.body.innerHTML.includes('plugins/applicant') ? 'YES applicant refs in DOM' : 'NO applicant refs in DOM'""")
        print("applicant refs in DOM:", ext)
        print("pageerrors on shell:", perr[:3])
        await pg.screenshot(path="/a0/tmp/journey-shell.png",full_page=True)
        await b.close()
asyncio.run(main())
