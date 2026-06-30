"""Step bindings for the front-door reachability / a11y / i18n specs (theme T08).

Issues #176, #182, #194, #199, #200, #201, #247, #248, #249, #250, #260, #271, #274.

Convention (mirrors ``test_enh_research_steps.py`` / ``test_enh_t06_notifications_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for behaviour that
  already ships on this branch — they assert against the engine's dormant-surface
  registry, the workspace ``applicant_features`` section map, or the actual static
  front-door files, and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for behaviour that is
  designed/described-but-not-built. Their steps make an honest probe at the real gap — a
  registry key no section references, a control kind that does not exist, an absent DOM
  element/attribute, a doc claim that contradicts the code — so the scenario is a genuine
  red, never ``assert True``. ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a
  non-strict xfail.

Reachability is asserted against the workspace ``applicant_features`` section map and the
engine ``dormant.py`` registry (the two-layer gating contract). Pure static-HTML/CSS/JS
facts that cannot be asserted without a DOM (missing element id, button ``type``, i18n,
loader timer) are asserted by reading the static file content. No browser is launched and
no real socket is opened.
"""

from __future__ import annotations

import importlib
import pathlib
import re
import sys

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_176_multi_campaign_switcher_dormant.feature",
    "../features/enhancements/enh_182_chat_steering_incomplete.feature",
    "../features/enhancements/enh_194_us_english_hardcoded.feature",
    "../features/enhancements/enh_199_live_dormant_surface_gating.feature",
    "../features/enhancements/enh_200_delivery_status_skip_undercount.feature",
    "../features/enhancements/enh_201_readme_surface_count.feature",
    "../features/enhancements/enh_247_placeholder_as_label.feature",
    "../features/enhancements/enh_248_loader_timeout_blank_page.feature",
    "../features/enhancements/enh_249_buttons_missing_type.feature",
    "../features/enhancements/enh_250_zero_i18n_infra.feature",
    "../features/enhancements/enh_260_missing_tool_email_btn.feature",
    "../features/enhancements/enh_271_oobe_step_count.feature",
    "../features/enhancements/enh_274_settings_host_divs.feature",
)

# Repo root: tests/bdd/steps/<this file> -> parents[3] is the repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"
README = REPO_ROOT / "README.md"
DELIVERY_STATUS = REPO_ROOT / "docs" / "delivery-status.md"
ONBOARDING_JS = REPO_ROOT / "workspace" / "static" / "js" / "applicantOnboarding.js"
INTEGRATION_DIR = REPO_ROOT / "tests" / "integration"


@pytest.fixture
def t08ctx() -> dict:
    return {}


def _load_features():
    """Import the workspace ``applicant_features`` module (speculative, runtime).

    Putting ``workspace`` on ``sys.path`` and importing ``src.applicant_features``
    here keeps the module-level import surface limited to symbols that always exist.
    """
    ws = str(REPO_ROOT / "workspace")
    if ws not in sys.path:
        sys.path.insert(0, ws)
    return importlib.import_module("src.applicant_features")


def _dormant_by_key() -> dict:
    from applicant.dormant import DORMANT_SURFACES

    return {s.key: s for s in DORMANT_SURFACES}


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ===========================================================================
# #176 — multi-campaign switcher dormant + missing front-door section
# ===========================================================================
@given("the engine dormant-surface registry")
def given_registry(t08ctx):
    t08ctx["dormant"] = _dormant_by_key()


@when("the multi-campaign switcher entry is read")
def read_switcher(t08ctx):
    t08ctx["switcher"] = t08ctx["dormant"].get("multi_campaign_switcher")


@then("it reports a dormant status so no live switcher is implied")
def switcher_dormant(t08ctx):
    from applicant.dormant import STATUS_DORMANT

    entry = t08ctx["switcher"]
    assert entry is not None, "multi_campaign_switcher must be registered"
    assert entry.status == STATUS_DORMANT


