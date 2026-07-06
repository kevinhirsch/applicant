"""Regression coverage for the §F/§G Vault/Remote/Gallery design-audit fix
batch (items 104-121, plus §G's native-gallery items 137-138), confined to
``static/js/applicantVault.js``, ``static/js/applicantRemote.js`` and
``static/js/applicantGallery.js`` (+ the CSS/markup facts they depend on in
``static/style.css`` and ``static/index.html``).

Follows the convention of ``tests/bdd/steps/test_enh_uia11y_steps.py`` and
its sibling ``test_applicant_round1_chatmind.py``: every fact is read from
the actual static file content via ``pathlib`` + regex — no browser, no DOM,
no real socket. All three modules do top-level ``document``/``window`` work
on import (they wire launchers / assign global seams outside any function),
so they are not importable under a bare ``node --input-type=module`` the way
a dependency-free leaf module (like ``applicantUpdateView.js``) is — hence
the text/regex approach throughout.

Each assertion here was verified, by hand, to actually go red when the
underlying fix is reverted (revert source -> rerun -> see the assertion
fail -> restore via ``git checkout``) per the batch's test-coverage DoD.

Item #115 is intentionally NOT covered here — confirmed not reproducible /
no such notice exists in the current code, so there is nothing to
regression-test.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
STYLE_CSS = REPO_ROOT / "workspace" / "static" / "style.css"
INDEX_HTML = REPO_ROOT / "workspace" / "static" / "index.html"
VAULT_JS = JS_DIR / "applicantVault.js"
REMOTE_JS = JS_DIR / "applicantRemote.js"
GALLERY_JS = JS_DIR / "applicantGallery.js"
# Pass 2a (later than this batch): rail-applicant-gallery / tool-applicant-
# gallery-btn moved out of index.html into applicantNav.js's single-source
# NAV array.
NAV_JS = JS_DIR / "applicantNav.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# Vault (#104-109)
# ═══════════════════════════════════════════════════════════════════════════

def test_vault_modal_has_neutral_hairline_border_not_shared_teal_border():
    """#104: the Vault sheet must be edged by a neutral fg-mix hairline, not
    the shared (teal-hued) `--border` stroke every other modal carries."""
    css = _read(STYLE_CSS)
    m = re.search(r"#applicant-vault-modal\s+\.modal-content\s*\{([^}]*)\}", css)
    assert m, "expected a #applicant-vault-modal .modal-content rule in style.css"
    block = m.group(1)
    assert re.search(r"border-color:\s*color-mix\(in srgb,\s*var\(--fg\)\s*14%,\s*transparent\)", block), (
        f"expected a neutral color-mix(var(--fg)...) hairline border-color, got: {block!r}"
    )
    # It must NOT simply reuse the shared teal --border token.
    assert "border-color: var(--border)" not in block.replace(" ", "")


def test_vault_pinned_opaque_under_frosted_glass_tier():
    """#106: the credential sheet must stay one fully opaque plane under the
    frosted glass tier — never letting whatever's behind it show through."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"body\.theme-frosted\s+#applicant-vault-modal\s+\.modal-content\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected a body.theme-frosted #applicant-vault-modal .modal-content override"
    block = m.group(1)
    assert re.search(r"background-color:\s*var\(--panel\)\s*!important", block)
    assert re.search(r"backdrop-filter:\s*none\s*!important", block)
    assert re.search(r"-webkit-backdrop-filter:\s*none\s*!important", block)


