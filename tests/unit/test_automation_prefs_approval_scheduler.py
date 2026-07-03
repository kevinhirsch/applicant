"""Settings > Automation config-store persistence for the approval-timeout and
scheduler-interval knobs (dark-engine audit items 86/90).

Extends the foundation laid down for items 82/84/85
(``test_automation_prefs_setup_service.py``) with two more previously env-only
knobs: how long a pending final-approval waits before timing out
(``APPROVAL_TIMEOUT_DAYS`` / the fine-grained ``APPROVAL_WAIT_SECONDS``
override, item 90) and how often the 24/7 loop ticks
(``SCHEDULER_INTERVAL_SECONDS``, item 86). Same ``SetupService.get_automation_
prefs``/``set_automation_prefs`` config-store pattern -- additive fields, not a
new mechanism.

Each assertion here was hand-verified to go RED when the corresponding piece
of ``set_automation_prefs``/``get_automation_prefs``/``AUTOMATION_PREFS_
DEFAULTS`` is reverted, then GREEN again after restoring (revert-verification
per the task's definition of done, via file-copy backups -- not ``git stash``,
which is shared across worktrees in this session).
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


def test_defaults_constant_includes_the_approval_and_scheduler_knobs():
    """Pins the hardcoded defaults to config.py's field defaults (approval_
    timeout_days=30, approval_wait_seconds=None, scheduler_interval_seconds=
    60.0) so the two can't silently drift apart."""
    assert AUTOMATION_PREFS_DEFAULTS["approval_timeout_days"] == 30
    assert AUTOMATION_PREFS_DEFAULTS["approval_wait_seconds"] is None
    assert AUTOMATION_PREFS_DEFAULTS["scheduler_interval_seconds"] == 60.0


def test_set_then_get_round_trips_the_approval_timeout_days():
    svc = _svc()
    svc.set_automation_prefs(approval_timeout_days=45)
    assert svc.get_automation_prefs()["approval_timeout_days"] == 45


def test_set_then_get_round_trips_the_approval_wait_seconds_override():
    svc = _svc()
    svc.set_automation_prefs(approval_wait_seconds=120.5)
    assert svc.get_automation_prefs()["approval_wait_seconds"] == 120.5


def test_set_then_get_round_trips_the_scheduler_interval_seconds():
    svc = _svc()
    svc.set_automation_prefs(scheduler_interval_seconds=30.0)
    assert svc.get_automation_prefs()["scheduler_interval_seconds"] == 30.0


def test_partial_save_of_new_knobs_leaves_the_existing_three_untouched():
    svc = _svc()
    svc.set_automation_prefs(
        egress_timezone="America/New_York",
        allow_automated_accounts=True,
        presubmit_max_apps_per_company_per_day=5,
    )
    svc.set_automation_prefs(approval_timeout_days=10, scheduler_interval_seconds=15.0)
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"  # untouched
    assert prefs["allow_automated_accounts"] is True  # untouched
    assert prefs["presubmit_max_apps_per_company_per_day"] == 5  # untouched
    assert prefs["approval_timeout_days"] == 10
    assert prefs["scheduler_interval_seconds"] == 15.0


def test_partial_save_of_one_new_knob_leaves_the_other_new_knob_untouched():
    svc = _svc()
    svc.set_automation_prefs(approval_timeout_days=20, scheduler_interval_seconds=45.0)
    svc.set_automation_prefs(approval_timeout_days=5)
    prefs = svc.get_automation_prefs()
    assert prefs["approval_timeout_days"] == 5  # updated
    assert prefs["scheduler_interval_seconds"] == 45.0  # untouched


def test_negative_approval_timeout_days_is_rejected():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(approval_timeout_days=-1)
    assert svc.get_automation_prefs() == {}


def test_zero_approval_timeout_days_is_allowed():
    """0 is the documented "no timeout / wait forever" sentinel (mirrors
    config.py's approval_timeout_days docstring), not an invalid value."""
    svc = _svc()
    svc.set_automation_prefs(approval_timeout_days=0)
    assert svc.get_automation_prefs()["approval_timeout_days"] == 0


def test_negative_approval_wait_seconds_is_rejected():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(approval_wait_seconds=-5.0)
    assert svc.get_automation_prefs() == {}


def test_zero_approval_wait_seconds_is_allowed():
    """0 is the documented "no timeout" sentinel for the seconds override too."""
    svc = _svc()
    svc.set_automation_prefs(approval_wait_seconds=0.0)
    assert svc.get_automation_prefs()["approval_wait_seconds"] == 0.0


def test_zero_scheduler_interval_seconds_is_rejected():
    """Unlike the timeout knobs, 0 (or negative) has no valid meaning for a
    tick interval -- it would be a busy loop -- so it must be rejected."""
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(scheduler_interval_seconds=0.0)
    assert svc.get_automation_prefs() == {}


def test_negative_scheduler_interval_seconds_is_rejected():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(scheduler_interval_seconds=-10.0)
    assert svc.get_automation_prefs() == {}


def test_state_persists_across_instances_over_the_same_store():
    """Simulated restart (FR-OOBE-1 pattern): a fresh SetupService over the
    same AppConfigStore must see the prior save."""
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_automation_prefs(approval_timeout_days=14, scheduler_interval_seconds=90.0)
    svc2 = _svc(store)
    prefs = svc2.get_automation_prefs()
    assert prefs["approval_timeout_days"] == 14
    assert prefs["scheduler_interval_seconds"] == 90.0