@given("the workspace Applicant section map")
def given_section_map(t08ctx):
    feats = _load_features()
    t08ctx["sections"] = feats.APPLICANT_SECTIONS
    keys = set()
    for s in feats.APPLICANT_SECTIONS:
        keys.update(s.get("dormant_keys", []))
    t08ctx["referenced_dormant_keys"] = keys


@when("the sections are inspected for a multi-campaign switcher")
def inspect_switcher_section(t08ctx):
    t08ctx["switcher_referenced"] = "multi_campaign_switcher" in t08ctx["referenced_dormant_keys"]


@then("a section grays itself off the multi-campaign switcher surface key")
def switcher_section_present(t08ctx):
    # Today no APPLICANT_SECTIONS entry references the switcher key — genuine red.
    assert t08ctx["switcher_referenced"], (
        "no front-door section gates off multi_campaign_switcher yet"
    )


# ===========================================================================
# #182 — chat steering (pause/resume/throughput/criteria GREEN; approve-all gap)
# ===========================================================================
@given("the chat loop-control intent parser")
def given_chat_parser(t08ctx):
    mod = importlib.import_module("applicant.application.services.chat_service")
    t08ctx["chat_mod"] = mod


@when("a pause directive and a resume directive are parsed")
def parse_pause_resume(t08ctx):
    mod = t08ctx["chat_mod"]
    pause_re = mod._PAUSE
    resume_re = mod._RESUME
    t08ctx["pause_match"] = bool(pause_re.search("please pause applying"))
    t08ctx["resume_match"] = bool(resume_re.search("resume applying now"))


@then("both are recognized as steering directives the chat can route")
def pause_resume_recognized(t08ctx):
    assert t08ctx["pause_match"] is True
    assert t08ctx["resume_match"] is True


@given("the chat control-action contract")
def given_control_contract(t08ctx):
    mod = importlib.import_module("applicant.application.services.chat_service")
    t08ctx["chat_mod"] = mod
    # The docstring of the ControlAction kind field enumerates the supported kinds.
    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    t08ctx["chat_src"] = src


@when("the supported control kinds are listed")
def list_control_kinds(t08ctx):
    src = t08ctx["chat_src"]
    # The literal kinds applied by the run-control routing.
    t08ctx["kinds_present"] = {
        k for k in ("pause", "resume", "throughput", "criteria") if f'"{k}"' in src
    }


@then("pause, resume, throughput and criteria refocus are all steerable")
def kinds_steerable(t08ctx):
    assert {"pause", "resume", "throughput", "criteria"} <= t08ctx["kinds_present"]


@when("the user asks to approve all of today's digest items through chat")
def ask_approve_all(t08ctx):
    src = t08ctx["chat_src"]
    # Probe for an approve-all digest control kind / intent in the chat service.
    t08ctx["approve_all_supported"] = bool(
        re.search(r"approve[_ -]?all", src, re.IGNORECASE)
    )


@then("an approve-all digest control kind is routed to the digest service")
def approve_all_routed(t08ctx):
    # No approve-all digest steering exists yet — genuine red.
    assert t08ctx["approve_all_supported"], (
        "chat cannot route an approve-all digest directive yet"
    )


# ===========================================================================
# #194 — US/English hardcoded parsing (US phone GREEN; intl + i18n gaps)
# ===========================================================================
@given("the phone-normalization core rule")
def given_phone_rule(t08ctx):
    from applicant.core.rules.field_normalization import normalize_phone

    t08ctx["normalize_phone"] = normalize_phone


@when("a US number written with its +1 country code is normalized")
def normalize_us(t08ctx):
    t08ctx["us_result"] = t08ctx["normalize_phone"]("+1 (314) 669-5386")


@then("it reduces to the bare ten-digit national number")
def us_ten_digits(t08ctx):
    assert t08ctx["us_result"] == "3146695386"