def test_vault_save_buttons_start_neutral_and_promotion_is_wired():
    """#105: all three "Save …" buttons must start neutral (no hardcoded
    `cal-btn-primary`) and `_wireSaveProminence` must promote exactly the
    section being typed into (and demote the other two) via a shared
    `_SAVE_GROUPS` table, wired from `_wire()`."""
    src = _read(VAULT_JS)

    for save_id in (
        "applicant-vault-google-save",
        "applicant-vault-default-save",
        "applicant-vault-save",
    ):
        m = re.search(r'id="' + re.escape(save_id) + r'"\s+class="([^"]*)"', src)
        assert m, f"expected to find the {save_id} button markup"
        assert "cal-btn-primary" not in m.group(1), (
            f"{save_id} must not hardcode cal-btn-primary — exactly one save "
            "button should look prominent at a time, based on user input"
        )

    assert re.search(r"function _wireSaveProminence\s*\(", src), (
        "expected a _wireSaveProminence function"
    )
    assert re.search(r"_wireSaveProminence\(modal\);", src), (
        "_wireSaveProminence must be called from _wire()"
    )
    assert re.search(
        r"btn\.classList\.toggle\('cal-btn-primary',\s*g\.save\s*===\s*activeSaveId\)",
        src,
    ), "expected _promoteSaveGroup to toggle cal-btn-primary per-group, demoting the others"

    # The wiring table must actually target the three real save buttons.
    group_block = re.search(r"const _SAVE_GROUPS = \[(.*?)\];", src, re.S)
    assert group_block, "expected a _SAVE_GROUPS table"
    for save_id in (
        "applicant-vault-google-save",
        "applicant-vault-default-save",
        "applicant-vault-save",
    ):
        assert save_id in group_block.group(1), f"_SAVE_GROUPS must include {save_id}"


def test_vault_credential_fields_use_neutral_applicant_field_class():
    """#108: every credential text/password input must use the plain neutral
    `.applicant-field` class, not `.settings-select` (dropdown/picker
    chrome) — a password field should never look like a <select>."""
    src = _read(VAULT_JS)
    field_ids = (
        "applicant-vault-google-username",
        "applicant-vault-google-secret",
        "applicant-vault-default-username",
        "applicant-vault-default-secret",
        "applicant-vault-tenant",
        "applicant-vault-username",
        "applicant-vault-secret",
    )
    for fid in field_ids:
        m = re.search(r'id="' + re.escape(fid) + r'"\s+class="([^"]*)"', src)
        assert m, f"expected to find the {fid} input markup"
        assert m.group(1) == "applicant-field", (
            f"{fid} must use class=\"applicant-field\", got {m.group(1)!r}"
        )
    assert "settings-select" not in src, (
        "the Vault modal must not use .settings-select chrome for any credential field"
    )


def test_vault_trust_payoff_section_leads_with_live_count_badge():
    """#109: the "sites with a saved sign-in" trust-payoff card (which shows
    a live count) must be the FIRST section in the modal body, ahead of the
    Google / default-account and per-site forms — not trailing them."""
    src = _read(VAULT_JS)
    count_idx = src.index('id="applicant-vault-count"')
    trust_heading_idx = src.index("Sites with a saved sign-in")
    account_heading_idx = src.index("Account sign-ins (used everywhere)")
    # copy/voice (02) audit #227: this heading was renamed "A specific site
    # sign-in" -> "Sign-in for a specific site"; only the anchor string used
    # for ordering below changed, not the assertion's intent.
    site_heading_idx = src.index("Sign-in for a specific site")

    assert trust_heading_idx < account_heading_idx < site_heading_idx, (
        "the trust-payoff ('Sites with a saved sign-in') section must lead, "
        "ahead of the account and per-site forms"
    )
    # The live count badge lives inside that same leading heading.
    assert trust_heading_idx < count_idx < account_heading_idx, (
        "the live count badge must sit inside the leading trust-payoff heading"
    )
    # And it must actually be live — populated from the fetched tenant count.
    assert re.search(r"function _setVaultCount\(n\)", src)
    assert "_setVaultCount(tenants.length)" in src


# ═══════════════════════════════════════════════════════════════════════════
# Remote (#110-114, #116)
# ═══════════════════════════════════════════════════════════════════════════

def test_remote_finish_card_has_no_custom_colored_border():
    """#110: the "Finish the application" card must not carry a custom blue
    border — it should read like every other neutral `.admin-card`."""
    src = _read(REMOTE_JS)
    # Heading level updated to <h5> by the a11y-deep audit's heading-hierarchy
    # fix (#56 in exhaustive2/05_a11y_deep.md): this h3 used to outrank the
    # dialog's own <h4> title — the border-color assertion below is unaffected.
    m = re.search(
        r'<div class="admin-card" style="([^"]*)">\s*<h5[^>]*>Finish the application</h5>',
        src,
    )
    assert m, 'expected to find the "Finish the application" admin-card markup'
    style_attr = m.group(1)
    assert "border-color" not in style_attr, (
        f'the "Finish the application" card must not set a custom border-color, got: {style_attr!r}'
    )
    assert "#5b8def" not in style_attr and "accent-color" not in style_attr


