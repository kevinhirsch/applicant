"""Regression coverage for P3-8 (Digest deliverability), confined to the
Notifications step renderer (``static/js/applicantOnboarding.js``, shared by
the OOBE wizard and Settings via ``mountSettingsStep``) and the new
``docs/email-deliverability.md`` guidance doc.

DoD (docs/backlog/road-to-market.md): "ntfy/Discord defaulted as the
recommended channel; SPF/DKIM guidance shipped for the SMTP path."

Follows the established convention: every fact is read from the actual
static file / doc content via ``pathlib`` — no browser, no DOM, no real
socket, no network (this story is explicitly about a channel this container
cannot actually deliver through). Each assertion was hand-verified to go red
when the underlying change is reverted, per the project's revert-verify
convention.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"
DELIVERABILITY_DOC = REPO_ROOT / "docs" / "email-deliverability.md"


def _read_js() -> str:
    return ONBOARDING_JS.read_text(encoding="utf-8")


def _channels_block() -> str:
    src = _read_js()
    start = src.index("async function _renderChannels()")
    end = src.index("// ── STEP 2.5: Automation sandbox", start)
    return src[start:end]


# ── ntfy/Discord defaulted as the recommended channel ───────────────────────


def test_discord_and_ntfy_rows_are_labeled_recommended():
    block = _channels_block()
    discord_label = re.search(
        r'<label class="settings-label">Discord webhook.*?</label>', block, re.S
    )
    ntfy_label = re.search(
        r'<label class="settings-label">Phone push \(ntfy\).*?</label>', block, re.S
    )
    email_label = re.search(
        r'<label class="settings-label">Email / SMTP.*?</label>', block, re.S
    )
    assert discord_label and "Recommended" in discord_label.group(0)
    assert ntfy_label and "Recommended" in ntfy_label.group(0)
    # Email is deliberately NOT badged "Recommended" — it needs SMTP setup to
    # be reliable, unlike Discord/ntfy which have no deliverability problem.
    assert email_label and "Recommended" not in email_label.group(0)


def test_step_description_recommends_discord_and_ntfy_over_email():
    block = _channels_block()
    assert "Discord and phone push (ntfy) are" in block
    assert "recommended" in block
    # Required substrings other pins (copy-voice lens 02) already assert —
    # confirm this change is additive, not a rewrite that dropped them.
    assert "so I can send you updates and ask for approvals" in block


def test_help_card_marks_discord_and_ntfy_sections_recommended():
    block = _channels_block()
    idx_discord = block.index("<strong>Discord webhook</strong>")
    idx_ntfy = block.index("<strong>Phone push (ntfy)</strong>")
    idx_email = block.index("<strong>Email / SMTP</strong>")
    window_discord = block[idx_discord : idx_discord + 80]
    window_ntfy = block[idx_ntfy : idx_ntfy + 80]
    window_email = block[idx_email : idx_email + 80]
    assert "recommended" in window_discord
    assert "recommended" in window_ntfy
    assert "recommended" not in window_email


# ── SPF/DKIM guidance shipped for the SMTP path ─────────────────────────────


def test_email_field_tooltip_mentions_spf_dkim_dmarc():
    block = _channels_block()
    idx = block.index('id="ao-ch-email"')
    window = block[max(0, idx - 900) : idx]
    assert "SPF" in window
    assert "DKIM" in window
    assert "DMARC" in window


def test_help_card_points_at_the_deliverability_doc():
    block = _channels_block()
    assert "docs/email-deliverability.md" in block
    assert "SPF" in block
    assert "DKIM" in block
    assert "DMARC" in block


def test_help_card_documents_from_and_reply_to_query_params():
    """Apprise already supports From-name/Reply-To as URL params; the panel
    should tell users how to use them rather than leaving sane headers as an
    undiscoverable feature."""
    block = _channels_block()
    assert "?from=" in block
    assert "reply=" in block


# ── The guidance doc itself ─────────────────────────────────────────────────


def test_deliverability_doc_exists_with_required_sections():
    assert DELIVERABILITY_DOC.exists(), "expected docs/email-deliverability.md"
    text = DELIVERABILITY_DOC.read_text(encoding="utf-8")
    for heading in (
        "SPF",
        "DKIM",
        "DMARC",
        "Bounce handling",
        "checklist",
    ):
        assert heading in text, f"expected the guide to cover {heading!r}"


def test_deliverability_doc_is_honest_about_no_live_inbox_testing():
    """H-series honesty: this doc must not claim a live inbox-placement check
    was actually run from this (network-isolated) environment."""
    text = DELIVERABILITY_DOC.read_text(encoding="utf-8")
    assert "not runnable from this environment" in text.lower() or (
        "not been run" in text.lower()
    )
    assert "mail-tester" in text.lower() or "postmaster" in text.lower()


def test_deliverability_doc_recommends_discord_ntfy_first():
    text = DELIVERABILITY_DOC.read_text(encoding="utf-8")
    idx = text.lower().index("recommended default")
    window = text[idx : idx + 400]
    assert "discord" in window.lower()
    assert "ntfy" in window.lower()
