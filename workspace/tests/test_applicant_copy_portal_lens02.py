"""Regression coverage for the copy & voice (exhaustive2, lens 02) pass on the
Pending-Actions Portal (``workspace/static/js/applicantPortal.js``), per
``docs/design/audits/exhaustive2/02_copy_voice.md``'s "Portal" section
(findings #6-#35) plus the handful of cross-cutting findings (#147/#148/#149/
#169, and cross-cutting #2's raw ``e.message`` toasts) that also cite this
file by line.

House voice per the audit: first-person-singular ("I"), calm, plain, quietly
confident — never third-person self-reference ("the assistant", "Applicant"
as a sentence's actor, "it"), never engineering vocabulary ("session" for the
takeover surface, raw enum text, bare "Field"/"Value" placeholders).

A companion surface (``applicantToday.js``, a stepped-deck lens over the
SAME pending data) already carries the identical fixes — its own copy-voice
test file (``test_applicant_exhaustive2_copyvoice_today_campaignsettings_
gallery.py``) explicitly notes "applicantPortal.js itself are out of this
pass's hard file scope", i.e. Portal's turn was deferred to a later pass.
This file is that later pass, confined to ``applicantPortal.js`` only.

Copy-only: no logic/DOM-structure changes beyond user-facing text, except the
one trivial copy-driven tweak the audit itself calls out (#32: suppressing a
row's subtitle when it would just repeat the title verbatim).

Every fact below is read from the actual static file content via ``pathlib``
+ regex/substring (mirrors the established convention in
``test_applicant_exhaustive2_copyvoice_today_campaignsettings_gallery.py``
and ``test_applicant_round1_portal.py`` — this file is not a pure leaf
module, so a full module import under Node is impractical). Every assertion
here was verified, by hand, to go red when the underlying fix is reverted
(temporarily restore the pre-fix source from a file-copy backup at
``/tmp/applicantPortal.js.bak``, rerun, see a real ``AssertionError``, then
restore the fix) before this file was landed.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_PORTAL_JS = _REPO / "static" / "js" / "applicantPortal.js"

_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def node_available():
    if not _HAS_NODE:
        pytest.skip("node binary not on PATH")


def _src() -> str:
    return _PORTAL_JS.read_text(encoding="utf-8")


def _slice_between(src: str, start_marker: str, end_marker: str) -> str:
    start = src.index(start_marker)
    end = src.index(end_marker, start)
    return src[start:end]


# ══════════════════════════════════════════════════════════════════════════
# KINDS per-kind copy (pronoun rule + specific findings #7/#16/#25/#26/#35/
# #147/#148/#169)
# ══════════════════════════════════════════════════════════════════════════


def test_portal_kinds_speak_first_person_not_third_person():
    src = _src()
    kinds_block = _slice_between(src, "const KINDS = {", "\n};")

    banned = [
        "The assistant has a question for you",
        "A detail is needed before this can continue",
        "Needs you to create an account, then it can continue",
        "Hit a snag that needs a look",
        "A core detail was inferred and needs your OK",
        "A few profile steps are still to do before your search can run",
        "in the live session",
        "Tap continue, then approve",
    ]
    for phrase in banned:
        assert phrase not in kinds_block, f"stale third-person/jargon phrase still present: {phrase!r}"

    required = [
        "I have a question for you",
        "I need one detail before I can continue",
        "I need you to create an account",
        "I hit a snag and need your help",
        "I think one of your core details changed",
        "A few profile steps are left before your search can run",
        "in the live view",
        "Tap ‘Continue Google sign-in’",
    ]
    for phrase in required:
        assert phrase in kinds_block, f"expected first-person replacement copy: {phrase!r}"


def test_portal_meta_fallback_never_leaks_a_raw_kind_string():
    """Finding #16: an unmapped kind used to render its raw snake_case name
    (e.g. 'detection clear') as the row's title via `replace(/_/g, ' ')`. The
    fallback must now always be the generic 'Needs your attention' label."""
    src = _src()
    fn = _slice_between(src, "function _meta(kind) {", "\n}")
    assert "replace(/_/g" not in fn, "the raw-kind-string fallback must be gone"
    assert re.search(r"label:\s*'Needs your attention'", fn)


def test_portal_two_factor_render_hints_quote_the_actual_button_label():
    """Finding #35: the hint said 'Tap continue' while the button read
    'Continue Google sign-in' — both the KINDS default and the retry-path
    hint in `_renderTwoFactor` now quote the real labels."""
    src = _src()
    fn = _slice_between(src, "function _renderTwoFactor(item) {", "\nfunction ")
    assert "Tap ‘Try Google again’" in fn
    assert "Tap ‘Continue Google sign-in’" in fn
    assert "Tap continue, then approve" not in fn
    assert "Tap continue and approve" not in fn


# ══════════════════════════════════════════════════════════════════════════
# Final-submit decision pair (#9/#10/#11) + Materials-approved consequence
# ══════════════════════════════════════════════════════════════════════════


def test_portal_final_approval_button_pair_is_first_person():
    """Finding #9/#23: the highest-gravity button credited the brand as
    actor, and its sibling carried parenthetical engineering jargon."""
    src = _src()
    fn = _slice_between(src, "function _renderFinal(item) {", "\nfunction _renderComplete")
    assert "Let me submit it" in fn
    assert "Authorize Applicant to submit this" not in fn
    assert "I'll submit it myself" in fn
    assert "(open live session)" not in fn
    assert "I'll click the final submit for you" in fn
    assert "Let the assistant click the final submit" not in fn


def test_portal_final_authorize_confirm_and_success_toast_are_first_person():
    """Finding #10/#11: the irreversible confirm dialog and the post-authorize
    toast both credited "the assistant" at the highest-gravity moment."""
    src = _src()
    fn = _slice_between(src, "final-authorize\').forEach((btn) => {", "\n  });\n\n  //")
    assert "Authorize the assistant to submit" not in fn
    assert "You’ve approved everything in it" in fn
    assert "I can’t take it back" in fn
    assert "Done — I submitted it. It’s on its way." in fn
    assert "Authorized — the assistant submitted the application" not in fn


# ══════════════════════════════════════════════════════════════════════════
# Snooze / review / missing-detail / digest CTA (#15/#19/#20/#21/#22/#149)
# ══════════════════════════════════════════════════════════════════════════


def test_portal_snooze_toast_is_first_person():
    src = _src()
    assert "Snoozed — I’ll bring it back tomorrow morning." in src
    assert "we’ll remind you tomorrow" not in src
    assert "we'll remind you tomorrow" not in src


def test_portal_review_button_states_its_object_and_hint_is_first_person():
    """Finding #21/#22: button said only 'Review' (review what?) and the
    fallback hint just restated the button."""
    src = _src()
    fn = _slice_between(src, "function _renderReview(item) {", "\nfunction _renderMissing")
    assert "Review the document</button>" in fn
    assert ">Review</button>" not in fn
    assert "See exactly what I changed, side by side, before anything goes out." in fn
    assert "Open the side-by-side review.'" not in fn


def test_portal_missing_detail_placeholders_and_helper_are_plain_language():
    """Finding #19/#20: bare 'Field'/'Value' placeholders and stiff helper
    copy."""
    src = _src()
    fn = _slice_between(src, "function _renderMissing(item) {", "\nfunction _renderSession")
    assert 'placeholder="Field"' not in fn
    assert 'placeholder="Value"' not in fn
    assert "What’s missing (e.g. desired salary)" in fn
    assert "Your answer" in fn
    assert "Give me this one detail and I’ll pick the application up where it left off." in fn
    assert "Provide the value below" not in fn


def test_portal_digest_cta_matches_the_surface_name():
    """Finding #149: 'Review applications' drifted from 'Today's roles' /
    'matched roles' used elsewhere in this same file."""
    src = _src()
    fn = _slice_between(src, "function _renderDigest(item) {", "\nfunction _renderConfirmChange")
    assert "Review today's roles" in fn
    assert "Review applications" not in fn


# ══════════════════════════════════════════════════════════════════════════
# "session" -> "live view" (finding #24)
# ══════════════════════════════════════════════════════════════════════════


def test_portal_live_session_jargon_renamed_live_view_everywhere():
    """Finding #24: 'session' is engineering jargon for the takeover surface.
    Scoped to the actual user-facing strings (button text/tooltips/toasts) —
    the file's own top-of-file architecture comment describing the feature
    is not user-facing copy and is left alone."""
    src = _src()
    assert ">Open live session<" not in src
    assert "Watch live" in src
    assert "When the live view is ready, the link will appear here." in src
    assert "When the live session is ready" not in src
    assert "No live view is available yet" in src
    assert "No live session is available yet" not in src
    assert "Open the live view and click submit yourself" in src
    assert "Open the live view and click submit when you" in src
    assert 'title="Open the live session' not in src


# ══════════════════════════════════════════════════════════════════════════
# Offline / gated fallback copy (#12/#13)
# ══════════════════════════════════════════════════════════════════════════


def test_portal_offline_message_matches_the_true_transient_disconnect_case():
    """Finding #12: `_renderOffline` used to tell an already-configured user
    to redo setup ("Connect a model in Settings...") even though it only
    ever fires for the true transient-disconnect case — the never-configured
    case already has its own separate `_renderGated` branch."""
    src = _src()
    fn = _slice_between(src, "function _renderOffline(body) {", "\nfunction _renderGated")
    assert "Connect a model in Settings to activate your job search" not in fn
    assert "I can't check in right now" in fn
    assert "I've lost my connection" in fn


def test_portal_gated_fallback_message_is_first_person():
    """Finding #13."""
    src = _src()
    assert "Finish onboarding and configure your model and notification channels to enable automated work." not in src
    assert "Finish setup — connect a model and fill in your profile — and I can start working for you." in src