@when("a UK number written with its +44 country code is normalized")
def normalize_uk(t08ctx):
    # A user states "+44 7700 900123"; their stored value is the same UK number.
    t08ctx["uk_norm_stated"] = t08ctx["normalize_phone"]("+44 7700 900123")
    t08ctx["uk_norm_national"] = t08ctx["normalize_phone"]("07700 900123")


@then("the country code is preserved rather than mangled")
def uk_preserved(t08ctx):
    # Today the "+" is stripped and the country code is not handled, so the stated
    # international form and the national form do NOT reconcile — genuine red until a
    # country-aware normalization lands.
    assert t08ctx["uk_norm_stated"] == t08ctx["uk_norm_national"], (
        "UK +44 number is mangled: stated and national forms do not reconcile"
    )


@given("the engine parsing layer")
def given_parsing_layer(t08ctx):
    t08ctx["root"] = REPO_ROOT


@when("a localization framework is looked up")
def lookup_i18n_framework(t08ctx):
    candidates = ("gettext", "babel", "i18n")
    found = False
    for name in candidates:
        try:
            # A first-party translation module would live under the applicant package.
            importlib.import_module(f"applicant.i18n.{name}")
            found = True
            break
        except ModuleNotFoundError:
            continue
    if not found:
        # Fall back to any first-party i18n package at all.
        try:
            importlib.import_module("applicant.i18n")
            found = True
        except ModuleNotFoundError:
            found = False
    t08ctx["i18n_found"] = found


@then("a translation backend is available so parsing is not English-only")
def i18n_backend_available(t08ctx):
    # No translation framework exists anywhere — genuine red.
    assert t08ctx["i18n_found"], "no engine-side localization framework exists yet"


# ===========================================================================
# #199 — live dormant surfaces lack front-door gating
# ===========================================================================
_LIVE_OPERATOR_SURFACES = ("debug_surface", "tool_toggle_registry", "update_button", "remote_takeover")


@when("the debug, tool-toggle, update and remote-takeover surfaces are read")
def read_live_surfaces(t08ctx):
    t08ctx["live_statuses"] = {
        k: (t08ctx["dormant"].get(k).status if t08ctx["dormant"].get(k) else None)
        for k in _LIVE_OPERATOR_SURFACES
    }


@then("each one reports a live status")
def live_status_each(t08ctx):
    from applicant.dormant import STATUS_LIVE

    for k, status in t08ctx["live_statuses"].items():
        assert status == STATUS_LIVE, f"{k} should be live, got {status!r}"


@when("the debug surface key is looked up in the section gating")
def lookup_debug_key(t08ctx):
    t08ctx["debug_referenced"] = "debug_surface" in t08ctx["referenced_dormant_keys"]


@then("a section depends on the debug surface registry key")
def debug_section_depends(t08ctx):
    # The debug section ships with dormant_keys: [] — it never checks the registry.
    assert t08ctx["debug_referenced"], (
        "no front-door section gates off the debug_surface registry key"
    )


@when("the tool-toggle, update and remote-takeover keys are looked up in the section gating")
def lookup_operator_keys(t08ctx):
    t08ctx["unreferenced"] = [
        k
        for k in ("tool_toggle_registry", "update_button", "remote_takeover")
        if k not in t08ctx["referenced_dormant_keys"]
    ]


@then("every live surface key is referenced by a front-door section")
def operator_keys_referenced(t08ctx):
    assert not t08ctx["unreferenced"], (
        f"live surfaces with no front-door gating: {t08ctx['unreferenced']}"
    )


