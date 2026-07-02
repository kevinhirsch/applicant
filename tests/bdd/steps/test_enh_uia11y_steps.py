"""Step bindings for the deep-accessibility UI-hardening specs (theme UI-A11Y).

Issues #379, #380, #382, #385, #388, #393, #394.

Convention (mirrors ``test_enh_t08_frontend_steps.py`` / ``test_enh_research_steps.py``):

* Scenarios with NO ``@pending`` tag are REAL regression coverage for an accessibility
  pattern that ALREADY ships on this branch as a safe sibling (the email-digest dialog's
  focus + Escape handling, the wizard/memory dialog role contract, the Tone label's
  ``for=``, the toast dismiss ``aria-label``, the Activity run-control reduced-motion
  guard). They assert against the actual static front-door files and must pass today.
* Scenarios tagged ``@pending`` are TDD acceptance specs for the residual gap — the same
  a11y attribute/handler being ABSENT on the other overlays/controls. Their steps make an
  honest probe by reading the cited file and asserting the missing pattern is present, so
  the scenario is a genuine red today. ``conftest.pytest_bdd_apply_tag`` maps ``@pending``
  to a non-strict xfail.

No browser is launched and no real socket is opened: every fact is read from the static
HTML / JS / CSS file content via ``pathlib`` (``REPO_ROOT`` derived from this file).
"""

from __future__ import annotations

import pathlib
import re

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios(
    "../features/enhancements/enh_379_modal_focus_management.feature",
    "../features/enhancements/enh_380_modal_focus_trap.feature",
    "../features/enhancements/enh_382_modal_escape_close.feature",
    "../features/enhancements/enh_385_dialog_aria_roles.feature",
    "../features/enhancements/enh_388_orphaned_labels.feature",
    "../features/enhancements/enh_393_glyph_button_aria_label.feature",
    "../features/enhancements/enh_394_pulse_reduced_motion.feature",
)

# Repo root: tests/bdd/steps/<this file> -> parents[3] is the repo root.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
UI_JS = JS_DIR / "ui.js"
DIGEST_JS = JS_DIR / "emailLibrary" / "applicantDigest.js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"
MIND_JS = JS_DIR / "applicantMind.js"

# The overlay modules that the findings say lack focus / Escape / dialog-role handling.
# (applicantDigest.js lives under emailLibrary/ and is the safe sibling, not in scope.)
GAP_OVERLAYS = ("applicantPortal.js", "applicantRemote.js", "applicantVault.js")
FOCUS_GAP_OVERLAYS = GAP_OVERLAYS + ("applicantMind.js",)


@pytest.fixture
def uia11yctx() -> dict:
    return {}


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _has_focus_capture(src: str) -> bool:
    """True if the source captures the active element (to restore later)."""
    return "activeElement" in src


def _has_focus_restore(src: str) -> bool:
    """True if the source restores focus to a saved element on close."""
    return ".focus(" in src


def _has_escape_handler(src: str) -> bool:
    """True if the source closes on the Escape key."""
    return bool(re.search(r"""key\s*===?\s*['"]Escape['"]""", src)) or "keyCode === 27" in src


def _calls_initModalA11y(src: str) -> bool:
    """True if the source calls initModalA11y (the shared a11y helper)."""
    return bool(re.search(r"initModalA11y\s*\(", src))


def _has_dialog_contract(src: str) -> bool:
    """True if the source declares role=dialog + aria-modal=true + an accessible name."""
    role = bool(re.search(r"""role=['"]dialog['"]""", src)) or "'role', 'dialog'" in src
    modal = "aria-modal" in src
    name = "aria-label" in src or "aria-labelledby" in src
    return role and modal and name


# ===========================================================================
# #379 — modal focus management (digest GREEN; Portal/Remote/Vault/Mind gap)
# ===========================================================================
@given("the email digest dialog module")
def given_digest_module(uia11yctx):
    uia11yctx["digest_src"] = _read(DIGEST_JS)


@when("the dialog open path is inspected")
def inspect_digest_open(uia11yctx):
    src = uia11yctx["digest_src"]
    # The digest dialog focuses its close button when it opens.
    uia11yctx["digest_focuses_on_open"] = bool(re.search(r"\b\w+\.focus\(\)", src))