def test_remote_takeover_button_demoted_to_plain_cal_btn():
    """#111: "Take control" must be a plain `.cal-btn`, not a styled
    `.cal-btn-primary` — it's one of several actions, not THE primary CTA."""
    src = _read(REMOTE_JS)
    m = re.search(r'id="applicant-remote-takeover"\s+class="([^"]*)"', src)
    assert m, "expected to find the Take control button markup"
    assert m.group(1) == "cal-btn", (
        f'"Take control" must render class="cal-btn" only, got {m.group(1)!r}'
    )


def test_remote_authorize_button_carries_full_destructive_weight():
    """#112 — THE SAFETY-CRITICAL FIX: "Authorize the assistant to finish"
    (the control that lets the engine click the employer's real final-submit
    button) must render as a FULLY FILLED system-red plate — not the calmer
    shared outline `.cal-btn-danger` used for routine deletes elsewhere.

    This asserts BOTH halves of the fix, because either alone is not enough:
      1. the JS markup carries the `cal-btn-danger` class on the authorize
         button (id-scoped, so the override below can target it), and
      2. style.css defines an ID-scoped override that gives THIS button (and
         only this button) a filled red background — while leaving the
         shared/generic `.cal-btn-danger` rule (used by routine deletes like
         the calendar's "Delete") untouched as a calmer outline style.
    """
    src = _read(REMOTE_JS)
    btn_m = re.search(r'id="applicant-remote-authorize"\s+class="([^"]*)"', src)
    assert btn_m, "expected to find the authorize button markup"
    classes = btn_m.group(1).split()
    assert "cal-btn" in classes and "cal-btn-danger" in classes, (
        f'authorize button must carry class="cal-btn cal-btn-danger", got {btn_m.group(1)!r}'
    )

    css = _read(STYLE_CSS)

    # The GENERIC shared .cal-btn-danger rule must stay a calm OUTLINE style
    # (transparent fill) — this is what routine deletes elsewhere still get.
    generic_m = re.search(
        r"button\.cal-btn\.cal-btn-danger\s*\{([^}]*)\}", css,
    )
    assert generic_m, "expected the generic button.cal-btn.cal-btn-danger rule to still exist"
    assert re.search(r"background:\s*transparent", generic_m.group(1)), (
        "the shared/generic .cal-btn-danger rule must remain an outline style "
        "(transparent background) for routine deletes elsewhere"
    )

    # The ID-SCOPED override on THIS ONE button must be a filled, full-weight
    # system-red plate.
    scoped_m = re.search(
        r"#applicant-remote-authorize\.cal-btn-danger\s*\{([^}]*)\}", css,
    )
    assert scoped_m, (
        "expected an ID-scoped #applicant-remote-authorize.cal-btn-danger override "
        "in style.css giving this one button full destructive weight"
    )
    scoped_block = scoped_m.group(1)
    assert re.search(r"background:\s*var\(--sys-red\)\s*;", scoped_block), (
        f"authorize button must have a filled var(--sys-red) background, got: {scoped_block!r}"
    )
    assert re.search(r"color:\s*#fff\s*;", scoped_block), (
        "authorize button text must be white against the filled red plate"
    )
    assert re.search(r"border-color:\s*var\(--sys-red\)\s*;", scoped_block)

    # A hover state that stays filled (darker red), not fading to transparent.
    hover_m = re.search(
        r"#applicant-remote-authorize\.cal-btn-danger:hover\s*\{([^}]*)\}", css,
    )
    assert hover_m, "expected a :hover state for the authorize button"
    assert re.search(r"background:\s*color-mix\(in srgb,\s*var\(--sys-red\)", hover_m.group(1)), (
        "hover state must stay a filled (darkened) red, not go transparent"
    )

    # Sanity: the sibling "I'll submit it myself" control must NOT carry the
    # danger styling — only the irreversible engine-authorize action does.
    self_m = re.search(r'id="applicant-remote-submit-self"\s+class="([^"]*)"', src)
    assert self_m, "expected to find the submit-self button markup"
    assert "cal-btn-danger" not in self_m.group(1), (
        '"I\'ll submit it myself" must not carry destructive styling — only '
        "the engine-authorize action does"
    )


