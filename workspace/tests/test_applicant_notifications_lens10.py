"""Regression coverage for exhaustive-audit-pass-2 lens 10 (notifications)
findings #22 and #52, confined to ``static/js/applicantOnboarding.js`` (the
Notifications/quiet-hours step rendered both in the OOBE wizard and, via
``mountSettingsStep``, in Settings).

Follows the convention of ``test_applicant_round1_onboarding.py``: every fact
is read from the actual static file content via ``pathlib`` + regex — no
browser, no DOM, no real socket. Each assertion was hand-verified to go red
when the underlying fix is reverted (backup the file to /tmp, revert the
change, rerun, see the assertion fail, restore from the backup) per the
project's revert-verify convention.

Findings covered (see ``docs/design/audits/exhaustive2/10_notifications.md``):
  * #22 — the engine's `email_timeout_minutes` channel setting had no
    front-door control. A numeric field now exists, pre-populated from the
    reported-back value and saved to the same `${SETUP}/channels` endpoint
    the other channel prefs use.
  * #52 — the quiet-hours time zone field silently degraded to UTC. It now
    defaults to the browser's own IANA zone (`Intl.DateTimeFormat().
    resolvedOptions().timeZone`) when nothing is saved yet.
"""

from __future__ import annotations

import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
JS_DIR = REPO_ROOT / "workspace" / "static" / "js"
ONBOARDING_JS = JS_DIR / "applicantOnboarding.js"


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ── #22: email-delay ("email_timeout_minutes") front-door control ──────────

def test_email_timeout_field_exists_prepopulated_from_engine_value():
    """A numeric input for the email escalation delay must exist, wired to
    read back `cur.email_timeout_minutes` (the value the engine's channels
    endpoint reports) rather than always starting blank/zero."""
    js = _read(ONBOARDING_JS)
    assert 'id="ao-ch-email-timeout"' in js, (
        "expected a dedicated numeric field for the email escalation delay"
    )
    m = re.search(r'<input id="ao-ch-email-timeout"[^>]*>', js)
    assert m, "expected the email-timeout input tag"
    tag = m.group(0)
    assert 'type="number"' in tag, "email-timeout field should be numeric"
    assert "cur.email_timeout_minutes" in tag, (
        "email-timeout field must pre-populate from the reported-back engine value"
    )


def test_email_timeout_saved_to_channels_endpoint():
    """Saving the field must POST `email_timeout_minutes` to the same
    `${SETUP}/channels` endpoint the other channel preferences use, not a
    bespoke or dead-end path."""
    js = _read(ONBOARDING_JS)
    m = re.search(
        r"etSave\.onclick\s*=\s*async[^{]*\{(.*?)\n\s*\};",
        js,
        re.DOTALL,
    )
    assert m, "expected an onclick handler for the email-timeout save button"
    body = m.group(1)
    assert "`${SETUP}/channels`" in body, (
        "email-timeout save must hit the shared channels endpoint"
    )
    assert "email_timeout_minutes" in body, (
        "email-timeout save payload must include email_timeout_minutes"
    )


def test_email_timeout_field_has_plain_language_label():
    """White-label: the field's label/help text must be plain language, with
    no FR-/NFR- jargon and no upstream codenames leaking into the copy."""
    js = _read(ONBOARDING_JS)
    idx = js.index('id="ao-ch-email-timeout"')
    window = js[max(0, idx - 800): idx]
    assert "Email me after" in window or "Email reminder timing" in window
    assert not re.search(r"\bFR-[A-Z]", window)
    assert not re.search(r"\bNFR-[A-Z]", window)


# ── #52: quiet-hours time zone browser-default ──────────────────────────────

def test_quiet_hours_timezone_defaults_to_browser_zone_when_unsaved():
    """The `ao-qh-tz` field must default to the browser's own IANA zone
    (via `Intl.DateTimeFormat().resolvedOptions().timeZone`) when there is no
    saved quiet-hours timezone yet, instead of silently starting blank (which
    the engine then evaluates as UTC)."""
    js = _read(ONBOARDING_JS)
    assert "Intl.DateTimeFormat().resolvedOptions().timeZone" in js, (
        "expected the browser timezone API to be read as a default source"
    )
    m = re.search(r'<input id="ao-qh-tz"[^>]*>', js)
    assert m, "expected the quiet-hours timezone input tag"
    tag = m.group(0)
    assert "qh.tz || ''" not in tag, (
        "the timezone field must no longer fall back straight to blank"
    )
    assert "qhTz" in tag, (
        "the timezone field's value must come from the browser-defaulted qhTz, not qh.tz alone"
    )


def test_quiet_hours_timezone_default_falls_back_to_utc_if_intl_throws():
    """`Intl` lookups can throw in constrained/older environments; the
    fallback must still be a safe literal ('UTC'), not an unguarded throw
    that would break rendering the whole Notifications step."""
    js = _read(ONBOARDING_JS)
    m = re.search(
        r"let _browserTz = 'UTC';\s*\n\s*try \{([^}]*)\} catch",
        js,
    )
    assert m, "expected a guarded (try/catch) browser-timezone lookup with a 'UTC' fallback"
    assert "resolvedOptions().timeZone" in m.group(1)
