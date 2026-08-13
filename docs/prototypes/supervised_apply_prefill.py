"""Supervised-apply prefill runner (E1-S3, productionized from the POC).

Data-driven: adding a role = adding a BANK entry, no code changes. Launches an
anti-detect browser (Camoufox) HEADFUL on the webtop desktop's X display so the
user can watch, opens the role's apply URL, routes each stored answer to the
right field by its question label, selects the right radio options, fills the
candidate's stored contact info, then STOPS. It never clicks submit and never
solves/skips a CAPTCHA — both are human-only boundaries (FR-PREFILL).

Usage (inside the webtop container):  python supervised_apply_prefill.py <role_key>

The essay answers live in the BANK per role (question-keyword -> answer); the
contact fields come from CANDIDATE (in production these are read from the engine's
stored attributes for the campaign, not hardcoded).
"""
import os
import sys
from camoufox.sync_api import Camoufox

CANDIDATE = {
    "input[name='name']": "Kevin Hirsch",
    "input[name='email']": "kevin@kevinhirsch.com",
    "input[name='phone']": "(314) 669-5386",
    "input[name='org']": "TEKsystems (Wells Fargo)",
}

# Per-role prefill banks. text: (question-keyword-in-label -> answer);
# radios: (question-keyword, desired-option-keyword); clicks: exact option text
# for lever custom radios whose label is unique.
BANKS = {
    "compassx-transformation": {
        "url": "https://jobs.lever.co/compassx/c99a4d42-7d0c-45a2-a7f4-0362f86534d3/apply",
        "text": [
            ("airport", "St. Louis Lambert International (STL)"),
            ("excited", "Yes. My best coaching work happens embedded with the team — on-site "
                        "is where resistance surfaces and where new ways of working stick."),
            ("previously been in a high travel", "My background is consulting and enterprise "
                "delivery; I've regularly worked on-site with client teams and that's where "
                "I've had the biggest impact."),
            ("taking direction", "Very comfortable — a proven playbook is an advantage; my job "
                "is to make it land, not relitigate it, and feed back honest signal."),
            ("adapt to a new tool", "At Auto Club I helped an ops team adopt endpoint "
                "automation over manual processes — started with one skeptic's worst task, "
                "automated it with them, and let peer credibility carry the change."),
            ("available to start", "Within two weeks of an offer"),
            ("compensation", "$150,000 base with benefits, or ~$75/hr if structured 1099"),
            ("rate are you targeting", "$150,000 base with benefits, or ~$75/hr if structured 1099"),
        ],
        "radios": [
            ("sponsorship for employment visa", "no (e.g."),
            ("completed a bachelor", "no"),
            ("independent contractor", "yes"),
            ("time spent traveling", "50%"),
        ],
        "clicks": ["No (e.g. I'm a US Citizen", "50% (e.g. twice a month)"],
    },
    # add LTS / CGS / others here as {url, text, radios, clicks}
}

SEL = ("textarea, input:not([type=hidden]):not([type=file]):not([type=radio])"
       ":not([type=checkbox]):not([type=submit]):not([type=button])")
_LABELS_JS = ("els => els.map(el => { let q='', a=el; for(let k=0;k<6&&a;k++){ a=a.parentElement;"
              " if(a){const t=(a.innerText||'').trim(); if(t.length>8){q=t;break;}}}"
              " return q.replace(/\\s+/g,' ').toLowerCase().slice(0,320); })")
_RADIO_JS = ("els => els.map(el => { let opt=''; if(el.id){const l=document.querySelector"
             "('label[for=\"'+el.id+'\"]'); if(l)opt=l.innerText;} if(!opt&&el.parentElement)"
             "opt=el.parentElement.innerText||''; let q='',a=el; for(let k=0;k<7&&a;k++){"
             "a=a.parentElement; if(a){const t=(a.innerText||'').trim(); if(t.length>25){q=t;break;}}}"
             " return {opt:(opt||'').replace(/\\s+/g,' ').trim().toLowerCase(),"
             " q:(q||'').replace(/\\s+/g,' ').toLowerCase().slice(0,320)}; })")


def prefill(page, bank):
    page.goto(bank["url"], wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    done = {"text": 0, "personal": 0, "radios": 0}

    labels = page.eval_on_selector_all(SEL, _LABELS_JS)
    for idx, q in enumerate(labels):
        for kw, ans in bank.get("text", []):
            if kw in q:
                try: page.locator(SEL).nth(idx).fill(ans); done["text"] += 1
                except Exception: pass
                break
    for sel, val in CANDIDATE.items():
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(): loc.fill(val); done["personal"] += 1
        except Exception: pass
    radios = page.eval_on_selector_all("input[type=radio]", _RADIO_JS)
    for qkw, optkw in bank.get("radios", []):
        for idx, r in enumerate(radios):
            if qkw in r["q"] and optkw in r["opt"]:
                try: page.locator("input[type=radio]").nth(idx).check(force=True); done["radios"] += 1
                except Exception: pass
                break
    for txt in bank.get("clicks", []):
        try: page.get_by_text(txt, exact=False).first.click(timeout=3000); done["radios"] += 1
        except Exception: pass
    return done


def main(role_key):
    bank = BANKS.get(role_key)
    if not bank:
        sys.exit(f"unknown role '{role_key}'. known: {', '.join(BANKS)}")
    os.environ["DISPLAY"] = ":1"  # the webtop's X display (KasmVNC session)
    with Camoufox(headless=False, geoip=True, os="linux") as browser:
        page = browser.new_page()
        done = prefill(page, bank)
        page.wait_for_timeout(1500)
        page.screenshot(path="/tmp/prefill_out.png", full_page=True)
        print(f"[{role_key}] filled {done}; SUBMIT NOT CLICKED; CAPTCHA never solved.")
        page.wait_for_timeout(3000)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "compassx-transformation")