def test_remote_decision_pair_has_explicit_or_divider():
    """#113: the decision pair ("I'll submit it myself" vs. "Authorize the
    assistant to finish") must have an explicit "or" divider between them,
    so the two options read as alternatives, not a task list."""
    src = _read(REMOTE_JS)
    m = re.search(
        r'id="applicant-remote-submit-self".*?'
        r'aria-hidden="true"[^>]*>\s*or\s*<.*?'
        r'id="applicant-remote-authorize"',
        src,
        re.S,
    )
    assert m, (
        'expected an aria-hidden "or" divider sitting between the '
        "submit-self and authorize buttons"
    )


def test_remote_live_frame_has_neutral_inset_border():
    """#114: the live-session iframe wrapper must carry a neutral inset
    hairline (fg-mix), not the previous colored `--border-color` outline."""
    src = _read(REMOTE_JS)
    m = re.search(
        r'id="applicant-remote-frame-wrap"\s*\n\s*style="([^"]*)"', src,
    )
    assert m, "expected to find the live-frame wrapper markup"
    style_attr = m.group(1)
    assert "border-color" not in style_attr and "var(--border-color" not in style_attr, (
        f"live-frame wrapper must not use a colored border, got: {style_attr!r}"
    )
    assert re.search(
        r"box-shadow:\s*inset 0 0 0 1px color-mix\(in srgb,\s*var\(--fg\)\s*10%,\s*transparent\)",
        style_attr,
    ), f"expected a neutral inset box-shadow border, got: {style_attr!r}"


def test_remote_dormant_desktop_card_collapses_when_unavailable():
    """#116: while the desktop-help feature is dormant (not baked into the
    sandbox image), the card must collapse to a single disabled row — hiding
    its descriptive paragraph and tightening its padding — so it doesn't
    push the irreversible "Finish the application" action further down."""
    src = _read(REMOTE_JS)
    fn_m = re.search(
        r"function _renderDesktopAssist\(\)\s*\{(.*?)\n\}\n", src, re.S,
    )
    assert fn_m, "expected to find _renderDesktopAssist"
    body = fn_m.group(1)

    unavailable_m = re.search(r"if \(!available\)\s*\{(.*?)\n\s*return;\n\s*\}", body, re.S)
    assert unavailable_m, "expected an `if (!available) { ... return; }` branch"
    unavailable_block = unavailable_m.group(1)
    assert "desc.style.display = 'none';" in unavailable_block, (
        "the descriptive paragraph must be hidden while dormant"
    )
    assert re.search(r"card\.style\.paddingTop = '8px'", unavailable_block), (
        "the card must tighten its padding while dormant/collapsed"
    )

    # Outside that branch (the available/interactive path), both must be
    # restored — otherwise a session that later becomes available would
    # stay visually collapsed.
    after_branch = body[unavailable_m.end():]
    assert "desc.style.display = '';" in after_branch
    assert re.search(r"card\.style\.paddingTop = ''", after_branch)


# ═══════════════════════════════════════════════════════════════════════════
# Gallery (#117, close/44px, native-gallery #137-138, relabel)
# ═══════════════════════════════════════════════════════════════════════════

