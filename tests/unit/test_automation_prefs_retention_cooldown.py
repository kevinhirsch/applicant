"""Settings > Automation config-store persistence for items 87/88 (dark-engine
audit): the data-retention window (``PII_RETENTION_DAYS``, default 0 = keep
forever) and the duplicate-application re-apply cooldown
(``PRESUBMIT_DUPLICATE_COOLDOWN_DAYS``, default 30) were env-only with zero
Settings UI. This exercises the two new ``SetupService.set_automation_prefs``/
``get_automation_prefs`` fields (``pii_retention_days``,
``presubmit_duplicate_cooldown_days``), which follow the same config-store
override pattern as the existing four automation-prefs knobs.

Each assertion here was hand-verified to go RED when the corresponding piece
of ``set_automation_prefs`` is reverted (file-copy backup, not ``git stash`` —
shared across sibling worktrees in this session), then GREEN again after
restoring.
"""

from __future__ import annotations

import pytest

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.application.services.setup_service import SetupService


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


def test_get_automation_prefs_is_empty_before_anything_is_saved():
    svc = _svc()
    prefs = svc.get_automation_prefs()
    assert "pii_retention_days" not in prefs
    assert "presubmit_duplicate_cooldown_days" not in prefs


def test_set_then_get_round_trips_both_new_knobs():
    svc = _svc()
    svc.set_automation_prefs(pii_retention_days=90, presubmit_duplicate_cooldown_days=14)
    prefs = svc.get_automation_prefs()
    assert prefs["pii_retention_days"] == 90
    assert prefs["presubmit_duplicate_cooldown_days"] == 14


def test_zero_retention_days_is_allowed_and_means_keep_forever():
    """0 is the documented default meaning "keep forever" -- must not be
    rejected as falsy/invalid."""
    svc = _svc()
    svc.set_automation_prefs(pii_retention_days=0)
    assert svc.get_automation_prefs()["pii_retention_days"] == 0


def test_zero_cooldown_days_is_allowed():
    svc = _svc()
    svc.set_automation_prefs(presubmit_duplicate_cooldown_days=0)
    assert svc.get_automation_prefs()["presubmit_duplicate_cooldown_days"] == 0


def test_negative_retention_days_is_rejected():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(pii_retention_days=-1)
    # Rejected write must not partially land.
    assert svc.get_automation_prefs() == {}


def test_negative_cooldown_days_is_rejected():
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(presubmit_duplicate_cooldown_days=-5)
    assert svc.get_automation_prefs() == {}


def test_partial_save_of_new_knobs_leaves_existing_knobs_untouched():
    svc = _svc()
    svc.set_automation_prefs(egress_timezone="America/New_York", allow_automated_accounts=True)
    svc.set_automation_prefs(pii_retention_days=30)
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"  # untouched
    assert prefs["allow_automated_accounts"] is True  # untouched
    assert prefs["pii_retention_days"] == 30  # newly set
    assert "presubmit_duplicate_cooldown_days" not in prefs  # never touched


def test_partial_save_of_new_knobs_does_not_clobber_each_other():
    svc = _svc()
    svc.set_automation_prefs(pii_retention_days=60)
    svc.set_automation_prefs(presubmit_duplicate_cooldown_days=7)
    prefs = svc.get_automation_prefs()
    assert prefs["pii_retention_days"] == 60  # untouched by the second call
    assert prefs["presubmit_duplicate_cooldown_days"] == 7


def test_state_persists_across_instances_over_the_same_store():
    """Simulated restart (FR-OOBE-1 pattern): a fresh SetupService over the
    same AppConfigStore must see the prior save."""
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_automation_prefs(pii_retention_days=45, presubmit_duplicate_cooldown_days=21)
    svc2 = _svc(store)
    prefs = svc2.get_automation_prefs()
    assert prefs["pii_retention_days"] == 45
    assert prefs["presubmit_duplicate_cooldown_days"] == 21
