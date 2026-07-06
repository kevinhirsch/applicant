"""Activation backlog §7.5 — "Resume-health / ATS-parseability score at upload".

Reachability investigation: `src/applicant/core/rules/ats_parseability.py` (issue
#370's `check_render_parseability`) already existed engine-side as a pure, generic
rule (text-layer length, contact email recoverable, recognizable section headers),
but it was wired ONLY into `submission_service._verify_ats_parse` — a self-check on
the GENERATED résumé render right before final submit. It was never run against the
résumé the user actually uploads at onboarding, so there was no "instant value hit"
at upload time as the audit calls for (product-gaps #48).

Fix, split across two repos:
  * Engine (see tests/unit/test_cov_backlog_resumehealth.py): `OnboardingService.
    ingest_base_resume` now also runs `check_render_parseability` against the
    uploaded résumé's own extractable text and returns the verdict on
    `ReconciliationResult`; `POST /api/onboarding/{cid}/base-resume` surfaces it as
    a `resume_health: {parseable, issues}` dict in the (unmodified-elsewhere)
    upload response. No new scoring/NLP was built — the existing pure rule is
    reused at a new call site.
  * Front-door (this file): `workspace/static/js/applicantOnboarding.js`'s resume
    upload step (`_renderBaseResume` / `readResume`) already shows a post-upload
    confirmation ("Read N details from your resume — we've filled in the next
    steps for you to review"); this is the exact same moment/location a prior
    round wired that confirmation into, so the resume-health line is appended to
    that SAME message rather than becoming a new step or a separate UI surface.
    The workspace's `/api/applicant/setup/onboarding/{cid}/base-resume` proxy
    (`applicant_setup_routes.py`) already returns the engine's JSON response
    verbatim (`JSONResponse(content=data)`), so no workspace route change is
    needed — only the JS needed to start reading the new field.

Every assertion below was verified against a temporary revert of the JS change
(edit -> rerun -> confirm a real AssertionError -> restore) before being left in
its final, passing form.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent  # workspace/
ONBOARDING_JS = _REPO / "static" / "js" / "applicantOnboarding.js"
_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _src() -> str:
    return ONBOARDING_JS.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


def _run_node(script: str) -> dict:
    res = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO,
        capture_output=True,
        timeout=15,
        text=True,
    )
    if res.returncode != 0:
        raise AssertionError(f"node failed:\n{res.stderr}")
    out_lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
    if not out_lines:
        raise AssertionError("node produced no stdout")
    return json.loads(out_lines[-1])


def _resume_health_block() -> str:
    src = _src()
    return _slice_between(src, "const _RESUME_HEALTH_HINTS = [", "function _tip(text) {")


# ===========================================================================
# Wiring: the resume-health line lands in the SAME post-upload confirmation
# message that already surfaces "Read N details..." — not a new step/surface.
# ===========================================================================


def test_read_resume_appends_resume_health_to_the_same_confirmation_message():
    src = _src()
    m = re.search(
        r"st\.innerHTML = `\$\{_resumeReadSummaryHTML\(res\)\}\$\{([^}]+)\}`;",
        src,
    )
    assert m, "the post-upload confirmation assignment must exist"
    assert m.group(1).strip() == "_resumeHealthHTML(res)", (
        "resume health must be appended INTO the existing confirmation message "
        "(same st.innerHTML assignment), not rendered as a separate step/element"
    )
    # HONESTY: the confirmation must not read the attribute-cloud total — the
    # "I read N details" claim counts only what THIS parse extracted.
    assert "res.attribute_count" not in src, (
        "the upload confirmation must use parsed_field_count, not the campaign's "
        "whole attribute cloud"
    )
    assert "res.parsed_field_count" in src


def test_resume_health_function_reads_the_engine_response_field():
    block = _resume_health_block()
    assert "res.resume_health" in block or "res && res.resume_health" in block
    assert "function _resumeHealthHTML(" in block


def test_healthy_case_reuses_existing_admin_success_class_not_a_new_style():
    """No bespoke CSS class introduced — reuse `.admin-success` like the rest of
    the wizard (per repo CLAUDE.md: reuse the workspace design system)."""
    block = _resume_health_block()
    assert 'class="admin-success"' in block


# ===========================================================================
# Behavior: the real pure `_resumeHealthHTML` / `_friendlyResumeHealthIssue`
# functions, sliced out of the live file and executed under node.
# ===========================================================================


def _esc_stub() -> str:
    return (
        "function esc(s) { return (s == null ? '' : String(s)).replace(/[&<>\"']/g, "
        "(c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])); }"
    )


def test_healthy_resume_renders_looks_good_with_no_issue_list(node_available):
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.healthy = _resumeHealthHTML({{ resume_health: {{ parseable: true, issues: [] }} }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert "admin-success" in out["healthy"]
    assert "looks good" in out["healthy"].lower()
    assert "<li>" not in out["healthy"], "a clean resume must not render an issue list"


def test_missing_email_issue_is_translated_to_a_friendly_specific_hint(node_available):
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.flagged = _resumeHealthHTML({{
          resume_health: {{ parseable: false, issues: ["contact email is not recoverable"] }}
        }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    html = out["flagged"]
    assert "admin-success" not in html, "an issue-flagged resume must not claim success styling"
    assert "<li>" in html
    # The raw engine string is translated to a friendlier, specific hint rather
    # than surfaced verbatim.
    assert "contact email is not recoverable" not in html
    assert "detectable in the text" in html


def test_unrecognized_issue_text_falls_back_to_the_raw_engine_message(node_available):
    """If the engine ever adds a new issue string this JS doesn't know about yet,
    it must still show SOMETHING (the raw text) rather than silently drop it."""
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.flagged = _resumeHealthHTML({{
          resume_health: {{ parseable: false, issues: ["some brand-new issue string"] }}
        }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert "some brand-new issue string" in out["flagged"]


def test_missing_resume_health_field_degrades_gracefully_and_honestly(node_available):
    """An engine response with no `resume_health` key at all must not crash the
    wizard — and HONESTY: the absence of a verdict must render as "not
    assessed", never as success styling or a "looks good" claim."""
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.result = _resumeHealthHTML({{}});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert "admin-success" not in out["result"], (
        "a missing verdict must never be styled as success"
    )
    assert "looks good" not in out["result"].lower()
    assert "assess" in out["result"].lower()