def test_gallery_tiles_use_flat_class_not_card_chrome():
    """#117: the engine-captured Gallery's screenshot/material tiles ARE the
    content — they must render `.applicant-gallery-tile` (flat, no nested
    card border/shadow), not the bordered/shadowed `.admin-card` chrome."""
    src = _read(GALLERY_JS)
    assert 'class="admin-card" style="display:flex;flex-direction:column;gap:6px;">' not in src, (
        "gallery tiles must not reuse .admin-card chrome"
    )
    shot_m = re.search(r"function _shotCard\(s\)\s*\{.*?return\s*`(.*?)`;", src, re.S)
    assert shot_m, "expected to find _shotCard"
    assert 'class="applicant-gallery-tile"' in shot_m.group(1)

    mat_m = re.search(r"function _matCard\(m\)\s*\{.*?return\s*`(.*?)`;", src, re.S)
    assert mat_m, "expected to find _matCard"
    assert 'class="applicant-gallery-tile"' in mat_m.group(1)

    css = _read(STYLE_CSS)
    css_m = re.search(r"#applicant-gallery-modal\s+\.applicant-gallery-tile\s*\{([^}]*)\}", css)
    assert css_m, "expected a #applicant-gallery-modal .applicant-gallery-tile rule"
    block = css_m.group(1)
    assert re.search(r"background:\s*transparent", block)
    assert re.search(r"border:\s*none", block)
    assert re.search(r"box-shadow:\s*none", block)


def test_gallery_close_control_uses_standardized_modal_close_and_x_glyph():
    """Gallery's close button must use the shared `.modal-close` class and
    the standard `×` glyph — not a bespoke `.close-btn` / heavy `✖` glyph."""
    src = _read(GALLERY_JS)
    m = re.search(
        r'<button class="([^"]*)" id="applicant-gallery-close"[^>]*>(.*?)</button>',
        src,
    )
    assert m, "expected to find the Gallery close button markup"
    assert m.group(1) == "modal-close", (
        f'close button must use class="modal-close", got {m.group(1)!r}'
    )
    assert m.group(2) == "×", (  # '×'
        f"close button glyph must be the standard × (U+00D7), got {m.group(2)!r}"
    )
    assert "✖" not in src, "the heavy ✖ (U+2716) glyph must not remain anywhere in the file"


def test_gallery_and_vault_and_remote_close_controls_meet_44px_hit_region():
    """#119: the Vault/Remote/Gallery close controls get a scoped >=44px tap
    target (WCAG 2.5.5) plus a dedicated focus ring — every other surface's
    shared .close-btn/.modal-close (24px) is untouched."""
    css = _read(STYLE_CSS)
    m = re.search(
        r"#applicant-vault-modal \.modal-close,\s*"
        r"#applicant-remote-modal \.modal-close,\s*"
        r"#applicant-gallery-modal \.close-btn,\s*"
        r"#applicant-gallery-modal \.modal-close\s*\{([^}]*)\}",
        css,
    )
    assert m, "expected the scoped Vault/Remote/Gallery close-control selector group"
    block = m.group(1)
    assert re.search(r"width:\s*44px\s*;", block)
    assert re.search(r"height:\s*44px\s*;", block)

    focus_m = re.search(
        r"#applicant-vault-modal \.modal-close:focus-visible,\s*"
        r"#applicant-remote-modal \.modal-close:focus-visible,\s*"
        r"#applicant-gallery-modal \.close-btn:focus-visible,\s*"
        r"#applicant-gallery-modal \.modal-close:focus-visible\s*\{([^}]*)\}",
        css,
    )
    assert focus_m, "expected a matching :focus-visible ring for the same selector group"
    assert re.search(r"outline:\s*2px solid var\(--sys-blue\)", focus_m.group(1))


def test_native_gallery_tiles_flat_and_hover_delifted():
    """#137/#138: the workspace's OWN native photo gallery (`.gallery-card`,
    distinct from the engine's `.applicant-gallery-tile`) must render flat
    content tiles (no border chrome) with a de-lifted hover: a subtle
    neutral inset ring instead of a colored border + shadow + translateY
    lift."""
    css = _read(STYLE_CSS)

    flat_m = re.search(r"\.gallery-card:not\(\.gallery-card-upload\)\s*\{([^}]*)\}", css)
    assert flat_m, "expected a .gallery-card:not(.gallery-card-upload) rule"
    assert re.search(r"border-color:\s*transparent\s*;", flat_m.group(1))

    hover_m = re.search(r"\.gallery-card:hover\s*\{([^}]*)\}", css)
    assert hover_m, "expected a .gallery-card:hover rule"
    hover_block = hover_m.group(1)
    assert "transform" not in hover_block, (
        f"hover must not lift the tile (translateY), got: {hover_block!r}"
    )
    assert "var(--red)" not in hover_block, (
        f"hover must not use the colored --red border/shadow treatment, got: {hover_block!r}"
    )
    assert re.search(
        r"box-shadow:\s*inset 0 0 0 1px color-mix\(in srgb,\s*var\(--fg\)\s*22%,\s*transparent\)\s*;",
        hover_block,
    ), f"expected a subtle neutral inset hover ring, got: {hover_block!r}"


