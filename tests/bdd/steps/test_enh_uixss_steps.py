"""Step bindings for the UI-XSS / output-encoding theme (front-door hardening).

Issues #384 (document composer renders received-email HTML verbatim into
innerHTML), #389 (email reader uses a denylist sanitizer, re-parses the
sanitized HTML — mXSS — and leaks read-receipt beacons via inline-style
``url()``), #391 (document title injected raw into the tab bar), #395
(version-history summary/source injected raw), #397 (image EXIF GPS
interpolated raw in the gallery detail panel).

These are **JS-file-content facts**, so every assertion is made by reading the
``.js`` source with ``pathlib`` (``ROOT = parents[3]``) and matching the risky
/ safe pattern with a regex — no browser, no DOM, no network.

Convention (mirrors ``test_enh_n3_wsjs_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for a safe
  sibling that already ships on this branch (the email reader routes received
  bodies through ``_sanitizeHtml``; the lang-picker / suggestion-reason sinks
  escape; the version diff builder escapes each line; the gallery camera /
  source / session fields escape). They must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for the residual
  output-encoding hole: the unsafe sink (verbatim ``innerHTML``, a denylist
  sanitizer, a raw re-parse, an unescaped interpolation) is STILL present, so
  the "it is fixed" assertion genuinely fails → ``conftest.pytest_bdd_apply_tag``
  maps ``@pending`` to a non-strict xfail. When the fix lands, drop the tag and
  the scenario becomes a hard regression gate. No ``assert True``.
"""

from __future__ import annotations

import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_384_email_composer_innerhtml.feature",
    "../features/enhancements/enh_389_email_sanitizer_allowlist.feature",
    "../features/enhancements/enh_391_doc_tab_title_escape.feature",
    "../features/enhancements/enh_395_version_summary_escape.feature",
    "../features/enhancements/enh_397_gallery_gps_escape.feature",
)

# Repo root: this file is tests/bdd/steps/<this>.py → parents[3] is the repo root.
ROOT = pathlib.Path(__file__).resolve().parents[3]
JS = ROOT / "workspace" / "static" / "js"


def _read(rel: str) -> str:
    """Read a workspace JS module relative to ``workspace/static/js``."""
    return (JS / rel).read_text(encoding="utf-8", errors="ignore")


def _slice_function(text: str, header: str) -> str:
    """Return the brace-balanced body of the function whose definition starts
    at ``header`` (a literal substring such as ``"function _emailBodyToHtml(""``).
    Speculative — raises if the header is absent so the probe fails honestly."""
    start = text.index(header)
    brace = text.index("{", start)
    depth = 0
    i = brace
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[brace : i + 1]
        i += 1
    return text[brace:]


@pytest.fixture
def uixssctx() -> dict:
    return {}


# ===========================================================================
# #384 — document composer renders received-email HTML verbatim into innerHTML
# ===========================================================================
@given("the email reader library module")
def given_email_reader(uixssctx):
    uixssctx["reader"] = _read("emailLibrary.js")


@when("the received-body render path is inspected")
def inspect_reader_render(uixssctx):
    src = uixssctx["reader"]
    # The reader renders the remote body via _sanitizeHtml(data.body_html).
    uixssctx["reader_sanitizes"] = bool(
        re.search(r"_sanitizeHtml\(\s*data\.body_html\s*\)", src)
    )


@then("it routes the body through the shared email sanitizer")
def reader_sanitizes(uixssctx):
    # GREEN: the reader path passes the received body through _sanitizeHtml.
    assert uixssctx["reader_sanitizes"], (
        "email reader does not route the received body through _sanitizeHtml"
    )


@given("the document composer module")
def given_composer(uixssctx):
    uixssctx["doc"] = _read("document.js")


