"""Regression coverage for the §D Onboarding/Settings design-audit fix batch
(items 65-84), confined to ``static/js/applicantOnboarding.js`` and
``static/style.css``.

Follows the convention of ``tests/bdd/steps/test_enh_uia11y_steps.py`` /
``test_applicant_round1_chatmind.py``: every fact is read from the actual
static file content via ``pathlib`` + regex — no browser, no DOM, no real
socket. ``applicantOnboarding.js`` does top-level module-scope work (mutable
module state, a `window.launchApplicantSetup` assignment) and is not a bare
dependency-free leaf the way ``applicantUpdateView.js`` is, so the text/regex
approach is used throughout rather than ``node --input-type=module`` execution.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore via ``git checkout``) per the batch's test-coverage DoD.

Items intentionally NOT covered here:
  * #73, #80, #82 — explicitly required cross-file changes outside this
    batch's ownership (settings.js / index.html); nothing landed in
    applicantOnboarding.js/style.css to regression-test.
  * #65, #72, #79 — verified already-OK / not reproducible; no fix landed.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #66: .settings-select:focus — blue ring, not a bare red border ─────────

def test_settings_select_focus_shows_blue_ring_not_red_border():
    """Focused `.settings-select` fields used to paint a plain red border with
    no ring at all (read as a permanent validation error). The focus state
    must now use the sanctioned system-blue ring (border-color + a soft
    box-shadow halo), and must NOT reference `--red` at all."""
    css = _read(STYLE_CSS)
    m = re.search(r"\.settings-select:focus\s*\{([^}]*)\}", css)
    assert m, "expected a .settings-select:focus rule in style.css"
    block = m.group(1)
    assert re.search(r"border-color:\s*var\(--sys-blue\)", block), (
        "expected the focus border to use the system-blue token"
    )
    assert re.search(r"box-shadow:\s*0\s+0\s+0\s+3px\s+color-mix\(in srgb,\s*var\(--sys-blue\)", block), (
        "expected a soft system-blue focus ring (box-shadow halo)"
    )
    assert "--red" not in block, "focus state must not fall back to --red"


# ── #67: .settings-select — min-height: 44px tap floor ─────────────────────

def test_settings_select_has_44px_min_height():
    """`.settings-select` (used throughout the wizard's forms and Settings)
    was padding:5px 8px with no min-height — well under the 44px tap-target
    floor. The base rule must now set min-height: 44px with border-box sizing
    so the extra height doesn't also inflate the width the padding accounts
    for."""
    css = _read(STYLE_CSS)
    m = re.search(r"(?m)^\.settings-select \{([^}]*)\}", css)
    assert m, "expected the base .settings-select rule in style.css"
    block = m.group(1)
    assert re.search(r"min-height:\s*44px\s*;", block), (
        "expected .settings-select to set min-height: 44px"
    )
    assert re.search(r"box-sizing:\s*border-box\s*;", block), (
        "expected box-sizing: border-box alongside the min-height"
    )


# ── #68/#81: Welcome step flattened into .ao-hairline-group ────────────────

def test_welcome_step_uses_flattened_hairline_group():
    """Welcome used to stack two bordered `.admin-card` boxes ahead of any
    action. `_renderWelcome` must now render a single flattened
    `.ao-hairline-group` containing exactly one Required row and one Optional
    row, each carrying its own step badge — not a re-styled pair of
    `.admin-card` boxes."""
    src = _read(ONBOARDING_JS)
    m = re.search(r"function _renderWelcome\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _renderWelcome"
    body = m.group(1)
    assert "ao-hairline-group" in body, "expected the flattened .ao-hairline-group container"
    assert body.count("ao-hairline-row") == 2, (
        "expected exactly one Required row and one Optional row"
    )
    assert "ao-step-badge-required" in body
    assert "ao-step-badge-optional" in body
    # The group itself must actually render two hairline-separated rows in CSS
    # (border-top on the group + border-bottom on each row), not just be a
    # renamed bordered card.
    css = _read(STYLE_CSS)
    group = re.search(r"#applicant-onboarding-overlay \.ao-hairline-group\s*\{([^}]*)\}", css)
    assert group, "expected a .ao-hairline-group rule in style.css"
    assert re.search(r"border-top:\s*1px solid var\(--border\)", group.group(1))
    row = re.search(r"#applicant-onboarding-overlay \.ao-hairline-row\s*\{([^}]*)\}", css)
    assert row, "expected a .ao-hairline-row rule in style.css"
    assert re.search(r"border-bottom:\s*1px solid var\(--border\)", row.group(1))


def test_welcome_trust_line_is_a_single_positive_statement_not_a_list():
    """Demo-tone pass (supersedes the old #68/#81 test below): the 'what
    Applicant never does' trust list used to be collapsed behind a `<details>`
    disclosure — still a wall of negative "never" statements, just deferred a
    beat. It has been replaced with ONE confident, positive control statement
    (`trustLine`, imported from this same module), rendered directly — a
    single line needs no toggle."""
    src = _read(ONBOARDING_JS)
    m = re.search(r"function _renderWelcome\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _renderWelcome"
    body = m.group(1)
    assert "<details" not in body, (
        "expected the never-do disclosure removed outright, not just relabeled"
    )
    assert "ao-welcome-trust" in body
    assert "trustLine" in body


def test_trust_line_is_exported_and_reads_as_a_positive_control_statement():
    src = _read(ONBOARDING_JS)
    m = re.search(r"export const trustLine = '([^']+)';", src)
    assert m, "expected an exported trustLine constant"
    line = m.group(1)
    assert "never" not in line.lower(), "expected no negative-capability framing"
    assert "you" in line.lower() and "control" in line.lower()


# ── #69: Nav + footer merged into one .ao-actionbar ─────────────────────────

def test_nav_and_foot_share_one_actionbar_row():
    """Back/Skip and the step's own primary action used to be two stacked
    full-width rows. `_buildOverlay` must now emit ONE `.ao-actionbar`
    container wrapping both `#ao-nav` (secondary actions) and `#ao-foot`
    (primary action) as siblings, not two separately-bordered rows."""
    src = _read(ONBOARDING_JS)
    m = re.search(r"function _buildOverlay\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _buildOverlay"
    body = m.group(1)
    bar = re.search(
        r'<div class="ao-actionbar" id="ao-actionbar">\s*'
        r'<div class="ao-nav" id="ao-nav"></div>\s*'
        r'<div class="ao-foot" id="ao-foot"></div>\s*'
        r'</div>',
        body,
    )
    assert bar, "expected ao-nav and ao-foot to be siblings inside a single .ao-actionbar"

    css = _read(STYLE_CSS)
    actionbar = re.search(r"#applicant-onboarding-overlay \.ao-actionbar\s*\{([^}]*)\}", css)
    assert actionbar, "expected a .ao-actionbar rule in style.css"
    block = actionbar.group(1)
    assert "border-top" in block, "the merged bar carries the single hairline separator"
    # The nav/foot sub-rules must NOT carry their own border (no more double
    # border/two competing rows).
    nav_rule = re.search(r"#applicant-onboarding-overlay \.ao-nav\s*\{([^}]*)\}", css)
    foot_rule = re.search(r"#applicant-onboarding-overlay \.ao-foot\s*\{([^}]*)\}", css)
    assert nav_rule and "border: none" in nav_rule.group(1)
    assert foot_rule and "border: none" in foot_rule.group(1)


# ── #70: admin-empty "None" state no longer falls to --red ─────────────────

def test_endpoint_list_empty_state_does_not_fall_through_to_red():
    """The endpoint-list empty state ('No endpoints configured' / 'None')
    used to reference `--accent-primary`/`--accent` tokens that are never
    actually set, which fell through to `--red` — a plain informational
    'None yet' painted as an error. The scoped override must use the same
    muted secondary-label tone as the base `.admin-empty` rule, never red."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"#adm-epList-local \.admin-empty,\s*#adm-epList-api \.admin-empty\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected a scoped #adm-epList-local/#adm-epList-api .admin-empty override"
    block = m.group(1)
    assert "--red" not in block, "empty state must not fall back to --red"
    assert "--accent-primary" not in block and "--accent)" not in block, (
        "must not reference the unset accent tokens that previously fell through to red"
    )
    assert re.search(r"color:\s*color-mix\(in srgb,\s*var\(--fg\)\s*58%", block), (
        "expected the same muted secondary-label tone as the base .admin-empty rule"
    )


# ── #71: "ADMIN" label uppercase transform removed ──────────────────────────

def test_settings_sidebar_admin_label_is_not_force_uppercased():
    """The markup already spells the section label title-case ('Admin'); the
    `.settings-sidebar-label` rule was force-uppercasing it to 'ADMIN' via
    `text-transform: uppercase`. That transform must be gone (the small/quiet
    caption sizing/opacity treatment stays)."""
    css = _read(STYLE_CSS)
    m = re.search(r"(?m)^\.settings-sidebar-label \{([^}]*)\}", css)
    assert m, "expected the base .settings-sidebar-label rule in style.css"
    block = m.group(1)
    assert "text-transform" not in block, (
        "expected text-transform to be removed from .settings-sidebar-label"
    )
    # Sanity: the rest of the quiet-caption treatment is still intact.
    assert re.search(r"opacity:\s*0\.5\s*;", block)


# ── #74: mobile stepper .ao-rail-compact "Step N of M" line ────────────────

def test_rail_compact_line_renders_step_n_of_m_and_is_mobile_only():
    """On a narrow phone the 3-item tab strip could truncate a step title.
    `.ao-rail-compact` must render a single always-legible 'Step N of M ·
    Title' line, and CSS must show it ONLY at <=480px while hiding the
    normal tab strip there."""
    src = _read(ONBOARDING_JS)
    m = re.search(r"function _renderRail\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _renderRail"
    body = m.group(1)
    compact = re.search(
        r'ao-rail-compact.*?Step \$\{_stepIndex \+ 1\} of \$\{STEPS\.length\} · \$\{esc\(cur\.title\)\}',
        body,
    )
    assert compact, "expected the ao-rail-compact span to render 'Step N of M · Title'"

    css = _read(STYLE_CSS)
    base = re.search(r"#applicant-onboarding-overlay \.ao-rail-compact\s*\{([^}]*)\}", css)
    assert base, "expected a base .ao-rail-compact rule"
    assert re.search(r"display:\s*none\s*;", base.group(1)), (
        "expected .ao-rail-compact to be hidden by default"
    )
    media = re.search(
        r"@media \(max-width:\s*480px\)\s*\{([^@]*?#applicant-onboarding-overlay \.ao-rail-compact[^}]*\}[^}]*\})",
        css,
        re.S,
    )
    assert media, "expected a max-width:480px media query touching .ao-rail-compact"
    media_block = media.group(1)
    assert re.search(r"\.ao-rail-compact\s*\{[^}]*display:\s*block", media_block), (
        "expected .ao-rail-compact to switch to display:block under 480px"
    )
    assert re.search(r"\.ao-rail-step\s*\{[^}]*display:\s*none", media_block), (
        "expected the normal tab strip (.ao-rail-step) hidden under 480px"
    )


# ── #75: .admin-tab steps get aria-disabled="true" ──────────────────────────

def test_rail_steps_carry_aria_disabled():
    """The step rail reuses `.admin-tab`, but these are progress indicators,
    not clickable tabs (no click handler). Each rendered step span must carry
    `aria-disabled="true"` so assistive tech doesn't read them as actionable."""
    src = _read(ONBOARDING_JS)
    m = re.search(r"function _renderRail\(\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _renderRail"
    body = m.group(1)
    step_tpl = re.search(r"const steps = STEPS\.map\(\(step, i\) => \{(.*?)\}\)\.join", body, re.S)
    assert step_tpl, "expected the per-step template inside _renderRail"
    assert 'aria-disabled="true"' in step_tpl.group(1), (
        "expected each rendered step span to carry aria-disabled=\"true\""
    )


# ── #76: STEPS[].required drives Required/Optional badge rendering ─────────

def test_steps_required_flag_drives_rail_and_welcome_badges():
    """Only the 'Connect a model' step is `required: true` in the STEPS data
    array; the rail badge and Welcome's badge pair must be driven from that
    flag, not hardcoded per-step markup."""
    src = _read(ONBOARDING_JS)
    steps_block = re.search(r"const STEPS = \[(.*?)\n\];", src, re.S)
    assert steps_block, "expected to find the STEPS array"
    block = steps_block.group(1)
    # Exactly one step ENTRY declares required: true (ignore the explanatory
    # comment above the array, which also contains the literal text).
    assert block.count("required: true,") == 1, (
        "expected exactly one STEPS entry to declare required: true"
    )
    assert re.search(r"key:\s*'llm'.*?required:\s*true", block, re.S), (
        "expected the 'llm' (Connect a model) step to be the required one"
    )
    # The rail renders the badge conditionally off step.required.
    assert "step.required ? ' <span class=\"ao-rail-req\">Required</span>' : ''" in src, (
        "expected the rail badge to be driven by step.required"
    )


# ── #77: secondary buttons get a quieter 36px borderless treatment ─────────

def test_secondary_buttons_are_36px_borderless_in_the_wizard():
    """Secondary actions (Back/Skip/etc.) used to match the primary CTA's
    44px pill size and sat directly adjacent to it, competing for attention.
    Inside the wizard, any `.cal-btn` that is NOT `.cal-btn-primary` must be
    quieted to 36px with a transparent border."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"#applicant-onboarding-overlay \.cal-btn:not\(\.cal-btn-primary\)\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected a scoped .cal-btn:not(.cal-btn-primary) rule"
    block = m.group(1)
    assert re.search(r"min-height:\s*36px\s*;", block), "expected the quieter 36px height"
    assert re.search(r"border-color:\s*transparent\s*;", block), "expected a borderless treatment"


# ── #78: ?-help popover uses real --panel/--fg tokens, not #20232a ─────────

def test_help_popover_uses_panel_and_fg_tokens_not_hardcoded_hex():
    """The `?` help popover bubble hardcoded `#20232a` (and other dark
    literals) regardless of theme — a light theme got a near-black tooltip.
    It must now use the real theme tokens `--panel`/`--fg`, and the
    hardcoded hex must be gone from the popover rule."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"#applicant-onboarding-overlay \.ao-tip:hover::after,\s*"
        r"#applicant-onboarding-overlay \.ao-tip:focus::after\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected the .ao-tip hover/focus popover rule"
    block = m.group(1)
    assert "#20232a" not in block, "hardcoded #20232a must be gone from the popover rule"
    assert re.search(r"background:\s*var\(--panel\)\s*;", block), (
        "expected the popover background to use the --panel token"
    )
    assert re.search(r"color:\s*var\(--fg\)\s*;", block), (
        "expected the popover text color to use the --fg token"
    )


# ── #83: sub-progress text reworded to avoid double-counting steps ─────────

def test_intake_subprogress_uses_section_wording_not_step():
    """The resumable intake's own sub-progress line used to read as a second,
    conflicting 'step N of M' counter next to the rail's own 'Step N of 3'.
    `_intakeProgressHTML` must word it as a 'section' count instead."""
    src = _read(ONBOARDING_JS)
    m = re.search(r"function _intakeProgressHTML\(total\)\s*\{(.*?)\n\}", src, re.S)
    assert m, "expected to find _intakeProgressHTML"
    body = m.group(1)
    assert "section ${_intakeIndex + 1} of ${total}" in body, (
        "expected the sub-progress line to count sections"
    )
    assert re.search(r"[Ss]tep \$\{", body) is None, (
        "sub-progress line must not word its own count as 'Step N' "
        "(that would double-count against the rail's own Step N of 3)"
    )


# ── #84: content column capped at 560px, centered ──────────────────────────

def test_wizard_body_column_capped_and_centered():
    """The step BODY must read as a single calm column (max-width: 560px,
    centered) rather than every row/card stretching edge-to-edge across the
    full 640px sheet width."""
    css = _read(STYLE_CSS)
    m = re.search(r"#applicant-onboarding-overlay #ao-body\s*\{([^}]*)\}", css)
    assert m, "expected a #applicant-onboarding-overlay #ao-body rule"
    block = m.group(1)
    assert re.search(r"max-width:\s*560px\s*;", block), "expected the body column capped at 560px"
    assert re.search(r"margin:\s*0 auto\s*;", block), "expected the body column to be centered"