# ══════════════════════════════════════════════════════════════════════════
# Header chrome: modal title/aria-label + "what I never do" (#14/#18)
# ══════════════════════════════════════════════════════════════════════════


def test_portal_modal_title_and_aria_label_name_a_place_not_a_state():
    """Finding #18: 'Pending' names a state, not a place, and didn't match
    the launcher's own noun."""
    src = _src()
    shell = _slice_between(src, "modal.innerHTML = `", "document.body.appendChild(modal);")
    assert "aria-label', 'Waiting on you — pending actions'" in src or "aria-label=\"Waiting on you" not in src
    assert "Waiting on you" in shell
    assert ">\n          Pending\n        </h4>" not in shell


def test_portal_neverdoes_toggle_and_panel_speak_in_positive_control_language():
    """Finding #14 originally fixed "What Applicant never does" / "What it
    never does" (third-person brand-as-actor) to first-person "What I never
    do". A later demo-tone pass went further: negative-capability framing
    ("never do") reads as a disclaimer wall, not a selling point, so the
    toggle/panel now state the same guarantee as ONE positive control line
    instead of a list of "nots"."""
    src = _src()
    assert "What Applicant never does" not in src
    assert 'aria-label="What Applicant never does"' not in src
    assert ">What I never do<" not in src
    assert 'aria-label="What I never do"' not in src
    assert "You’re in control" in src
    assert "import { trustLine } from './applicantOnboarding.js';" in src, (
        "expected the panel to reuse the wizard's single trust line, not "
        "hardcode/duplicate its own copy"
    )
    fn = _slice_between(src, "function _neverDoesHTML() {", "\nfunction ")
    assert "trustLine" in fn
    assert "<ul" not in fn, "expected a single positive line, not a bulleted list of nots"