@then("it focuses a control inside the dialog on open")
def digest_focuses_on_open(uia11yctx):
    assert uia11yctx["digest_focuses_on_open"], (
        "the digest dialog should focus a control inside the dialog on open"
    )


@given("the Applicant overlay modules")
def given_overlay_modules(uia11yctx):
    uia11yctx["overlay_src"] = {name: _read(JS_DIR / name) for name in FOCUS_GAP_OVERLAYS}


@when("their open and close paths are inspected for focus management")
def inspect_overlay_focus(uia11yctx):
    # The shared a11y helper in ui.js handles focus capture/restore.
    # Each overlay module calls initModalA11y on open, which saves
    # document.activeElement and restores it on cleanup.
    ui_src = _read(UI_JS)
    uia11yctx["ui_has_focus_capture"] = _has_focus_capture(ui_src)
    uia11yctx["ui_has_focus_restore"] = _has_focus_restore(ui_src)
    uia11yctx["overlay_calls"] = {
        name: _calls_initModalA11y(_read(JS_DIR / name))
        for name in FOCUS_GAP_OVERLAYS
    }


@then("each one captures the active element on open and restores it on close")
def overlays_manage_focus(uia11yctx):
    assert uia11yctx["ui_has_focus_capture"], (
        "ui.js initModalA11y does not capture activeElement"
    )
    assert uia11yctx["ui_has_focus_restore"], (
        "ui.js initModalA11y does not restore focus (.focus call)"
    )
    unwired = [name for name, ok in uia11yctx["overlay_calls"].items() if not ok]
    assert not unwired, (
        f"overlays not calling initModalA11y: {unwired}"
    )


# ===========================================================================
# #380 — focus trap (wizard dialog contract GREEN; Tab-trap gap)
# ===========================================================================
@given("the first-run setup wizard module")
def given_onboarding_module(uia11yctx):
    uia11yctx["onboarding_src"] = _read(ONBOARDING_JS)


@when("the overlay markup is inspected")
def inspect_wizard_markup(uia11yctx):
    uia11yctx["wizard_dialog_contract"] = _has_dialog_contract(uia11yctx["onboarding_src"])


@then("it declares itself a modal dialog with an accessible name")
def wizard_is_dialog(uia11yctx):
    assert uia11yctx["wizard_dialog_contract"], (
        "the setup wizard overlay should declare role=dialog + aria-modal + a name"
    )


@when("the wizard is inspected for a focus-trap handler")
def inspect_wizard_trap(uia11yctx):
    onboarding_src = uia11yctx["onboarding_src"]
    ui_src = _read(UI_JS)
    # The shared helper initModalA11y in ui.js handles Tab/Shift+Tab wrapping
    # by querying focusable elements and wrapping first/last.
    has_tab_keydown = bool(
        re.search(r"addEventListener\(\s*['\"]keydown['\"]", ui_src)
    ) and bool(re.search(r"""key\s*===?\s*['"]Tab['"]|keyCode\s*===?\s*9""", ui_src))
    has_focusables = "querySelectorAll" in ui_src
    uia11yctx["wizard_trap"] = has_tab_keydown and has_focusables
    uia11yctx["wizard_calls_a11y"] = _calls_initModalA11y(onboarding_src)


@then("a keydown handler wraps Tab and Shift+Tab focus within the dialog")
def wizard_traps_tab(uia11yctx):
    assert uia11yctx["wizard_trap"], (
        "ui.js initModalA11y does not trap Tab/Shift+Tab focus — missing keydown+Tab "
        "handler or focusable-element query"
    )
    assert uia11yctx["wizard_calls_a11y"], (
        "applicantOnboarding.js does not call initModalA11y to wire the focus trap"
    )


# ===========================================================================
# #382 — Escape-to-close (digest GREEN; Portal/Vault/Remote/Mind gap)
# ===========================================================================
@when("the dialog key handling is inspected")
def inspect_digest_keys(uia11yctx):
    uia11yctx["digest_escape"] = _has_escape_handler(uia11yctx["digest_src"])