@when("the rich-body render path is inspected")
def inspect_composer_render(uixssctx):
    src = uixssctx["doc"]
    # The sink: _rich.innerHTML = _emailBodyToHtml(fields.body);
    uixssctx["composer_sink"] = bool(
        re.search(r"\.innerHTML\s*=\s*_emailBodyToHtml\(", src)
    )
    # The honest probe: does _emailBodyToHtml itself sanitize the body before
    # returning it (instead of returning attacker HTML verbatim)? A fix would
    # call a sanitizer (_sanitizeHtml or a sandboxed iframe) inside that helper.
    body = _slice_function(src, "function _emailBodyToHtml(")
    uixssctx["composer_sanitizes"] = bool(
        re.search(r"_sanitizeHtml\s*\(|sandbox|srcdoc", body)
    )


@then(
    "the email body is sanitized before the innerHTML assignment instead of "
    "being used verbatim"
)
def composer_sanitizes(uixssctx):
    # @pending: _emailBodyToHtml returns sender-controlled HTML verbatim; the
    # innerHTML sink never sanitizes it.
    assert uixssctx["composer_sink"], "expected the _emailBodyToHtml innerHTML sink"
    assert uixssctx["composer_sanitizes"], (
        "_emailBodyToHtml returns received-email HTML verbatim without sanitizing "
        "before the innerHTML assignment"
    )


# ===========================================================================
# #389 — denylist sanitizer + double re-parse (mXSS) + inline url() beacon
# ===========================================================================
@given("the email sanitizer helper")
def given_sanitizer(uixssctx):
    uixssctx["utils"] = _read("emailLibrary/utils.js")


@when("its strategy is inspected")
def inspect_sanitizer_strategy(uixssctx):
    body = _slice_function(uixssctx["utils"], "function _sanitizeHtml(")
    uixssctx["sanitizer_body"] = body
    # An allowlist sanitizer keeps only an approved tag set: it names an
    # ALLOW(ED)_TAGS collection and removes/unwraps any element whose tag is NOT
    # in it (a negated membership test). The shipped version has neither — it
    # only removes a fixed denylist of tags via querySelectorAll.
    names_allow_set = re.search(
        r"\b(?:ALLOW(?:ED)?_TAGS?|allow(?:ed)?Tags|TAG_ALLOWLIST|ALLOWLIST)\b", body
    )
    negated_membership_removal = re.search(
        r"!\s*\w*[Aa]llow\w*\.has\(", body
    ) or re.search(r"!\s*\w*[Aa]llow\w*\.includes\(", body)
    uixssctx["has_allowlist"] = bool(names_allow_set and negated_membership_removal)
    uixssctx["has_denylist_remove"] = bool(
        re.search(r"querySelectorAll\([^)]*script[^)]*\)\s*\.?\s*\n?\s*\.forEach", body)
        or "script, iframe" in body
    )


@then("it keeps only an allowed set of tags rather than removing a fixed denylist")
def sanitizer_is_allowlist(uixssctx):
    # @pending: _sanitizeHtml strips a fixed denylist of tags; no allowlist.
    assert uixssctx["has_denylist_remove"], (
        "expected the shipped denylist tag-removal in _sanitizeHtml"
    )
    assert uixssctx["has_allowlist"], (
        "_sanitizeHtml is a denylist (removes a fixed tag set) rather than an "
        "allowlist that keeps only approved tags"
    )


@when("the thread and quote rendering passes are inspected")
def inspect_reparse(uixssctx):
    src = uixssctx["reader"]
    thread = _slice_function(src, "function _renderThreadStructure(")
    fold = _slice_function(src, "function _foldQuotedReplies(")
    # A raw re-parse of the already-sanitized HTML: each pass calls
    # new DOMParser().parseFromString(...) on the sanitized content.
    reparse = re.compile(r"new\s+DOMParser\(\)\s*\.parseFromString")
    uixssctx["reparse_count"] = len(reparse.findall(thread)) + len(reparse.findall(fold))


@then("the already-sanitized HTML is not handed to another raw DOM parse")
def no_reparse(uixssctx):
    # @pending: both _renderThreadStructure and _foldQuotedReplies re-parse the
    # sanitized HTML with a fresh DOMParser — the mXSS surface.
    assert uixssctx["reparse_count"] == 0, (
        f"sanitized email HTML is re-parsed raw {uixssctx['reparse_count']} more "
        "time(s) (mXSS surface) before display"
    )


