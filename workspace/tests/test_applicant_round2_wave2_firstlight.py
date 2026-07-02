"""Regression coverage for round 2, wave 2's "first-light payoff" fix
(Top-25 #17 / §7 item 3 in ``docs/design/audits/PRODUCT_EXHAUSTIVE_AUDIT.md``),
confined to ``static/js/applicantOnboarding.js``.

Follows the convention of ``test_applicant_round1_onboarding.py``: every fact is
read from the actual static file content via ``pathlib`` + regex — no browser,
no DOM, no real socket. Each assertion here was verified, by hand, to actually
go red when the underlying fix is reverted (temporarily re-apply the pre-fix
source, rerun, see the assertion fail, restore) per this batch's DoD.

What the fix does: on genuine OOBE completion (the "You're all set!" finish
screen — llm_configured, nothing left gating it), the wizard now hands off to
the Portal home base with a short toast instead of leaving the user on the bare
chat shell. The engine's always-on scheduler already starts discovery on its own
cadence once campaign criteria are ready (see agent_loop.py / lifespan.py — no
front-door change needed there); this fix only makes that visible.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _find_function(src: str, name: str) -> str:
    """Extract a top-level `function name(...) { ... }` body via brace counting
    (regex alone can't balance nested braces reliably in this file)."""
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


# ── module state: the completion flag ───────────────────────────────────────


def test_just_completed_setup_flag_declared_and_initialized_false():
    """A module-level flag must exist to let _dismiss() distinguish a genuine
    finish from an Escape/cancel out of a still-incomplete wizard. It must start
    false so a fresh page load never opens the Portal unprompted."""
    src = _read(ONBOARDING_JS)
    assert re.search(r"let _justCompletedSetup\s*=\s*false\s*;", src), (
        "expected a module-level `let _justCompletedSetup = false;` flag"
    )


# ── _finish(): the flag is set ONLY on the genuine "You're all set!" screen ──


def test_finish_sets_completed_flag_on_ready_screen_only():
    """`_finish()` has two branches: the genuine "You're all set!" screen (no
    missing gating requirements) and the "Almost there" screen (still missing
    e.g. connect-a-model). Only the former is a real OOBE completion — the flag
    must be set in that branch, and must NOT appear in the "Almost there"
    branch (setting it there would open the Portal before setup is actually
    done)."""
    src = _read(ONBOARDING_JS)
    finish_body = _find_function(src, "_finish")

    ready_marker = "You’re all set!"
    almost_marker = "Almost there"
    ready_idx = finish_body.find(ready_marker)
    almost_idx = finish_body.find(almost_marker)
    assert ready_idx != -1, "expected the 'You're all set!' ready screen in _finish()"
    assert almost_idx != -1, "expected the 'Almost there' screen in _finish()"
    assert ready_idx < almost_idx, "expected the ready screen to come before the Almost-there screen"

    ready_branch = finish_body[ready_idx:almost_idx]
    assert "_justCompletedSetup = true;" in ready_branch, (
        "expected _finish() to set _justCompletedSetup = true on the genuine finish screen"
    )

    almost_branch = finish_body[almost_idx:]
    assert "_justCompletedSetup = true" not in almost_branch, (
        "the still-incomplete 'Almost there' screen must never set _justCompletedSetup"
    )

    # The flag must be set before the Get-started button is wired, not after —
    # otherwise a very fast click could race a dismiss that reads the flag too
    # early (defence in depth; also just correct ordering).
    onclick_idx = ready_branch.index("document.getElementById('ao-finish').onclick = _dismiss;")
    flag_idx = ready_branch.index("_justCompletedSetup = true;")
    assert flag_idx < onclick_idx, (
        "expected _justCompletedSetup to be set before the Get-started handler is wired"
    )


# ── _dismiss(): consumes the flag exactly once and hands off ───────────────


def test_dismiss_consumes_flag_and_resets_it():
    """_dismiss() must read _justCompletedSetup into a local BEFORE tearing down
    / navigating, then reset the module flag back to false unconditionally —
    otherwise a later, unrelated Escape-close (e.g. from a Settings-launched
    re-run of a step) could incorrectly re-trigger the home-base hand-off."""
    src = _read(ONBOARDING_JS)
    dismiss_body = _find_function(src, "_dismiss")
    assert re.search(r"const justCompleted\s*=\s*_justCompletedSetup\s*;", dismiss_body), (
        "expected _dismiss() to capture _justCompletedSetup into a local"
    )
    assert re.search(r"_justCompletedSetup\s*=\s*false\s*;", dismiss_body), (
        "expected _dismiss() to reset _justCompletedSetup back to false"
    )
    # The reset must happen unconditionally (not nested inside the refresh-hook
    # branch) so it also fires on the defensive reload fallback.
    reset_idx = dismiss_body.index("_justCompletedSetup = false;")
    refresh_idx = dismiss_body.index("window.refreshApplicantFeatures")
    assert reset_idx < refresh_idx, (
        "expected the flag reset to happen before the refresh/reload branching, "
        "so it is unconditional"
    )


def test_dismiss_opens_home_base_only_when_justcompleted_and_refresh_succeeds():
    """The hand-off call must be gated on `justCompleted` and must live inside
    the `window.refreshApplicantFeatures` success path — a reload would wipe
    any Portal opened before it, so the fix must not call the hand-off ahead of
    that fallback's `window.location.reload()`."""
    src = _read(ONBOARDING_JS)
    dismiss_body = _find_function(src, "_dismiss")

    m = re.search(
        r"if\s*\(justCompleted\)\s*_openHomeBaseAfterSetup\(\)\s*;",
        dismiss_body,
    )
    assert m, "expected `if (justCompleted) _openHomeBaseAfterSetup();` in _dismiss()"

    call_idx = m.start()
    refresh_call_idx = dismiss_body.index("window.refreshApplicantFeatures();")
    reload_idx = dismiss_body.index("window.location.reload();")
    assert refresh_call_idx < call_idx < reload_idx, (
        "expected the home-base hand-off to sit between the refreshApplicantFeatures() "
        "call and the reload() fallback, i.e. only on the success path"
    )


# ── _openHomeBaseAfterSetup(): uses the established Portal launcher + toast ─


def test_open_home_base_helper_exists_and_is_never_a_hard_navigation():
    """The hand-off must reuse the already-established `openApplicantPortal`
    launcher (via the `window.applicantPortalModule` exposure pattern used
    elsewhere in this codebase, e.g. applicantChat.js), not a hand-rolled
    `window.location` redirect to some /portal route — that would be a jarring
    hard navigation, not the natural in-page hand-off the audit calls for."""
    src = _read(ONBOARDING_JS)
    helper_body = _find_function(src, "_openHomeBaseAfterSetup")
    assert re.search(
        r"window\.applicantPortalModule\s*&&\s*typeof\s+window\.applicantPortalModule\.openApplicantPortal\s*===\s*'function'",
        helper_body,
    ), "expected a guarded call through window.applicantPortalModule.openApplicantPortal"
    assert "openApplicantPortal()" in helper_body
    assert "window.location.href" not in helper_body
    assert "window.location.assign" not in helper_body


def test_open_home_base_shows_a_soft_handoff_toast_not_silent():
    """A silent auto-navigation would be jarring per the task brief; the fix
    must show a toast in the same "you're set, here's what's next" voice as the
    rest of the wizard's finish copy, using the established showToast/_toast
    helpers (not a bespoke banner)."""
    src = _read(ONBOARDING_JS)
    helper_body = _find_function(src, "_openHomeBaseAfterSetup")
    assert "showToast" in helper_body, "expected the helper to call showToast"
    assert "_toast(" in helper_body, "expected a _toast(...) fallback when uiModule is unavailable"
    # The toast message should be an honest "all set" hand-off line, matching
    # the finish screen's own "You're all set!" wording rather than diverging
    # copy, and should read naturally rather than as a bare command.
    assert "all set" in helper_body.lower()
    assert "home base" in helper_body.lower()
    # Give the user a real window to notice/act on it (not the default ~1.2s).
    assert re.search(r"duration:\s*[3-9]\d{3}", helper_body), (
        "expected a multi-second toast duration, not the terse default"
    )


def test_open_home_base_helper_never_throws_when_globals_missing():
    """Both the toast and the Portal-open calls must be defensively wrapped —
    a missing/broken ui.js or applicantPortal.js module must never leave the
    user stuck mid-dismiss (the wizard overlay is already torn down by the time
    this runs)."""
    src = _read(ONBOARDING_JS)
    helper_body = _find_function(src, "_openHomeBaseAfterSetup")
    # Expect two independent try/catch guards: one around the toast, one around
    # the Portal-open call, so a failure in one never skips the other.
    try_blocks = re.findall(r"try\s*\{.*?\}\s*catch", helper_body, re.S)
    assert len(try_blocks) >= 2, (
        "expected the toast and the Portal-open call to each be independently try/catch-guarded"
    )