@then("pressing Escape dismisses the dialog")
def digest_escape_closes(uia11yctx):
    assert uia11yctx["digest_escape"], (
        "the digest dialog should close on the Escape key"
    )


@when("their key handling is inspected for an Escape dismiss")
def inspect_overlay_escape(uia11yctx):
    ui_src = _read(UI_JS)
    uia11yctx["ui_has_escape"] = _has_escape_handler(ui_src)
    uia11yctx["escape_bound"] = {
        name: _calls_initModalA11y(_read(JS_DIR / name))
        for name in GAP_OVERLAYS
    }


@then("each dismissible overlay binds an Escape handler that closes it")
def overlays_escape_close(uia11yctx):
    assert uia11yctx["ui_has_escape"], (
        "ui.js initModalA11y does not handle the Escape key"
    )
    missing = [name for name, ok in uia11yctx["escape_bound"].items() if not ok]
    assert not missing, f"overlays not calling initModalA11y (Escape handler): {missing}"


# ===========================================================================
# #385 — dialog ARIA (wizard + mind GREEN; Portal/Remote/Vault gap)
# ===========================================================================
@given("the setup wizard and memory dialog modules")
def given_wizard_and_mind(uia11yctx):
    uia11yctx["wizard_src"] = _read(ONBOARDING_JS)
    uia11yctx["mind_src"] = _read(MIND_JS)


@when("their overlay markup is inspected")
def inspect_green_dialog_contracts(uia11yctx):
    uia11yctx["green_dialog_contracts"] = {
        "applicantOnboarding.js": _has_dialog_contract(uia11yctx["wizard_src"]),
        "applicantMind.js": _has_dialog_contract(uia11yctx["mind_src"]),
    }


@then("each declares role dialog, aria-modal true, and an accessible name")
def green_dialogs_have_contract(uia11yctx):
    missing = [name for name, ok in uia11yctx["green_dialog_contracts"].items() if not ok]
    assert not missing, f"expected dialog contract missing from: {missing}"


@when("their overlay markup is inspected for the dialog contract")
def inspect_gap_dialog_contracts(uia11yctx):
    uia11yctx["gap_dialog_contracts"] = {
        name: _has_dialog_contract(_read(JS_DIR / name)) for name in GAP_OVERLAYS
    }


@then("each declares role dialog, aria-modal true, and an accessible name too")
def gap_dialogs_have_contract(uia11yctx):
    missing = [name for name, ok in uia11yctx["gap_dialog_contracts"].items() if not ok]
    # Today only Onboarding + Mind carry the contract — these are bare divs. Red.
    assert not missing, (
        f"overlays missing role=dialog/aria-modal/accessible name: {missing}"
    )


# ===========================================================================
# #388 — orphaned labels (Tone label GREEN; the rest orphaned)
# ===========================================================================
@given("the front-door page markup")
def given_index_markup(uia11yctx):
    uia11yctx["html"] = _read(INDEX_HTML)


@when("the Tone control label is inspected")
def inspect_tone_label(uia11yctx):
    html = uia11yctx["html"]
    has_for = 'for="applicant-aggr-slider"' in html
    has_control = 'id="applicant-aggr-slider"' in html
    uia11yctx["tone_label_ok"] = has_for and has_control


@then("it associates to its slider via a for attribute that matches the control id")
def tone_label_associated(uia11yctx):
    assert uia11yctx["tone_label_ok"], (
        "the Tone label should associate to applicant-aggr-slider via for/id"
    )


@when("the visible labels are compared to their for-associations")
def compare_labels_for(uia11yctx):
    html = uia11yctx["html"]
    # Visible labels = label elements that wrap or precede a field by id, i.e. the
    # full population of <label ...> tags in the form markup.
    uia11yctx["label_total"] = len(re.findall(r"<label\b", html))
    uia11yctx["label_with_for"] = len(re.findall(r"<label[^>]*\bfor=", html))


@then("every visible label points at a control id rather than sitting orphaned")
def labels_all_associated(uia11yctx):
    total = uia11yctx["label_total"]
    with_for = uia11yctx["label_with_for"]
    # Today ~125 labels exist but only a handful carry for= — genuine red until each
    # visible label is wired to its control.
    assert with_for >= total, (
        f"only {with_for} of {total} visible labels associate to a control via for/id"
    )