@when("the inline-style scrubbing is inspected")
def inspect_style_scrub(uixssctx):
    body = uixssctx.get("sanitizer_body") or _slice_function(
        uixssctx["utils"], "function _sanitizeHtml("
    )
    # The style filter neutralizes dangerous declarations. Today it only blocks
    # 'javascript:' and 'expression(' substrings — it never touches url(), so a
    # surviving background-image: url(http://beacon) fires on open.
    uixssctx["style_blocks_url"] = bool(re.search(r"url\(", body))


@then("url() references in surviving styles are stripped or blocked")
def style_neutralizes_url(uixssctx):
    # @pending: the inline-style scrubber does not neutralize url() — a
    # background-image url() read-receipt beacon survives.
    assert uixssctx["style_blocks_url"], (
        "the inline-style scrubber never neutralizes url() — a background-image "
        "url() tracking beacon survives sanitizing"
    )


# ===========================================================================
# #391 — document title injected raw into the tab bar
# ===========================================================================
@given("the document browser module")
def given_document(uixssctx):
    uixssctx["doc"] = _read("document.js")


@when("the language-picker and suggestion-reason sinks are inspected")
def inspect_doc_escaped_siblings(uixssctx):
    src = uixssctx["doc"]
    # Lang-picker label escapes via uiModule.esc(...); suggestion reason via _esc(...).
    uixssctx["langpicker_escaped"] = bool(
        re.search(r"doc-langpicker-label\">\$\{uiModule\.esc\(", src)
    )
    uixssctx["suggestion_escaped"] = bool(
        re.search(r"doc-suggestion-reason\">\$\{_esc\(", src)
    )


@then("both escape their interpolated text with the escaping helper")
def doc_siblings_escaped(uixssctx):
    # GREEN: the two sibling title-bearing sinks already escape.
    assert uixssctx["langpicker_escaped"], "lang-picker label is not escaped via uiModule.esc"
    assert uixssctx["suggestion_escaped"], "suggestion reason is not escaped via _esc"


@when("the tab-bar title interpolation is inspected")
def inspect_tab_title(uixssctx):
    src = uixssctx["doc"]
    # The shipped tab markup interpolates title/shortTitle raw:
    #   title="${title}"  and  <span class="doc-tab-title">${shortTitle}</span>
    uixssctx["tab_title_raw"] = bool(re.search(r"doc-tab[^\n]*title=\"\$\{title\}\"", src))
    uixssctx["tab_shorttitle_raw"] = bool(
        re.search(r"doc-tab-title\">\$\{shortTitle\}<", src)
    )
    # A fix wraps both in the escaper.
    uixssctx["tab_title_escaped"] = bool(
        re.search(r"title=\"\$\{(?:_esc|uiModule\.esc)\(\s*title", src)
    )
    uixssctx["tab_shorttitle_escaped"] = bool(
        re.search(r"doc-tab-title\">\$\{(?:_esc|uiModule\.esc)\(\s*shortTitle", src)
    )


@then(
    "the title and short title are escaped before they are placed into the tab markup"
)
def tab_title_escaped(uixssctx):
    # @pending: the tab title/short-title are interpolated raw today.
    assert uixssctx["tab_title_raw"] or uixssctx["tab_shorttitle_raw"], (
        "expected the raw tab-bar title interpolation"
    )
    assert uixssctx["tab_title_escaped"] and uixssctx["tab_shorttitle_escaped"], (
        "the document tab-bar title/short-title are interpolated into innerHTML "
        "without escaping"
    )


# ===========================================================================
# #395 — version-history summary/source injected raw
# ===========================================================================
@when("the version-history diff builder is inspected")
def inspect_diff_builder(uixssctx):
    body = _slice_function(uixssctx["doc"], "function _buildDiffSummary(")
    # Each diff line is escaped with _escHtml before being interpolated.
    uixssctx["diff_escaped"] = len(re.findall(r"_escHtml\(", body)) >= 2