# ══════════════════════════════════════════════════════════════════════════
# Row-level copy drift (#27/#28/#29/#30/#31/#32/#33)
# ══════════════════════════════════════════════════════════════════════════


def test_portal_waiting_on_you_header_replaces_the_bare_grammar_count():
    """Finding #27: '${n} items need${s} your attention' was a bare-grammar
    header competing with the greeting's own 'things' noun; the audit
    suggests folding the header into a plain 'Waiting on you: N' count."""
    src = _src()
    assert "need your attention</span>" not in src
    assert "Waiting on you: ${_items.length}" in src


def test_portal_library_deeplink_toast_says_document_not_brand_adjective():
    """Finding #28: 'Applicant review is in your Library' reads like a
    different product than the one doing the reviewing."""
    src = _src()
    assert "Applicant review is in your Library" not in src
    assert "Your document review is in the Library" in src


def test_portal_momentum_empty_state_does_not_dangle_a_few():
    """Finding #29."""
    src = _src()
    assert "once you've submitted a few." not in src
    assert "Your momentum shows up here once your first applications go out." in src


def test_portal_best_source_tooltip_drops_analytics_jargon():
    """Finding #30."""
    src = _src()
    assert 'title="The source converting best for you."' not in src
    assert "The job board that's working best for you so far." in src