# ===========================================================================
# Product-honesty regressions (live audit): every celebratory claim in the
# upload step derives from an explicit engine-computed verdict/count.
# ===========================================================================


def test_explicit_good_verdict_renders_looks_good(node_available):
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.good = _resumeHealthHTML({{ resume_health: {{ verdict: 'good', parseable: true, issues: [] }} }});
        out.unknown = _resumeHealthHTML({{ resume_health: {{ verdict: 'unknown', parseable: false, issues: [] }} }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    assert "looks good" in out["good"].lower()
    # An explicit-but-unknown verdict is NOT success.
    assert "looks good" not in out["unknown"].lower()
    assert "admin-success" not in out["unknown"]


def test_new_issue_strings_get_friendly_hints(node_available):
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.flagged = _resumeHealthHTML({{
          resume_health: {{ verdict: 'issues', parseable: false, issues: [
            "your name is not detectable in the text",
            "a phone number is not detectable in the text",
            "very little text could be read from this file"
          ] }}
        }});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    html = out["flagged"]
    assert "admin-success" not in html
    assert "name isn’t detectable" in html
    assert "phone number isn’t detectable" in html
    assert "small amount of text" in html


def test_preview_card_gates_on_a_real_rendered_artifact():
    """The "I built a polished version (N pages). Looks like a faithful match."
    card may only render when the engine reports `artifact_available: true`
    (a real PDF built by an available toolchain). Anything else — including an
    older engine without the field — gets the honest no-preview message with no
    "Use this version" action and no page count."""
    src = _src()
    start = src.index("async function _buildPreview()")
    end = src.index("\n}", src.index("ao-prev-download"))
    body = src[start:end]
    gate = body.index("p.artifact_available !== true")
    claim = body.index("I built a polished version of your résumé (")
    assert gate < claim, "the artifact_available gate must run before the built-a-version claim"
    unavailable = body[gate:claim]
    assert "couldn’t build a polished preview" in unavailable
    assert "Use this version" not in unavailable
    assert "page" not in unavailable.split("couldn’t build")[1].split("</p>")[0], (
        "the no-artifact message must not carry a page count"
    )


def test_read_summary_is_honest_about_trivial_and_missing_counts(node_available):
    block = _resume_health_block()
    script = textwrap.dedent(f"""
        {_esc_stub()}
        {block}
        const out = {{}};
        out.zero = _resumeReadSummaryHTML({{ parsed_field_count: 0 }});
        out.two = _resumeReadSummaryHTML({{ parsed_field_count: 2 }});
        out.many = _resumeReadSummaryHTML({{ parsed_field_count: 21 }});
        out.missing = _resumeReadSummaryHTML({{}});
        console.log(JSON.stringify(out));
    """)
    out = _run_node(script)
    # Zero parsed fields: an explicit warning, never green success styling.
    assert "couldn’t read any details" in out["zero"]
    assert "admin-success" not in out["zero"]
    # A trivially-small parse is flagged as a likely non-text résumé.
    assert "only read 2 details" in out["two"]
    assert "admin-success" not in out["two"]
    # A real parse keeps the confident first-person line (with the REAL count).
    assert "I read 21 details from your résumé" in out["many"]
    assert "admin-success" in out["many"]
    # No count from the engine -> no number is invented.
    assert "21" not in out["missing"] and "0 details" not in out["missing"]
    assert "admin-success" not in out["missing"]
