"""Regression coverage for the profile-gap completeness checklist (dark-engine
audit item 51) in ``static/js/applicantOnboarding.js``.

Follows the established convention for this file (see
``test_applicant_round1_onboarding.py``): ``applicantOnboarding.js`` does
top-level module-scope work and is not a bare dependency-free leaf, so this
reads the actual static file content via regex rather than executing it in a
DOM/browser. Each assertion was verified, by hand, to go red when the checklist
wiring is reverted (see the companion route/client-method revert checks in
``test_applicant_profile_gaps_route.py`` / ``test_applicant_engine_gaps_client.py``
for the backend half of the same chain).
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ONBOARDING_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantOnboarding.js"


def _read() -> str:
    return ONBOARDING_JS.read_text(encoding="utf-8")


def test_profile_gaps_module_state_exists():
    js = _read()
    assert re.search(r"let\s+_profileGaps\s*=\s*null\s*;", js), (
        "expected a _profileGaps module-state variable"
    )


def test_renders_onboarding_fetches_the_gaps_proxy_route():
    """The wizard's 'Your profile' step entry point must fetch the SAME proxy
    route the backend chain exposes (SETUP + '/gaps/{campaignId}') -- not a
    re-derived or hardcoded URL."""
    js = _read()
    m = re.search(r"async function _renderOnboarding\(\)\s*\{([\s\S]*?)\n\}", js)
    assert m, "expected an async function _renderOnboarding() {...}"
    body = m.group(1)
    assert "_profileGaps" in body
    assert re.search(r"\$\{SETUP\}/gaps/\$\{encodeURIComponent\(_campaignId\)\}", body), (
        "expected _renderOnboarding to fetch `${SETUP}/gaps/${encodeURIComponent(_campaignId)}`"
    )
    # A gaps-fetch failure must never block the intake itself (best-effort, like
    # the existing apply-readiness status fetch).
    assert "try" in body and "catch" in body


def test_profile_gaps_html_renders_a_checklist_of_real_missing_items():
    js = _read()
    m = re.search(r"function _profileGapsHTML\(\)\s*\{([\s\S]*?)\n\}", js)
    assert m, "expected a function _profileGapsHTML() {...} renderer"
    body = m.group(1)
    # Degrades cleanly when nothing has been fetched yet / nothing is missing.
    assert re.search(r"if\s*\(\s*!g\s*\|\|\s*g\.complete", body)
    # Renders the real gap strings (never fabricated) via the shared HTML-escaper.
    assert "g.gaps.map" in body
    assert "esc(item)" in body


def test_base_resume_step_shows_the_checklist():
    """The checklist must actually be wired into a rendered step, not just
    defined and unused (dead code would fail 'reachability is the definition of
    done')."""
    js = _read()
    m = re.search(r"function _renderBaseResume\(saved\)\s*\{([\s\S]*?_setBody\(`[\s\S]*?`\);)", js)
    assert m, "expected function _renderBaseResume(saved) {...} with a _setBody(...) call"
    assert "_profileGapsHTML()" in m.group(1)