# ===========================================================================
# #393 — glyph-only buttons need aria-label (toast GREEN; overlay close gap)
# ===========================================================================
@given("the shared toast helper module")
def given_ui_module(uia11yctx):
    uia11yctx["ui_src"] = _read(UI_JS)


@when("the dismiss button is inspected")
def inspect_toast_dismiss(uia11yctx):
    src = uia11yctx["ui_src"]
    uia11yctx["toast_aria"] = bool(
        re.search(r"""setAttribute\(\s*['"]aria-label['"]""", src)
    )


@then("it sets an explicit aria-label rather than relying on a tooltip")
def toast_has_aria(uia11yctx):
    assert uia11yctx["toast_aria"], (
        "the toast dismiss button should set an explicit aria-label"
    )


@given("the memory dialog module")
def given_mind_module(uia11yctx):
    uia11yctx["mind_src"] = _read(MIND_JS)


@when("its close button is inspected")
def inspect_mind_close(uia11yctx):
    src = uia11yctx["mind_src"]
    # The glyph/close button currently relies on title= only. A fix adds aria-label
    # to the close control. Probe for an aria-label on a close button declaration.
    uia11yctx["mind_close_aria"] = bool(
        re.search(r"<button[^>]*\bclass=[^>]*close[^>]*aria-label=", src, re.I)
        or re.search(r"<button[^>]*aria-label=[^>]*class=[^>]*close", src, re.I)
    )


@then("the glyph-only close button sets an explicit aria-label")
def mind_close_has_aria(uia11yctx):
    # Today the memory dialog close button uses title="Close" with no aria-label — red.
    assert uia11yctx["mind_close_aria"], (
        "the memory dialog close button relies on title= and sets no aria-label"
    )


# ===========================================================================
# #394 — reduced-motion pulse (Activity pulse GREEN; status-strip gap)
# ===========================================================================
@given("the front-door stylesheet")
def given_stylesheet(uia11yctx):
    uia11yctx["css"] = _read(STYLE_CSS)


def _reduced_motion_disables(css: str, animation_token: str) -> bool:
    """True if a prefers-reduced-motion block disables the named animation."""
    for m in re.finditer(
        r"@media[^{]*prefers-reduced-motion[^{]*reduce[^{]*\{(.*?)\}\s*\}",
        css,
        re.S,
    ):
        block = m.group(1)
        if animation_token in block and re.search(r"animation\s*:\s*none", block):
            return True
    return False


@when("the run-control pulse animation is inspected")
def inspect_runcontrol_pulse(uia11yctx):
    css = uia11yctx["css"]
    # The audit's fix (APPLE_GENIUS_IMPROVEMENTS.md #88) went further than gating
    # the pulse behind prefers-reduced-motion: it deleted the animation entirely
    # (applicantDebug.js's _statusChip renders a plain static dot, no `animation`
    # property at all). A gate would satisfy "disabled under reduced motion"
    # conditionally; deletion satisfies it unconditionally, which is strictly
    # stronger. Assert the token is genuinely gone rather than merely gated.
    uia11yctx["runcontrol_guarded"] = "applicantPulse" not in css


@then("a reduced-motion media query disables it")
def runcontrol_guarded(uia11yctx):
    assert uia11yctx["runcontrol_guarded"], (
        "the Activity run-control pulse should never animate — either gated behind "
        "prefers-reduced-motion, or (as fixed) removed entirely"
    )


@when("the status-strip pulse animation is inspected")
def inspect_statusstrip_pulse(uia11yctx):
    css = uia11yctx["css"]
    # The status-strip dot animates with the applicant-status-pulse keyframes.
    uia11yctx["statusstrip_guarded"] = _reduced_motion_disables(
        css, "applicant-status-pulse"
    ) or _reduced_motion_disables(css, "applicant-status-dot")


@then("a reduced-motion media query disables it too")
def statusstrip_guarded(uia11yctx):
    # Today no reduced-motion guard targets the status-strip pulse — genuine red.
    assert uia11yctx["statusstrip_guarded"], (
        "the status-strip pulse is not disabled under prefers-reduced-motion"
    )