def test_engine_gallery_relabeled_application_gallery_everywhere():
    """Relabel: the engine's Gallery must read "Application Gallery"
    everywhere it's surfaced — disambiguating it from the workspace's own
    native photo gallery (which stays plain "Gallery") — in the modal
    itself, and in both front-door launchers' tooltips (rail icon + tool list
    item).

    Pass 2a (a later nav-reconciliation pass) moved the launchers themselves
    out of index.html into applicantNav.js's NAV array, and shortened the
    SIDEBAR's visible label to plain "Gallery" — the full "Application
    Gallery — ..." name now lives only in the shared `title` field (rendered
    as the rail button's title+aria-label AND the sidebar item's title), not
    in the sidebar's visible text."""
    gallery_src = _read(GALLERY_JS)
    assert "Application Gallery — screenshots and generated materials" in gallery_src, (
        "expected the modal's aria-label to read 'Application Gallery — ...'"
    )
    header_m = re.search(r"<h4>\s*<svg[^>]*>.*?</svg>\s*\n\s*(.*?)\n\s*</h4>", gallery_src, re.S)
    assert header_m, "expected to find the modal header <h4> content"
    assert header_m.group(1).strip() == "Application Gallery", (
        f"modal header must read exactly 'Application Gallery', got {header_m.group(1)!r}"
    )

    nav_src = _read(NAV_JS)
    item_m = re.search(
        r"\{\s*rail:\s*'rail-applicant-gallery',\s*side:\s*'tool-applicant-gallery-btn'[^}]*\}",
        nav_src,
        re.S,
    )
    assert item_m, "expected the rail-applicant-gallery / tool-applicant-gallery-btn NAV entry"
    entry = item_m.group(0)

    title_m = re.search(r"title:\s*'([^']*)'", entry)
    assert title_m, "expected a title field on the NAV entry"
    assert title_m.group(1).startswith("Application Gallery"), (
        f"expected the tooltip to start with 'Application Gallery', got {title_m.group(1)!r}"
    )

    label_m = re.search(r"label:\s*'([^']*)'", entry)
    assert label_m, "expected a label field on the NAV entry"
    assert label_m.group(1) == "Gallery", (
        f"expected the sidebar's short visible label to read 'Gallery', got {label_m.group(1)!r}"
    )

    # _railButton always emits aria-label from the SAME `title` field, so the
    # title assertion above plus this template check together establish
    # "starts with Application Gallery" for both the rail button's title AND
    # its aria-label (see test_applicant_round2_wave1_a11y_labels.py, which
    # pins this invariant for every NAV rail item).
    rail_fn_m = re.search(r"function _railButton\(item\)\s*\{(.*?)\n\}", nav_src, re.S)
    assert rail_fn_m and 'aria-label="${item.title}"' in rail_fn_m.group(1), (
        "expected _railButton to emit aria-label from the same `title` field as title"
    )

    # And the workspace's OWN native gallery must stay plain "Gallery" — the
    # relabel is scoped to the engine's surfaces only, not a global rename.
    # (rail-gallery is the native, vendored, hidden rail button — still
    # static index.html markup; Pass 2a doesn't touch it.)
    html = _read(INDEX_HTML)
    native_rail_m = re.search(r'id="rail-gallery"\s+title="([^"]*)"', html)
    assert native_rail_m and native_rail_m.group(1) == "Gallery", (
        "the native workspace gallery launcher must remain plain 'Gallery'"
    )
