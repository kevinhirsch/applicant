"""Settings > Automation config-store persistence (dark-engine audit items 82/84/85).

New foundational Settings tab: browser-fingerprint timezone/locale (item 82,
``EGRESS_TIMEZONE``/``EGRESS_LOCALE``), the automated-account-creation opt-in (item
84, ``ALLOW_AUTOMATED_ACCOUNTS``), and the per-company daily application cap (item
85, ``PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY``) were env-only with zero Settings UI
and zero runtime-override mechanism. This exercises the new
``SetupService.get_automation_prefs``/``set_automation_prefs`` pair, which follows
the exact ``get_channels``/``configure_channels`` config-store pattern already
established in this module: an override record in ``AppConfigStore``, ``None`` =
"leave this key alone" on write, and the raw (un-defaulted) record on read so the
caller (the setup router) can merge it onto the env-sourced ``Settings`` defaults.

Each assertion here was hand-verified to go RED when the corresponding piece of
``set_automation_prefs``/``get_automation_prefs`` is reverted, then GREEN again
after restoring (revert-verification per the task's definition of done).
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.setup_service import (
    AUTOMATION_PREFS_DEFAULTS,
    SetupService,
)


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


def test_get_automation_prefs_is_empty_before_anything_is_saved():
    svc = _svc()
    assert svc.get_automation_prefs() == {}


def test_defaults_constant_matches_configpy_field_defaults():
    """Pins the hardcoded defaults to the values the audit anchored on
    (config.py:411/469/565) so the two can't silently drift apart.

    Subset check (not full-dict ``==``): items 86/90 (approval timeout/wait,
    scheduler interval -- see ``test_automation_prefs_approval_scheduler.py``)
    additively extended this dict with more keys, so a strict equality here
    would break on every future additive knob.
    """
    assert AUTOMATION_PREFS_DEFAULTS["egress_timezone"] == "America/Phoenix"
    assert AUTOMATION_PREFS_DEFAULTS["egress_locale"] == "en-US"
    assert AUTOMATION_PREFS_DEFAULTS["allow_automated_accounts"] is False
    assert AUTOMATION_PREFS_DEFAULTS["presubmit_max_apps_per_company_per_day"] == 3


def test_set_then_get_round_trips_all_four_knobs():
    svc = _svc()
    svc.set_automation_prefs(
        egress_timezone="America/New_York",
        egress_locale="en-GB",
        allow_automated_accounts=True,
        presubmit_max_apps_per_company_per_day=7,
    )
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"
    assert prefs["egress_locale"] == "en-GB"
    assert prefs["allow_automated_accounts"] is True
    assert prefs["presubmit_max_apps_per_company_per_day"] == 7


def test_partial_save_leaves_the_other_knobs_untouched():
    """None = no-op on that key, same convention as set_quiet_hours."""
    svc = _svc()
    svc.set_automation_prefs(
        egress_timezone="America/New_York",
        allow_automated_accounts=True,
        presubmit_max_apps_per_company_per_day=5,
    )
    svc.set_automation_prefs(presubmit_max_apps_per_company_per_day=1)
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"  # untouched
    assert prefs["allow_automated_accounts"] is True  # untouched
    assert prefs["presubmit_max_apps_per_company_per_day"] == 1  # updated


def test_negative_per_company_cap_is_rejected():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(presubmit_max_apps_per_company_per_day=-1)
    # Rejected write must not partially land.
    assert svc.get_automation_prefs() == {}


def test_zero_per_company_cap_is_allowed():
    """0 is a legitimate (if extreme) cap -- "pause all applying to a company
    today" -- so only negative values are rejected, not falsy-zero."""
    svc = _svc()
    svc.set_automation_prefs(presubmit_max_apps_per_company_per_day=0)
    assert svc.get_automation_prefs()["presubmit_max_apps_per_company_per_day"] == 0


def test_blank_timezone_falls_back_to_the_default_not_an_empty_string():
    svc = _svc()
    svc.set_automation_prefs(egress_timezone="   ")
    assert svc.get_automation_prefs()["egress_timezone"] == "America/Phoenix"


def test_blank_locale_falls_back_to_the_default_not_an_empty_string():
    svc = _svc()
    svc.set_automation_prefs(egress_locale="")
    assert svc.get_automation_prefs()["egress_locale"] == "en-US"


def test_allow_automated_accounts_can_be_turned_back_off():
    """A bool False must persist as an explicit override, not be mistaken
    for "not set" (the None-sentinel convention must not swallow False)."""
    svc = _svc()
    svc.set_automation_prefs(allow_automated_accounts=True)
    assert svc.get_automation_prefs()["allow_automated_accounts"] is True
    svc.set_automation_prefs(allow_automated_accounts=False)
    assert svc.get_automation_prefs()["allow_automated_accounts"] is False


def test_state_persists_across_instances_over_the_same_store():
    """Simulated restart (FR-OOBE-1 pattern): a fresh SetupService over the
    same AppConfigStore must see the prior save."""
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_automation_prefs(
        egress_timezone="Europe/Berlin", presubmit_max_apps_per_company_per_day=10
    )
    svc2 = _svc(store)
    prefs = svc2.get_automation_prefs()
    assert prefs["egress_timezone"] == "Europe/Berlin"
    assert prefs["presubmit_max_apps_per_company_per_day"] == 10