@then("each diff line is escaped with the escaping helper")
def diff_escaped(uixssctx):
    # GREEN: the diff builder escapes every line via _escHtml.
    assert uixssctx["diff_escaped"], "version diff lines are not escaped via _escHtml"


@when("the version-history list interpolation is inspected")
def inspect_version_list(uixssctx):
    src = uixssctx["doc"]
    # Shipped: summary/source interpolated raw in the versions.map template.
    uixssctx["summary_raw"] = bool(
        re.search(r"doc-version-summary\">\$\{v\.summary\}<", src)
    )
    uixssctx["source_raw"] = bool(re.search(r"doc-version-source\">\$\{v\.source\}<", src))
    # A fix escapes both.
    uixssctx["summary_escaped"] = bool(
        re.search(r"doc-version-summary\">\$\{(?:_escHtml|_esc)\(\s*v\.summary", src)
    )
    uixssctx["source_escaped"] = bool(
        re.search(r"doc-version-source\">\$\{(?:_escHtml|_esc)\(\s*v\.source", src)
    )


@then("the summary and source values are escaped before interpolation")
def version_escaped(uixssctx):
    # @pending: v.summary and v.source are interpolated raw at the list sink.
    assert uixssctx["summary_raw"] or uixssctx["source_raw"], (
        "expected the raw version summary/source interpolation"
    )
    assert uixssctx["summary_escaped"] and uixssctx["source_escaped"], (
        "version-history summary/source are interpolated into innerHTML without "
        "escaping (the diff sibling is escaped)"
    )


# ===========================================================================
# #397 — image EXIF GPS interpolated raw in the gallery detail panel
# ===========================================================================
@given("the gallery browser module")
def given_gallery(uixssctx):
    uixssctx["gallery"] = _read("gallery.js")


@when("the camera, source and session detail fields are inspected")
def inspect_gallery_siblings(uixssctx):
    src = uixssctx["gallery"]
    uixssctx["camera_escaped"] = bool(re.search(r"\$\{_esc\(\s*img\.camera\s*\)\}", src))
    uixssctx["model_escaped"] = bool(re.search(r"\$\{_esc\(\s*img\.model\s*\)\}", src))
    uixssctx["session_escaped"] = bool(
        re.search(r"\$\{_esc\(\s*img\.session_name\s*\)\}", src)
    )


@then("each escapes its value with the escaping helper")
def gallery_siblings_escaped(uixssctx):
    # GREEN: the sibling metadata fields all escape via _esc.
    assert uixssctx["camera_escaped"], "img.camera is not escaped via _esc"
    assert uixssctx["model_escaped"], "img.model is not escaped via _esc"
    assert uixssctx["session_escaped"], "img.session_name is not escaped via _esc"


@when("the location detail interpolation is inspected")
def inspect_gallery_gps(uixssctx):
    src = uixssctx["gallery"]
    # Shipped: ${img.gps.lat}, ${img.gps.lng} interpolated raw.
    uixssctx["gps_raw"] = bool(
        re.search(r"\$\{img\.gps\.lat\}\s*,\s*\$\{img\.gps\.lng\}", src)
    )
    # A fix wraps both in _esc.
    uixssctx["gps_escaped"] = bool(
        re.search(r"\$\{_esc\(\s*img\.gps\.lat\s*\)\}", src)
        and re.search(r"\$\{_esc\(\s*img\.gps\.lng\s*\)\}", src)
    )


@then("the GPS latitude and longitude are escaped before interpolation")
def gallery_gps_escaped(uixssctx):
    # @pending: img.gps.lat / img.gps.lng are interpolated raw at the detail sink.
    assert uixssctx["gps_raw"], "expected the raw GPS lat/lng interpolation"
    assert uixssctx["gps_escaped"], (
        "gallery GPS lat/lng are interpolated raw (the sibling metadata fields "
        "use _esc)"
    )