# ===========================================================================
# #200 — delivery-status undercounts integration-gated skips
# ===========================================================================
@given("the integration test suite skip markers")
def given_integration_skips(t08ctx):
    count = 0
    for path in sorted(INTEGRATION_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        count += len(re.findall(r"@pytest\.mark\.skipif", text))
        count += len(re.findall(r"pytest\.skip\(", text))
    t08ctx["real_skip_count"] = count


@when("the documented integration-gated skip count is compared to the real count")
def compare_skip_counts(t08ctx):
    text = _read(DELIVERY_STATUS)
    m = re.search(r"(\d+)\s+integration-gated skips", text)
    t08ctx["documented_count"] = int(m.group(1)) if m else None


@then("the documented count is not below the real number of default skips")
def documented_count_accurate(t08ctx):
    documented = t08ctx["documented_count"]
    real = t08ctx["real_skip_count"]
    assert documented is not None, "could not find a documented skip count"
    # Today the doc says 14 while the suite has more skip markers — genuine red.
    assert documented >= real, (
        f"doc claims {documented} integration-gated skips but the suite has {real}"
    )


# ===========================================================================
# #201 — README surface count vs APPLICANT_SECTIONS wiring
# ===========================================================================
@when("the section entries are counted")
def count_sections(t08ctx):
    t08ctx["section_count"] = len(t08ctx["sections"])


@then("exactly eight sections are wired into the gating map")
def eight_sections(t08ctx):
    # 13 = the original 9 (documents, memory, chat, mind, email, debug,
    # desktop_assist, multi_campaign_switcher, compare) plus the three README
    # front-door surfaces given real section defs in #201: update (#rail-update),
    # takeover (#settings-open-remote) and vault (#settings-open-vault), plus the
    # gallery surface added in #296 (#tool-applicant-gallery-btn / #rail-applicant-gallery).
    # Each has a real greyable nav handler, so the gating map covers every such surface.
    assert t08ctx["section_count"] == 13


@given("the README front-door surface list and the section map")
def given_readme_and_sections(t08ctx):
    feats = _load_features()
    t08ctx["sections"] = feats.APPLICANT_SECTIONS
    readme = _read(README)
    seg = readme.split("Every surface below", 1)[1].split("Engine-side adjacencies", 1)[0]
    t08ctx["readme_surface_count"] = len(re.findall(r"^- \*\*", seg, re.M))


@when("the listed surfaces are matched to gated sections")
def match_readme_surfaces(t08ctx):
    t08ctx["readme_vs_sections"] = (
        t08ctx["readme_surface_count"],
        len(t08ctx["sections"]),
    )


@then("no listed surface is reachable outside the proxy-JS-nav section pipeline")
def all_surfaces_gated(t08ctx):
    readme_count, section_count = t08ctx["readme_vs_sections"]
    # README claims 9 reachable surfaces but only 8 sections exist, and several README
    # surfaces (portal, OOBE, takeover, vault) are not gated through the section map at
    # all — genuine red until the README/wiring are reconciled.
    assert readme_count <= section_count, (
        f"README lists {readme_count} reachable surfaces but only {section_count} "
        "are gated through the section pipeline"
    )


# ===========================================================================
# #247 — placeholder-as-label a11y
# ===========================================================================
@given("the front-door page markup")
def given_index_html(t08ctx):
    t08ctx["html"] = _read(INDEX_HTML)


@when("the form controls are counted")
def count_controls(t08ctx):
    html = t08ctx["html"]
    t08ctx["control_count"] = len(re.findall(r"<(?:input|select|textarea)\b", html))


@then("the page contains many input, select and textarea controls")
def many_controls(t08ctx):
    assert t08ctx["control_count"] >= 100


@when("the explicitly associated labels are counted against the controls")
def count_labels(t08ctx):
    html = t08ctx["html"]
    t08ctx["label_for_count"] = len(re.findall(r"<label[^>]*\bfor=", html))
    t08ctx["control_count"] = len(re.findall(r"<(?:input|select|textarea)\b", html))


@then("most controls carry a label rather than relying on placeholder text")
def most_controls_labelled(t08ctx):
    labels = t08ctx["label_for_count"]
    controls = t08ctx["control_count"]
    # Today there are only a handful of label-for associations for 100+ controls.
    assert labels >= controls / 2, (
        f"only {labels} label-for associations for {controls} controls"
    )


# ===========================================================================
# #248 — loader timeout blank page
# ===========================================================================
@when("the loading overlay is looked for")
def look_for_loader(t08ctx):
    t08ctx["loader_present"] = "app-loader" in t08ctx["html"]


@then("a loading overlay element is present")
def loader_present(t08ctx):
    assert t08ctx["loader_present"] is True


@when("the loader-removal logic is inspected")
def inspect_loader_removal(t08ctx):
    html = t08ctx["html"]
    # A fixed-timer teardown: a setTimeout whose body references the app-loader and
    # whose delay is the hard 5000ms. The body spans nested statements/timeouts, so
    # match across them (DOTALL) up to the closing ",5000)".
    t08ctx["fixed_timer"] = bool(
        re.search(r"setTimeout\(.*?app-loader.*?,\s*5000\s*\)", html, re.S)
    )


@then("the loader is not torn down by a fixed five-second timeout alone")
def loader_not_fixed_timer(t08ctx):
    # Today the loader is removed by a hard 5s timer regardless of init state.
    assert not t08ctx["fixed_timer"], (
        "loader is removed by a fixed 5000ms timer, not by init completion"
    )


# ===========================================================================
# #249 — buttons missing type=button
# ===========================================================================
@when("the buttons are counted")
def count_buttons(t08ctx):
    html = t08ctx["html"]
    t08ctx["button_count"] = len(re.findall(r"<button\b", html))


@then("the page contains many button elements")
def many_buttons(t08ctx):
    assert t08ctx["button_count"] >= 100


@when("the buttons without an explicit type are counted")
def count_buttons_no_type(t08ctx):
    html = t08ctx["html"]
    buttons = re.findall(r"<button\b[^>]*>", html)
    t08ctx["buttons_no_type"] = [b for b in buttons if not re.search(r"\btype=", b)]


@then("no button is left to default to a submit type")
def no_typeless_buttons(t08ctx):
    # Today ~140 buttons omit type and default to submit — genuine red.
    assert not t08ctx["buttons_no_type"], (
        f"{len(t08ctx['buttons_no_type'])} buttons omit an explicit type"
    )


# ===========================================================================
# #250 — zero i18n infrastructure
# ===========================================================================
@when("the page is checked for translation-key annotations")
def check_i18n_keys(t08ctx):
    html = t08ctx["html"]
    t08ctx["i18n_attr_count"] = len(re.findall(r"\bdata-i18n\b", html))


@then("user-facing strings are tagged with translation keys rather than hardcoded")
def strings_tagged(t08ctx):
    # No data-i18n annotations exist anywhere — genuine red.
    assert t08ctx["i18n_attr_count"] > 0, "no translation-key annotations in the page"


@given("the workspace static tree")
def given_static_tree(t08ctx):
    t08ctx["static_root"] = REPO_ROOT / "workspace"


@when("the tree is checked for locale or translation resource files")
def check_locale_files(t08ctx):
    root = t08ctx["static_root"]
    locale_files = []
    for pattern in ("**/*.po", "**/*.pot", "**/locale/**/*.json", "**/locales/**/*.json"):
        locale_files.extend(root.glob(pattern))
    t08ctx["locale_files"] = locale_files


@then("at least one locale resource exists so the UI can be localized")
def locale_exists(t08ctx):
    # No locale/translation files exist anywhere — genuine red.
    assert t08ctx["locale_files"], "no locale/translation resource files in the workspace"


# ===========================================================================
# #260 — missing tool-email-btn element
# ===========================================================================
@when("the email section nav ids are read")
def read_email_nav_ids(t08ctx):
    sections = t08ctx["sections"]
    email = next((s for s in sections if s["key"] == "email"), None)
    assert email is not None, "email section must exist"
    t08ctx["email_nav_ids"] = list(email.get("nav_ids", []))


@then("the email toolbar launcher id is among them")
def email_nav_has_btn(t08ctx):
    assert "tool-email-btn" in t08ctx["email_nav_ids"]


@when("the email toolbar launcher element is looked up")
def lookup_email_btn(t08ctx):
    html = t08ctx["html"]
    t08ctx["email_btn_present"] = 'id="tool-email-btn"' in html or "id='tool-email-btn'" in html


@then("the email toolbar launcher element is present so it can be ungreyed")
def email_btn_present(t08ctx):
    # The feature map references tool-email-btn but no such element exists — genuine red.
    assert t08ctx["email_btn_present"], (
        "tool-email-btn referenced by the email section but absent from index.html"
    )


# ===========================================================================
# #271 — OOBE 3-step wizard (GREEN) vs README claim (gap)
# ===========================================================================
@given("the onboarding wizard module")
def given_onboarding_js(t08ctx):
    t08ctx["onboarding_src"] = _read(ONBOARDING_JS)


@when("the wizard steps are counted")
def count_wizard_steps(t08ctx):
    src = t08ctx["onboarding_src"]
    m = re.search(r"const STEPS\s*=\s*\[(.*?)\];", src, re.S)
    assert m is not None, "could not locate the STEPS array"
    block = m.group(1)
    t08ctx["wizard_step_count"] = len(re.findall(r"\bkey:\s*'", block))


@then("the wizard defines exactly three steps")
def three_steps(t08ctx):
    assert t08ctx["wizard_step_count"] == 3


@given("the README first-run setup section")
def given_readme_setup(t08ctx):
    readme = _read(README)
    seg = readme.split("First-run setup wizard", 1)[1].split("The daily digest", 1)[0]
    t08ctx["readme_setup"] = seg


@when("the documented OOBE step count is read")
def read_readme_step_count(t08ctx):
    seg = t08ctx["readme_setup"]
    # Numbered list items "1." "2." ... at line start describe the wizard steps.
    t08ctx["readme_step_count"] = len(re.findall(r"^\d+\.\s+\*\*", seg, re.M))


@then("it matches the three-step wizard rather than claiming more")
def readme_steps_match(t08ctx):
    # README §1 still enumerates four numbered OOBE steps (LLM, channels, fonts,
    # intake) while the wizard ships three — genuine red until the README is updated.
    assert t08ctx["readme_step_count"] == 3, (
        f"README describes {t08ctx['readme_step_count']} OOBE steps but the wizard has 3"
    )


# ===========================================================================
# #274 — settings host divs present and not in comment blocks (GREEN)
# ===========================================================================
_SETTINGS_HOST_DIVS = (
    "ao-settings-notifications",
    "ao-settings-fonts",
    "ao-settings-sandbox",
    "ao-settings-update",
)


@when("the settings tab host divs are looked up")
def lookup_host_divs(t08ctx):
    html = t08ctx["html"]
    t08ctx["host_div_present"] = {
        el: (f'id="{el}"' in html or f"id='{el}'" in html) for el in _SETTINGS_HOST_DIVS
    }


@then("the notifications, fonts, sandbox and update host divs all exist")
def host_divs_exist(t08ctx):
    missing = [el for el, present in t08ctx["host_div_present"].items() if not present]
    assert not missing, f"missing settings host divs: {missing}"


@when("each settings host div is checked against the surrounding comments")
def check_host_divs_comments(t08ctx):
    html = t08ctx["html"]
    inside = {}
    for el in _SETTINGS_HOST_DIVS:
        idx = html.find(f'id="{el}"')
        if idx == -1:
            idx = html.find(f"id='{el}'")
        before = html[:idx]
        last_open = before.rfind("<!--")
        last_close = before.rfind("-->")
        inside[el] = last_open > last_close
    t08ctx["host_div_in_comment"] = inside


@then("none of the host divs sit inside an HTML comment block")
def host_divs_not_commented(t08ctx):
    commented = [el for el, flag in t08ctx["host_div_in_comment"].items() if flag]
    assert not commented, f"settings host divs buried in a comment block: {commented}"
