"""Regression coverage for two front-door reachability findings against
``static/index.html`` (the workspace shell markup):

  1. lens 12 #5 -- ``static/js/applicantTrust.js`` (the "How Applicant
     protects you" trust center) is a fully-built, self-contained,
     content-only surface, but nothing in the shell ever loaded it: no
     ``<script type="module">`` tag pulled it into the page, and no element
     with id ``tool-trust-btn`` existed for its own ``_wireLaunchers()`` to
     find. Without both, the module never ran and the launcher never
     appeared -- the surface was unreachable. This file asserts both the
     module tag and the launcher element now exist in the shell, and that
     the launcher sits in the Tools list alongside its sibling launchers
     (matching the existing ``list-item`` markup/classes).
  2. lens 11 #7 -- the Settings sidebar's ``data-settings-tab`` list grouped
     tabs under unlabeled dividers; only the admin-only tail ("Tools",
     "Users", "System") got an explicit ``.settings-sidebar-label`` ("Admin").
     The Applicant-specific tabs (Campaign, and further down the admin-only
     Automation/sandbox tab) had no equivalent heading distinguishing them
     from the generic workspace tabs (Add Models, AI Defaults, Search,
     Fonts, Integrations, Email, ...). This file asserts an "Applicant"
     ``.settings-sidebar-label`` now exists, reusing the same class as the
     existing "Admin" label, and that it precedes the Campaign tab.

Both assertions are source-level (regex/substring over the real
``static/index.html``), the same technique used by
``test_applicant_reachability_wiring.py`` and
``test_applicant_promote_variant.py`` for markup that isn't designed for
full DOM execution.

Every assertion here was hand-verified to go RED against a backup copy of
the pre-fix ``index.html`` (no ``applicantTrust.js`` script tag, no
``tool-trust-btn`` element, no "Applicant" ``.settings-sidebar-label``)
before landing this file, and GREEN again once the backup was restored.
"""

from __future__ import annotations

import pathlib
import re

_REPO = pathlib.Path(__file__).resolve().parent.parent  # workspace/
_INDEX_HTML = _REPO / "static" / "index.html"
# Pass 2a: the Tools sidebar list-items (incl. tool-trust-btn) now render from
# applicantNav.js's single-source NAV array instead of being hand-authored
# divs in index.html.
_NAV_JS = _REPO / "static" / "js" / "applicantNav.js"


def _read() -> str:
    return _INDEX_HTML.read_text(encoding="utf-8")


def _read_nav() -> str:
    return _NAV_JS.read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════════
# 1. The standalone "Trust" nav item was removed (user-driven).
# ══════════════════════════════════════════════════════════════════════════
#
# The wordmark-adjacent "Trust" launcher read as an unexplained button. It was
# removed from the nav; its safety message is contextual instead — the Portal's
# "you approve every application before it's sent — you're always in control"
# line and the onboarding wizard. The applicantTrust.js module still ships but is
# dormant (no launcher wires to it), so nothing 404s and it can be re-surfaced
# later without re-plumbing.


def test_trust_center_module_script_still_ships_dormant():
    # The module remains loaded (harmless, unwired) so a future re-surfacing
    # needs no re-plumbing — but it must NOT be reachable from the nav.
    src = _read()
    assert '<script type="module" src="/static/js/applicantTrust.js"></script>' in src


def test_trust_center_is_intentionally_not_a_nav_destination():
    """Guard the removal so it isn't reflexively re-added: no NAV entry, no rail
    twin for Trust. (User feedback: the button read as unexplained.)"""
    nav_src = _read_nav()
    assert not re.search(r"side:\s*'tool-trust-btn'", nav_src), (
        "the Trust nav item was intentionally removed — do not re-add it to NAV"
    )
    assert "rail-trust" not in nav_src, (
        "the Trust rail twin was intentionally removed"
    )


# ══════════════════════════════════════════════════════════════════════════
# 2. lens 11 #7 -- an "Applicant" settings-sidebar group label exists.
# ══════════════════════════════════════════════════════════════════════════


def test_applicant_settings_sidebar_label_exists():
    src = _read()
    # Reuses the exact class the existing "Admin" heading uses -- no new
    # visual language, per the workspace design-system convention.
    assert re.search(r'<div class="settings-sidebar-label"[^>]*>Applicant</div>', src)


def test_applicant_settings_sidebar_label_precedes_the_campaign_tab():
    src = _read()
    sidebar = re.search(
        r'<div class="settings-sidebar">.*?<div class="settings-panels">',
        src,
        re.S,
    )
    assert sidebar, "expected to find the settings sidebar block"
    body = sidebar.group(0)

    label_match = re.search(r'<div class="settings-sidebar-label"[^>]*>Applicant</div>', body)
    campaign_match = re.search(r'data-settings-tab="campaign"', body)
    assert label_match and campaign_match
    assert label_match.start() < campaign_match.start(), (
        "the 'Applicant' label should sit before the Campaign tab it introduces"
    )


def test_settings_sidebar_still_has_exactly_one_active_default_tab():
    # Guard against the additive markup accidentally disturbing the existing
    # tabs: "Add Models" must remain the single default-active tab, and every
    # pre-existing data-settings-tab value must still be present (nothing was
    # dropped while adding the label/divider).
    src = _read()
    sidebar = re.search(
        r'<div class="settings-sidebar">.*?<div class="settings-panels">',
        src,
        re.S,
    )
    assert sidebar
    body = sidebar.group(0)
    assert body.count('settings-nav-item active') == 1
    for tab in (
        "services", "ai", "campaign", "search", "fonts", "sandbox", "update",
        "integrations", "email", "reminders", "notifications",
        "appearance", "shortcuts", "account", "tools", "users", "system",
    ):
        assert f'data-settings-tab="{tab}"' in body, f"missing pre-existing tab: {tab}"
