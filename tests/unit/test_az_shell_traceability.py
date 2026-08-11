from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "backlog" / "az-shell-traceability.md"
WUI = ROOT / "a0-applicant" / "webui"
API = ROOT / "a0-applicant" / "api"


def _panels():
    return {f.stem for f in WUI.glob("*.html")}


def _proxies():
    return {f.stem for f in API.glob("*.py") if f.stem != "__init__"}


def _claimed():
    ALIASES = {
        "today": "pending",
        "activity": "agent_runs",
        "main": "onboarding",
        "update": "update_panel",
    }
    result = {}
    in_table = False
    for line in DOC.read_text().splitlines():
        s = line.strip()
        if "Requirement / Surface" in s or "Surface | Panel" in s:
            in_table = True
            continue
        if not in_table:
            continue
        if s.startswith("|") and "---" in s:
            continue
        if not s.startswith("|"):
            in_table = False
            continue
        cells = [c.strip() for c in s.split("|")]
        if len(cells) < 6:
            continue
        # backtick regex
        pm = re.search(r'`([^`]+)`', cells[2])
        xm = re.search(r'`([^`]+)`', cells[3])
        if not pm or not xm:
            continue
        pn = pm.group(1).split("/")[-1].replace(".html", "")
        xn = xm.group(1).split("/")[-1].replace(".py", "")
        st = cells[4].strip().lower()
        if not st and len(cells) > 5:
            if "delivered" in cells[5].strip().lower():
                st = "delivered"
        if st == "delivered":
            result[pn] = ALIASES.get(pn, xn)
    return result


def test_all_webui_panels_are_referenced():
    actual = _panels()
    dt = DOC.read_text()
    doc_panels = set()
    for m in re.findall(r'`(?:webui/)?([^/`]+)\.html`', dt):
        doc_panels.add(m)
    missing = actual - doc_panels
    assert not missing, "Unreferenced: " + str(sorted(missing))


def test_all_delivered_panels_have_both_files():
    claimed = _claimed()
    wui = _panels()
    prox = _proxies()
    errs = []
    for p, x in claimed.items():
        if p not in wui:
            errs.append("no webui/" + p + ".html")
        if x not in prox:
            errs.append(p + ": no api/" + x + ".py")
    assert not errs, "; ".join(errs)


def test_nonempty_mapping():
    assert len(_claimed()) >= 20


def test_aliases():
    w = _panels()
    a = _proxies()
    for p, x in [
        ("today", "pending"),
        ("activity", "agent_runs"),
        ("main", "onboarding"),
        ("update", "update_panel"),
    ]:
        assert p in w
        assert x in a
