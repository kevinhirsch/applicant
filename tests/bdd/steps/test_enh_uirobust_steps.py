"""Step bindings for the UI-robustness theme — front-door hardening holes.

Issues #387 (no stale-response/sequence guard on panel re-renders), #390
(save-run-settings double-submit), #392 (digest feedback/survey double-submit),
#396 (mark-submitted double-submit), #398 (render-blocking style.css), #399
(live-session iframe capped at 480px).

These are **front-end file-content facts**: every assertion is made by reading
the shipped ``.js`` / ``.html`` source with ``pathlib`` (``ROOT = parents[3]``)
and matching a safe / risky pattern — no browser, no DOM, no network.

Convention (mirrors ``test_enh_n3_wsjs_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for a
  safe-sibling pattern that already ships on this branch (Run-now / Pause disable
  in flight; Approve / Pass / Research guard re-entry; the Update button disables
  its trigger; the KaTeX sheet uses ``media="print"``; the live frame uses
  viewport-relative ``dvh`` units). They must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for the residual gap
  (no AbortController/token on the panel re-render path; ``#applicant-run-save``
  has no in-flight disable; ``_onFeedback`` / ``_onSurvey`` are unguarded;
  ``_markSubmitted`` leaves its button enabled; ``style.css`` is a synchronous
  render-blocking ``<link>``; the remote iframe is pinned to ``max-height:480px``).
  Each "the gap is fixed" assertion genuinely fails against current source, so
  ``conftest.pytest_bdd_apply_tag`` maps ``@pending`` to a non-strict xfail. No
  ``assert True``.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_387_panel_stale_response_guard.feature",
    "../features/enhancements/enh_390_run_save_inflight_disable.feature",
    "../features/enhancements/enh_392_digest_feedback_survey_guard.feature",
    "../features/enhancements/enh_396_mark_submitted_disable.feature",
    "../features/enhancements/enh_398_stylesheet_render_blocking.feature",
    "../features/enhancements/enh_399_remote_iframe_responsive_height.feature",
)

# Repo root: this file is tests/bdd/steps/<this>.py → parents[3] is the repo root.
ROOT = pathlib.Path(__file__).resolve().parents[3]
JS = ROOT / "workspace" / "static" / "js"
HTML = ROOT / "workspace" / "static" / "index.html"

# The Applicant front-door panel modules that re-render on a selector/tab change.
_PANEL_MODULES = (
    "applicantDebug.js",
    "applicantPortal.js",
    "applicantRemote.js",
    "emailLibrary/applicantDigest.js",
)


def _read(rel: str) -> str:
    return (JS / rel).read_text(encoding="utf-8", errors="ignore")


def _read_html() -> str:
    return HTML.read_text(encoding="utf-8", errors="ignore")


def _extract_handler(src: str, anchor: str) -> str:
    """Return the body of the click handler whose registration contains ``anchor``.

    Walks forward from the anchor and balances braces so we capture the whole
    ``addEventListener('click', async () => { ... })`` / function body, not a
    line. Used to scope an assertion to a single handler.
    """
    start = src.find(anchor)
    assert start != -1, f"anchor not found in source: {anchor!r}"
    brace = src.find("{", start)
    assert brace != -1, f"no opening brace after anchor: {anchor!r}"
    depth = 0
    i = brace
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[brace : i + 1]
        i += 1
    return src[brace:]


def _extract_function(src: str, signature: str) -> str:
    """Return the body of a named ``async function NAME(...)`` declaration."""
    m = re.search(re.escape(signature) + r"[^{]*\{", src)
    assert m is not None, f"function signature not found: {signature!r}"
    brace = m.end() - 1
    depth = 0
    i = brace
    while i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[brace : i + 1]
        i += 1
    return src[brace:]


@pytest.fixture
def uirobustctx() -> dict:
    return {}


# ===========================================================================
# #387 — no stale-response / sequence guard on panel re-renders
# ===========================================================================
@given("the Activity/Debug browser module")
def given_debug(uirobustctx):
    uirobustctx["debug"] = _read("applicantDebug.js")


@when("the Run-now and Pause click handlers are inspected")
def inspect_run_pause(uirobustctx):
    src = uirobustctx["debug"]
    run_body = _extract_handler(src, "runNowBtn.addEventListener('click'")
    pause_body = _extract_handler(src, "pauseBtn.addEventListener('click'")
    uirobustctx["run_now_body"] = run_body
    uirobustctx["pause_body"] = pause_body


@then(
    "each disables its button while the request is in flight and re-enables it "
    "afterwards"
)
def run_pause_disable(uirobustctx):
    # GREEN: both handlers set `<btn>.disabled = true` and re-enable in a finally.
    run_body = uirobustctx["run_now_body"]
    pause_body = uirobustctx["pause_body"]
    assert re.search(r"runNowBtn\.disabled\s*=\s*true", run_body), (
        "Run-now does not disable its button in flight"
    )
    assert re.search(r"runNowBtn\.disabled\s*=\s*false", run_body) and "finally" in run_body, (
        "Run-now does not re-enable its button in a finally block"
    )
    assert re.search(r"pauseBtn\.disabled\s*=\s*true", pause_body), (
        "Pause does not disable its button in flight"
    )
    assert re.search(r"pauseBtn\.disabled\s*=\s*false", pause_body) and "finally" in pause_body, (
        "Pause does not re-enable its button in a finally block"
    )


@given("the Applicant panel browser modules")
def given_panels(uirobustctx):
    uirobustctx["panel_src"] = {rel: _read(rel) for rel in _PANEL_MODULES}


@when("the re-render paths are scanned for a stale-response guard")
def scan_stale_guard(uirobustctx):
    # An AbortController, or an incrementing/compared request token, anywhere in
    # the panel modules. "signal" alone is excluded — these modules use
    # "presence signal" wording that is unrelated to an AbortSignal.
    token_pat = re.compile(
        r"AbortController|\.abort\s*\(|new AbortController|"
        r"_reqSeq|requestToken|_renderToken|_loadToken|_seqToken|reqId\b|"
        r"AbortSignal"
    )
    hits: dict[str, int] = {}
    for rel, src in uirobustctx["panel_src"].items():
        n = len(token_pat.findall(src))
        if n:
            hits[rel] = n
    uirobustctx["stale_guard_hits"] = hits


@then(
    "a request token or AbortController gates the DOM write so a stale response "
    "is discarded"
)
def stale_guard_present(uirobustctx):
    # @pending: none of the applicant panel modules carry an AbortController or a
    # request-sequencing token, so a late response can overwrite the current view.
    hits = uirobustctx["stale_guard_hits"]
    assert hits, (
        "no AbortController / request-token stale-response guard found in any "
        f"applicant panel module ({', '.join(_PANEL_MODULES)})"
    )


# ===========================================================================
# #390 — save-run-settings double-submit
# ===========================================================================
@when("the Save run settings click handler is inspected")
def inspect_save_handler(uirobustctx):
    src = uirobustctx["debug"]
    uirobustctx["save_body"] = _extract_handler(
        src, "querySelector('#applicant-run-save').addEventListener('click'"
    )


@then("it disables the Save button while saving and re-enables it in a finally block")
def save_disable(uirobustctx):
    # @pending: the #applicant-run-save handler awaits the PUT with no
    # `disabled = true` and no finally re-enable, unlike Run-now / Pause.
    body = uirobustctx["save_body"]
    has_disable = "disabled" in body
    has_finally = "finally" in body
    assert has_disable and has_finally, (
        "Save run settings handler does not disable its button in flight and "
        "re-enable it in a finally block"
    )


# ===========================================================================
# #392 — digest feedback / survey double-submit
# ===========================================================================
@given("the Daily-updates digest browser module")
def given_digest(uirobustctx):
    uirobustctx["digest"] = _read("emailLibrary/applicantDigest.js")


@when("the Approve, Pass and Research handlers are inspected")
def inspect_digest_rows(uirobustctx):
    src = uirobustctx["digest"]
    uirobustctx["approve_body"] = _extract_function(src, "async function _onApprove(")
    uirobustctx["pass_body"] = _extract_function(src, "async function _onPass(")
    uirobustctx["research_body"] = _extract_function(src, "async function _onResearch(")


@then("each disables its control before awaiting the request")
def digest_rows_guarded(uirobustctx):
    # GREEN: Approve / Pass call _disableRow(card). Research now guards re-entry with
    # an in-flight `dataset.researching` flag and doubles the button as its own cancel
    # control (a re-click cancels rather than double-submitting), so it deliberately
    # stays enabled instead of disabling — lens 04 #60.
    assert "_disableRow(card)" in uirobustctx["approve_body"], (
        "_onApprove does not disable the row before awaiting"
    )
    assert "_disableRow(card)" in uirobustctx["pass_body"], (
        "_onPass does not disable the row before awaiting"
    )
    research_body = uirobustctx["research_body"]
    assert re.search(r"dataset\.researching\s*=\s*'1'", research_body) and (
        "dataset.researching === '1'" in research_body
    ), (
        "_onResearch does not guard re-entry (in-flight flag + cancel-on-reclick) "
        "before awaiting"
    )


@when("the Send-feedback handler is inspected")
def inspect_feedback(uirobustctx):
    uirobustctx["feedback_body"] = _extract_function(
        uirobustctx["digest"], "async function _onFeedback("
    )


@then("it guards re-entry while the prompt or submit is outstanding")
def feedback_guarded(uirobustctx):
    # @pending: _onFeedback has no disabled / in-flight guard around the prompt
    # + POST, so the toolbar button stays live the whole time.
    body = uirobustctx["feedback_body"]
    assert "disabled" in body, (
        "_onFeedback does not guard re-entry while the prompt/submit is outstanding"
    )


@when("the Quick-survey handler is inspected")
def inspect_survey(uirobustctx):
    uirobustctx["survey_body"] = _extract_function(
        uirobustctx["digest"], "async function _onSurvey("
    )


@then("it guards re-entry while the survey or submit is outstanding")
def survey_guarded(uirobustctx):
    # @pending: _onSurvey has no disabled / in-flight guard around the modal + POST.
    body = uirobustctx["survey_body"]
    assert "disabled" in body, (
        "_onSurvey does not guard re-entry while the survey/submit is outstanding"
    )


# ===========================================================================
# #396 — mark-submitted double-submit
# ===========================================================================
@when("the Update click handler is inspected")
def inspect_update(uirobustctx):
    uirobustctx["update_body"] = _extract_handler(
        uirobustctx["debug"], "updateBtn.addEventListener('click'"
    )


@then("it disables its button before awaiting the request")
def update_disable(uirobustctx):
    # GREEN: the Update button sets updateBtn.disabled = true before the POST.
    assert re.search(r"updateBtn\.disabled\s*=\s*true", uirobustctx["update_body"]), (
        "the Update handler does not disable its button before awaiting"
    )


@when("the mark-submitted handler is inspected")
def inspect_mark_submitted(uirobustctx):
    uirobustctx["marksub_body"] = _extract_function(
        uirobustctx["debug"], "async function _markSubmitted("
    )


@then(
    "it disables the triggering button or guards by application id until the "
    "record is saved"
)
def mark_submitted_guarded(uirobustctx):
    # @pending: _markSubmitted POSTs with the triggering button still enabled and
    # no per-app-id in-flight guard, so the manual submission can be recorded twice.
    body = uirobustctx["marksub_body"]
    has_disable = "disabled" in body
    has_inflight_set = bool(re.search(r"_(?:pending|busy|inflight)\w*", body, re.I))
    assert has_disable or has_inflight_set, (
        "_markSubmitted neither disables the triggering button nor guards re-entry "
        "by application id"
    )


# ===========================================================================
# #398 — render-blocking style.css
# ===========================================================================
@given("the front-door index page")
def given_index(uirobustctx):
    uirobustctx["html"] = _read_html()


@when("the KaTeX stylesheet link is inspected")
def inspect_katex(uirobustctx):
    m = re.search(r"<link[^>]*id=\"katex-css\"[^>]*>", uirobustctx["html"])
    assert m is not None, "KaTeX stylesheet link not found in index.html"
    uirobustctx["katex_link"] = m.group(0)


@then("it is loaded with media print so it does not block first paint")
def katex_non_blocking(uirobustctx):
    # GREEN: the KaTeX sheet ships with media="print" (flipped to all on load).
    assert 'media="print"' in uirobustctx["katex_link"], (
        "the KaTeX stylesheet is not loaded with media=print"
    )


@when("the main stylesheet link is inspected")
def inspect_main_css(uirobustctx):
    html = uirobustctx["html"]
    # Find the <link ...> that points at /static/style.css.
    m = re.search(r"<link[^>]*href=\"/static/style\.css\"[^>]*>", html)
    uirobustctx["main_css_link"] = m.group(0) if m else ""
    # An inlined critical-CSS block would be a <style> tag carrying a critical marker.
    uirobustctx["has_inline_critical"] = bool(
        re.search(r"<style[^>]*>[^<]*?(?:critical|above-the-fold)", html, re.I)
    )


@then(
    "it is deferred, async, split, or its critical CSS is inlined rather than a "
    "synchronous blocking link"
)
def main_css_non_blocking(uirobustctx):
    # @pending: style.css ships as a plain synchronous <link rel="stylesheet"> in
    # <head> with no deferral (no media=print swap, no rel=preload onload, no
    # disabled attr) and no inlined critical CSS.
    link = uirobustctx["main_css_link"]
    deferred = bool(link) and (
        'media="print"' in link
        or "preload" in link
        or "disabled" in link
        or "onload" in link
    )
    assert deferred or uirobustctx["has_inline_critical"], (
        "the main stylesheet is loaded as a synchronous render-blocking <link> "
        "with no critical-CSS inline / async deferral"
    )


# ===========================================================================
# #399 — live-session iframe capped at 480px
# ===========================================================================
@given("the live-session takeover browser module")
def given_remote(uirobustctx):
    uirobustctx["remote"] = _read("applicantRemote.js")


@when("the embedded session frame styling is inspected")
def inspect_remote_frame(uirobustctx):
    src = uirobustctx["remote"]
    uirobustctx["frame_has_dvh"] = bool(re.search(r"height:\s*\d+dvh", src))
    uirobustctx["frame_has_480_cap"] = bool(re.search(r"max-height:\s*480px", src))


@then("the frame height is expressed in viewport-relative units")
def remote_frame_viewport_relative(uirobustctx):
    # GREEN: the frame + wrapper use a dvh-based (viewport-relative) height.
    assert uirobustctx["frame_has_dvh"], (
        "the live-session frame height is not expressed in viewport-relative units"
    )


@then("the frame is not pinned to a fixed 480px maximum height")
def remote_frame_no_fixed_cap(uirobustctx):
    # @pending: both the wrapper and the iframe still set max-height:480px, which
    # letterboxes the live session on small/handheld viewports.
    assert not uirobustctx["frame_has_480_cap"], (
        "the live-session frame is still pinned to a fixed max-height:480px cap"
    )
