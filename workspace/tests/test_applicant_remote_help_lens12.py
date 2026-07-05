"""Regression coverage for two STILL-UNFIXED findings from the help/self-
explanation audit (``docs/design/audits/exhaustive2/12_help_selfexplain.md``),
confined to ``applicantRemote.js`` (the live-takeover surface):

* item 12 — "Takeover semantics are half-explained: how control comes back is
  never stated". The permanent intro paragraph said you could "take over at
  any moment" but never said how control hands back to the assistant or what
  closing the modal does to the session. Fixed by extending the intro copy
  and the two "resume after a step you did yourself" button tooltips.
* item 21 — "Remote first-open card + demote the permanent intro". Remote had
  no first-open explainer at all. Fixed by lifting the digest's first-open
  feedback-loop card pattern (``emailLibrary/applicantDigest.js``
  ``LOOP_INTRO_SEEN_KEY`` / ``_loopIntroHTML`` / ``_dismissLoopIntro``) into
  this file: a localStorage "seen" flag, a small dismissible `admin-card`
  reusing the existing `memory-toolbar-btn` "Got it" dismiss pattern, gated
  so it renders once, ever, per browser.

Follows the established convention (``test_applicant_help_selfexplain_12.py``,
``test_applicant_backlog_referralprompt.py``): every fact is read from the
actual static file content via ``pathlib`` + regex — no browser, no DOM, no
real socket. Each assertion was verified, by hand, to go red when the
underlying fix is reverted (temporarily restore the pre-fix source from a
file-copy backup, rerun, see a real ``AssertionError``, then restore from the
backup — never ``git stash``) before this file was landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
REMOTE_JS = JS_DIR / "applicantRemote.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace
    counting (mirrors test_applicant_help_selfexplain_12.py's helper)."""
    m = re.search(rf"function {re.escape(name)}\([^)]*\)\s*\{{", src)
    assert m, f"expected to find function {name}"
    start = m.end()
    depth = 1
    i = start
    while depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


# ── item 12: the permanent intro states the control-handback contract ──────


def test_intro_paragraph_explains_how_control_hands_back():
    src = _read(REMOTE_JS)
    m = re.search(
        r'id="applicant-remote-intro">(.*?)</p>', src, re.DOTALL,
    )
    assert m, "expected the intro paragraph"
    intro = m.group(1)
    assert re.search(r"pick up.*where you left off", intro, re.IGNORECASE), (
        "expected the intro to state how the assistant resumes after a "
        "hand-back, not just that you can take over"
    )
    assert '"Continue"' in intro or "Continue" in intro, (
        "expected the intro to name the Continue control as the handback action"
    )


def test_intro_paragraph_explains_closing_the_modal_does_not_end_the_session():
    src = _read(REMOTE_JS)
    m = re.search(
        r'id="applicant-remote-intro">(.*?)</p>', src, re.DOTALL,
    )
    assert m, "expected the intro paragraph"
    intro = m.group(1)
    assert re.search(r"closing this window", intro, re.IGNORECASE), (
        "expected the intro to say what closing the modal does"
    )
    assert re.search(r"doesn'?t end the session", intro, re.IGNORECASE), (
        "expected the intro to state closing the modal does NOT end the "
        "live session, only stops watching it"
    )


def test_resume_buttons_explain_the_handback_in_their_tooltip():
    src = _read(REMOTE_JS)
    m_account = re.search(
        r'<button id="applicant-remote-resume-account"[^>]*title="([^"]*)"', src,
    )
    m_detect = re.search(
        r'<button id="applicant-remote-resume-detection"[^>]*title="([^"]*)"', src,
    )
    assert m_account, "expected the resume-account button's title="
    assert m_detect, "expected the resume-detection button's title="
    for title in (m_account.group(1), m_detect.group(1)):
        assert re.search(r"pick up.*where.*left off", title, re.IGNORECASE), (
            "expected the resume button tooltip to state the assistant picks "
            "up where you left off, not just 'continue'"
        )


# ── item 21: Remote first-open explainer card ───────────────────────────────