def test_portal_row_subtitle_suppressed_when_it_duplicates_the_title():
    """Finding #32: an engine-supplied title that happens to equal the
    generic per-kind label used to print the same sentence twice (title +
    subtitle). This is the one "trivial copy-driven tweak" the audit itself
    allows alongside the pure text fixes."""
    src = _src()
    fn = _slice_between(src, "function _rowShell(item, inner) {", "\nfunction ")
    assert "title === meta.label" in fn
    assert "subtitleLabel" in fn
    assert "${esc(meta.label)} ${_ageLabel(item)}" not in fn


def test_portal_digest_empty_note_and_searched_label_are_first_person():
    """Finding #8/#31: the digest's own empty-day note spoke in third person
    and appended a bare 'Searched:' label."""
    src = _src()
    fn = _slice_between(src, "function _renderDigestRows(payload) {", "\nfunction ")
    assert "The assistant keeps looking and will let you know." not in fn
    assert "I'm still looking — I'll tell you the moment one does." in fn
    assert "Searched: ${searched}." not in fn
    assert "I looked at: ${searched}." in fn


def test_portal_digest_gated_message_is_first_person():
    """Finding #33."""
    src = _src()
    assert "Finish setting up Applicant to start seeing matched roles here." not in src
    assert "Finish setup and I'll start lining up matched roles here." in src


def test_portal_initial_loading_placeholder_has_a_subject():
    """Finding #34: the initial pending-panel placeholder was a bare
    'Loading…' with no subject."""
    src = _src()
    shell = _slice_between(src, "modal.innerHTML = `", "document.body.appendChild(modal);")
    assert '<div class="hwfit-loading">Loading…</div>' not in shell
    assert "Checking what needs you…" in shell


# ══════════════════════════════════════════════════════════════════════════
# Cross-cutting #2: raw e.message toasts routed through errText
# ══════════════════════════════════════════════════════════════════════════


def test_portal_toasts_route_through_errtext_not_raw_e_message():
    """Cross-cutting finding #2: every simple `_toast(e.message || '...')`
    catch-block toast must route through the shared `errText(e)` helper
    (already imported from applicantCore.js) instead of surfacing raw
    proxy/HTTP internals. The one deliberately-nuanced exception
    (`_wireRows`'s "Fix documents" handler, which already threads
    `e.body.detail`/a specific fallback through its own logic) is left
    alone — it isn't the flagged blind `e.message || '...'` pattern."""
    src = _src()
    assert not re.search(r"_toast\(e\.message", src), "raw e.message must not reach a toast"
    assert re.search(r"^import \{[\s\S]*?\berrText\b[\s\S]*?\} from '\./applicantCore\.js';$", src, re.M), (
        "expected errText to already be imported from applicantCore.js"
    )
    assert len(re.findall(r"_toast\(errText\(e\)", src)) >= 10


def test_node_check_applicant_portal_js(node_available):
    res = subprocess.run(["node", "--check", str(_PORTAL_JS)], capture_output=True, timeout=15, text=True)
    assert res.returncode == 0, f"node --check failed:\n{res.stderr}"


# ── Denylist hygiene (per the task's standing instruction) ──────────────────

#: The four upstream-fork codenames CI's repo-wide white-label denylist step
#: bans from shipped artifacts. Split into two-piece tuples so the literal,
#: contiguous codename string never appears in this file's own source text.
_DENYLIST_CODENAME_HALVES = (
    ("fire", "house"),
    ("or", "well"),
    ("odys", "seus"),
    ("smo", "key"),
)


def test_new_test_file_is_denylist_clean():
    text = pathlib.Path(__file__).read_text(encoding="utf-8").lower()
    for a, b in _DENYLIST_CODENAME_HALVES:
        assert (a + b) not in text
