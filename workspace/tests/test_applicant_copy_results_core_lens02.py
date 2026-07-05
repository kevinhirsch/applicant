"""Regression coverage for exhaustive-audit-pass 2, lens 02 (copy & voice):
findings against ``applicantResults.js`` (#156-#162, #175) and the shared
error/status helpers in ``applicantCore.js`` (#138, #143, #167, #168).

Every fact below is read from the actual shipped source via ``pathlib`` — no
browser, no DOM, no real socket — following the project's established
source-assertion convention for these copy-audit tests. Each assertion was
hand-verified to go red when the underlying fix is reverted (``cp`` the file
to a backup, revert the change, rerun to see a real ``AssertionError``, then
restore from the backup) per the project's revert-verify convention.

House voice for this lens: first-person-singular, calm, plain, quietly
confident, on-your-side — never third-person self-reference ("the
assistant"), never raw technical detail (URLs, HTTP status codes) in
user-facing copy.
"""

from __future__ import annotations

import pathlib

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_RESULTS_JS = _REPO / "static" / "js" / "applicantResults.js"
_CORE_JS = _REPO / "static" / "js" / "applicantCore.js"


def _results_src() -> str:
    return _RESULTS_JS.read_text(encoding="utf-8")


def _core_src() -> str:
    return _CORE_JS.read_text(encoding="utf-8")


# ── applicantResults.js ──────────────────────────────────────────────────────


def test_funnel_matched_tip_is_first_person():
    """#156: the funnel's "Matched" step tooltip spoke in third person."""
    src = _results_src()
    assert "Roles I found that fit your criteria." in src
    assert "Roles the assistant found that fit your criteria." not in src


def test_sources_section_tip_is_first_person_and_plain():
    """#157: the per-source section tooltip spoke in third person and used
    the analyst word "converts"."""
    src = _results_src()
    assert "Each place I search, ranked by how well it's working for you." in src
    assert "Each source the assistant searches, ranked by how well it converts for you." not in src


def test_signature_section_tip_drops_bias_and_third_person():
    """#158: "the bias the assistant learns and applies" read negatively and
    spoke in third person."""
    src = _results_src()
    assert "what I've learned to favor for you." in src
    assert "the bias the assistant learns and applies" not in src


def test_empty_state_is_first_person():
    """#159: the brand-new-user empty state credited "your assistant"."""
    src = _results_src()
    assert "once I\\'ve submitted a few applications for you" in src
    assert "your assistant has submitted a few applications" not in src


def test_offline_state_title_and_body_match_the_portal_pattern():
    """#160: Results' offline title/body drifted from the Portal's "Not
    connected yet" wording and spoke in third person."""
    src = _results_src()
    assert "'Not connected yet'" in src
    assert "Your results will appear here once I\\'m connected and running." in src
    assert "Results are offline" not in src
    assert "your assistant is connected and running" not in src


def test_funnel_rate_label_is_plain_not_analyst_speak():
    """#161: "of prior" was clipped analyst-speak."""
    src = _results_src()
    assert "of the step before" in src
    assert "of prior" not in src


def test_signature_sample_count_avoids_funnel_jargon():
    """#162: "converting application(s)" was funnel-analytics jargon."""
    src = _results_src()
    assert "that moved forward." in src
    assert "converting application" not in src


def test_gated_fallback_message_is_plain_and_actionable():
    """#175: the Results gated fallback used "onboarding" jargon."""
    src = _results_src()
    assert "Finish setup and connect a model — your results will start appearing here." in src
    assert "Finish onboarding and connect a model to start collecting results." not in src


# ── applicantCore.js — shared error copy (high leverage: feeds every surface
#    that imports errText/_fetchJSON) ────────────────────────────────────────


def test_fetchjson_never_builds_a_user_facing_message_from_raw_url_status():
    """#138: the shared fetch helper used to fall back to a raw
    "`${url} → ${res.status}`" string as the thrown error's .message, which
    could reach a toast verbatim. The raw detail may still be logged to the
    console for debugging (not asserted against here), but the thrown
    Error's default message — read a few lines above where the status
    check begins — must be plain, calm copy, never the interpolated
    URL/status template."""
    src = _core_src()
    idx = src.index("if (!res.ok) {")
    body = src[idx : idx + 600]
    assert "`${url} → ${res.status}`" not in body.split("console.error")[0], (
        "the raw URL/status template must not feed the thrown error's "
        "user-facing .message"
    )
    assert "Something went wrong — please try again." in body


def test_timeout_copy_is_first_person():
    """#143: the shared timeout copy said "the assistant is still working",
    leaking third person into every surface that imports errText."""
    src = _core_src()
    assert "I’m still working. Try again shortly." in src
    assert "the assistant is still working" not in src


def test_network_error_copy_is_first_person_and_reassuring():
    """#168: the shared network-error copy said "Can't reach the assistant
    right now" — third person, and gave no sense that it would keep trying."""
    src = _core_src()
    assert "I can’t connect right now — I’ll keep trying." in src
    assert "Can’t reach the assistant right now." not in src
    assert "the assistant" not in src


def test_auth_expired_copy_drops_session_jargon():
    """#167: "Your session expired" used internal "session" terminology in
    the plain-language error map."""
    src = _core_src()
    assert "You’ve been signed out — please sign in again." in src
    assert "Your session expired — please sign in again." not in src
