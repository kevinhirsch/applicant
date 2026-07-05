"""Regression coverage for exhaustive-audit-pass-2 lens 11 (settings/config)
findings #51, #34, and #50, confined to
``static/js/applicantCampaignSettings.js`` (Settings -> Campaign tab).

Follows the project convention (see e.g. ``test_applicant_settings_nav_lens11.py``):
every fact is read from the actual static file content via ``pathlib`` + regex —
no browser, no DOM, no real socket. Each assertion was hand-verified to go red
when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/11_settings_config.md``):
  * #51 — the daily-target field clamped to a hard cap (30) and only told the
    user about it *after* they hit it ("Capped at X for safety"). The label
    itself now states the cap up front ("up to 30") so the ceiling is visible
    before it's ever hit.
  * #34 — name/mode/target/exploration-budget all share one explicit
    "Save changes" button, while the discovery-source checkboxes below save
    instantly on change — a mixed save model with no indicator of which state
    a field is in. A lightweight "Unsaved changes" dirty badge now appears on
    the campaign card as soon as any Save-button-backed field is edited, and
    clears once the card is freshly re-rendered after a successful save.
  * #50 — nothing on the campaign card said whether its settings were
    per-search or deployment-wide. A short caption now states these settings
    apply to this search only.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
CAMPAIGN_JS = JS_DIR / "applicantCampaignSettings.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _card_fn_body(js: str) -> str:
    m = re.search(r"function _campaignCard\(c\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected a _campaignCard(c) function"
    return m.group(1)


def _wire_card_fn_body(js: str) -> str:
    m = re.search(r"async function _wireCard\(host, card\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert m, "expected an async _wireCard(host, card) function"
    return m.group(1)


# ── #51: daily-target cap stated in the label up front ──────────────────────


def test_max_daily_target_constant_defined():
    js = _read(CAMPAIGN_JS)
    assert re.search(r"MAX_DAILY_TARGET\s*=\s*30", js), (
        "expected a MAX_DAILY_TARGET = 30 constant mirroring the engine's hard cap"
    )


def test_daily_target_label_states_the_cap_up_front():
    js = _read(CAMPAIGN_JS)
    body = _card_fn_body(js)
    label_match = re.search(
        r"Daily target\s*\n\s*<span[^>]*>\(([^)]*)\)</span>", body
    )
    assert label_match, "expected a Daily target label with a parenthetical help span"
    help_text = label_match.group(1)
    assert "${MAX_DAILY_TARGET}" in help_text, (
        "the daily-target label's help text must interpolate the actual cap number, "
        "not just say 'capped for safety' with no number"
    )


def test_daily_target_input_max_uses_the_shared_constant():
    js = _read(CAMPAIGN_JS)
    body = _card_fn_body(js)
    assert 'max="${MAX_DAILY_TARGET}"' in body, (
        "the number input's max attribute should derive from the same "
        "MAX_DAILY_TARGET constant surfaced in the label, so they can't drift apart"
    )


# ── #34: dirty indicator for the explicit-save field group ──────────────────


def test_dirty_badge_element_exists_hidden_by_default():
    js = _read(CAMPAIGN_JS)
    body = _card_fn_body(js)
    assert 'class="memory-badge cs-dirty-badge"' in body, (
        "expected a dirty-state badge reusing the existing memory-badge design-system class"
    )
    assert "Unsaved changes" in body, "the dirty badge should say something like 'Unsaved changes'"
    # Hidden by default: rendered fresh, no field has been edited yet.
    badge_match = re.search(
        r'<span class="memory-badge cs-dirty-badge"[^>]*id="cs-dirty-\$\{id\}"[^>]*>',
        body,
    )
    assert badge_match, "expected the dirty badge span to be keyed per-campaign (id cs-dirty-${id})"
    assert "display:none" in badge_match.group(0), (
        "the dirty badge must start hidden (display:none) since a freshly rendered card has no edits"
    )


def test_dirty_badge_toggled_by_save_button_backed_fields():
    js = _read(CAMPAIGN_JS)
    body = _wire_card_fn_body(js)
    assert "_setDirty" in body, "expected a dirty-state setter used from _wireCard"
    assert "querySelectorAll('[data-cs-field]')" in body, (
        "the dirty tracker must cover every field wired to the Save-changes button "
        "(name, run_mode, throughput_target, exploration_pct), not a hand-picked subset"
    )
    assert "_setDirty(true)" in body, "editing a tracked field must flip the dirty badge on"


def test_dirty_indicator_does_not_touch_the_instant_save_source_checkboxes():
    js = _read(CAMPAIGN_JS)
    wire_sources = re.search(r"async function _wireSources\(host, campaignId\)\s*\{(.*?)\n\}\n", js, re.DOTALL)
    assert wire_sources, "expected an async _wireSources(host, campaignId) function"
    assert "_setDirty" not in wire_sources.group(1), (
        "the discovery-source toggles save instantly and must stay untouched by the "
        "explicit-save dirty indicator — conflating the two would misrepresent the mixed save model"
    )


# ── #50: per-campaign scope caption ──────────────────────────────────────────


def test_campaign_card_has_a_per_search_scope_caption():
    js = _read(CAMPAIGN_JS)
    body = _card_fn_body(js)
    assert "cs-scope-caption" in body, "expected a dedicated scope-caption element on the campaign card"
    caption_match = re.search(
        r'class="admin-toggle-sub cs-scope-caption"[^>]*>\s*([^<]*)\s*</div>', body
    )
    assert caption_match, "expected the scope caption to reuse the admin-toggle-sub design-system class"
    caption_text = caption_match.group(1).lower()
    assert "this search only" in caption_text, (
        "the caption should say plainly that these settings are scoped to this search"
    )
    assert "deployment" in caption_text or "other searches" in caption_text, (
        "the caption should contrast per-search scope against the wider deployment/other searches "
        "so a reader isn't left guessing what the alternative scope would have been"
    )


def test_scope_caption_sits_inside_the_card_near_the_top_not_buried_in_danger_zone():
    js = _read(CAMPAIGN_JS)
    body = _card_fn_body(js)
    # The caption must appear before the Discovery sources block and the danger
    # zone, i.e. it's an up-front orientation note, not a footnote.
    caption_pos = body.index("cs-scope-caption")
    sources_pos = body.index("cs-sources")
    danger_pos = body.index("cs-danger-zone")
    assert caption_pos < sources_pos < danger_pos, (
        "the scope caption should appear near the top of the card, before the "
        "sources list and danger zone, so it's read first"
    )