def test_intro_seen_key_follows_applicant_naming_convention():
    src = _read(REMOTE_JS)
    assert "REMOTE_INTRO_SEEN_KEY = 'applicant-remote-intro-seen'" in src, (
        "expected a localStorage key matching this session's applicant- "
        "prefix convention (NOTIF_SEEN_KEY / RECAP_SEEN_KEY in "
        "applicantPortal.js, LOOP_INTRO_SEEN_KEY in applicantDigest.js)"
    )


def test_first_open_card_html_is_gated_on_seen_state():
    body = _find_function(_read(REMOTE_JS), "_firstOpenCardHTML")
    assert re.search(r"if\s*\(\s*_isFirstOpenSeen\(\)\s*\)\s*return\s*'';", body), (
        "the card must render nothing once the user has dismissed it — "
        "otherwise it would show on every open forever"
    )


def test_first_open_card_explains_what_live_takeover_is_for():
    body = _find_function(_read(REMOTE_JS), "_firstOpenCardHTML")
    assert re.search(r"what live takeover is for", body, re.IGNORECASE)
    assert "creating an account" in body
    assert "clearing a verification" in body
    assert "final submit" in body
    assert "Got it" in body, "expected a dismiss button labelled plainly, not a bare X"


def test_first_open_card_reuses_existing_card_and_button_classes_not_new_css():
    body = _find_function(_read(REMOTE_JS), "_firstOpenCardHTML")
    assert "admin-card" in body, "must reuse the existing admin-card look"
    assert "memory-toolbar-btn" in body, (
        "the dismiss button must reuse the existing toolbar-button class"
    )


def test_dismiss_helper_persists_to_localstorage_and_removes_the_card():
    body = _find_function(_read(REMOTE_JS), "_dismissFirstOpenCard")
    assert "localStorage.setItem(REMOTE_INTRO_SEEN_KEY" in body
    assert "el.remove()" in body, (
        "dismissing must remove the card from the currently-rendered modal "
        "immediately, not just persist the flag for next time"
    )


def test_ensure_modal_actually_renders_the_first_open_card():
    """Reachability: _firstOpenCardHTML() must be called from the modal
    template, not just exist as unused dead code."""
    src = _read(REMOTE_JS)
    ensure_modal = _find_function(src, "_ensureModalEl")
    assert "_firstOpenCardHTML()" in ensure_modal


def test_wire_binds_the_dismiss_button():
    """Reachability: the dismiss button rendered by _firstOpenCardHTML() must
    actually get a click handler wired in _wire(modal)."""
    body = _find_function(_read(REMOTE_JS), "_wire")
    assert "applicant-remote-first-open-dismiss" in body
    assert "_dismissFirstOpenCard(modal)" in body


def test_first_open_card_never_makes_a_network_call():
    """Purely client-side, like the digest's loop-intro card it mirrors — no
    new proxy route, no new engine call."""
    src = _read(REMOTE_JS)
    fns = "".join([
        _find_function(src, "_isFirstOpenSeen"),
        _find_function(src, "_dismissFirstOpenCard"),
        _find_function(src, "_firstOpenCardHTML"),
    ])
    assert "fetch(" not in fns
    assert "_fetchJSON(" not in fns
    assert "_post(" not in fns


# ── white-label guard (project-wide convention) ─────────────────────────────


def test_no_codename_or_fr_jargon_leaks_into_the_new_copy():
    body = "".join([
        _find_function(_read(REMOTE_JS), "_firstOpenCardHTML"),
    ])
    src = _read(REMOTE_JS)
    m = re.search(r'id="applicant-remote-intro">(.*?)</p>', src, re.DOTALL)
    intro = m.group(1) if m else ""
    combined = body + intro
    assert not re.search(
        r"firehouse|orwell|odysseus|smokey|hermes-agent", combined, re.IGNORECASE,
    )
    assert not re.search(r"\bFR-|\bNFR-", combined)


# ── node --check on the touched file (CI-equivalent front-end syntax gate) ──


def test_node_check_remote_js():
    import shutil
    import subprocess

    if shutil.which("node") is None:
        import pytest
        pytest.skip("node binary not on PATH")
    res = subprocess.run(
        ["node", "--check", str(REMOTE_JS)],
        capture_output=True, text=True, timeout=15,
    )
    assert res.returncode == 0, f"node --check failed for {REMOTE_JS.name}:\n{res.stderr}"
