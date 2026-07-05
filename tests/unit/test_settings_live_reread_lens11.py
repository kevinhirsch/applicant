"""Lens 11 audit findings #22 (pre-submit safety thresholds) and #23 (approval
timeouts): ``container.py`` built these ONCE from ``settings.*`` at
container-build time and never re-read the persisted Settings > Automation store
(``SetupService.get_automation_prefs``/``set_automation_prefs``) -- so a threshold
an operator saved in Settings > Automation persisted and displayed back but never
actually governed the running engine. This is the SAME systemic gap
``Scheduler._effective_curation_schedule`` (scheduler.py) already fixed for the
curation cadence; this file extends that pattern to two more knobs.

This file proves, for ONE ``build_container()`` result (no rebuild in between the
"before" and "after" assertions):

* #22 -- ``presubmit_safety_params`` (a live proxy, ``_LivePresubmitSafetyParams``,
  shared by BOTH ``AgentLoop._process_approvals`` and ``DigestService``'s
  digest-row warning preview) and ``PrefillService``'s ATS match-rate floor
  (``_effective_match_rate_floor``) now re-read
  ``SetupService.get_automation_prefs()`` on EVERY check;
* #23 -- the DBOS orchestrator's approval-gate ``recv`` timeout
  (``DbosOrchestrator._resolve_timeout_seconds``) does the same.

Each assertion below was hand-verified RED (temporarily reverted the
container.py / prefill_service.py / dbos_orchestrator.py changes against a
``cp``-backed copy of the pre-fix files, reran this file, watched the "after
save" assertions fail because the value never changed) then GREEN again
(restored the fix) before this file was landed.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from applicant.app.config import Settings
from applicant.app.container import _build_orchestrator, build_container
from applicant.application.services.presubmit_safety import (
    PresubmitBlock,
    check_per_company_volume_cap,
)
from applicant.core.entities.application import Application
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import ApplicationId, CampaignId, JobPostingId, new_id
from applicant.core.state_machine import ApplicationState


def _build(**settings_kwargs):
    return build_container(Settings(_env_file=None, **settings_kwargs))


# ---------------------------------------------------------------------------
# #22a -- presubmit_safety_params (AgentLoop + DigestService)
# ---------------------------------------------------------------------------


def test_presubmit_params_fall_back_to_settings_when_nothing_saved():
    """With no Settings > Automation override saved, the live params must reflect
    the ACTUAL configured ``settings.presubmit_*`` values -- not a hardcoded
    literal that happens to coincide with the defaults."""
    container = _build(
        PRESUBMIT_MAX_LISTING_AGE_DAYS=45,
        PRESUBMIT_DUPLICATE_COOLDOWN_DAYS=10,
        PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY=2,
        PRESUBMIT_ELIGIBILITY_ENABLED=False,
    )
    params = container.agent_loop._presubmit_safety_params
    assert params.get("max_age_days") == 45
    assert params.get("duplicate_cooldown_days") == 10
    assert params.get("max_apps_per_company_per_day") == 2
    assert params.get("eligibility_enabled") is False
    # DigestService's digest-row warning preview shares the SAME live object, not
    # a second independently-drifting copy.
    assert container.digest_service._presubmit_safety_params is params


def test_presubmit_max_apps_per_company_per_day_live_reread_without_rebuild():
    container = _build(PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY=3)
    params = container.agent_loop._presubmit_safety_params
    assert params.get("max_apps_per_company_per_day") == 3

    container.setup_service.set_automation_prefs(
        presubmit_max_apps_per_company_per_day=1
    )
    # SAME container, SAME params object -- no rebuild -- now reflects the save.
    assert params.get("max_apps_per_company_per_day") == 1


def test_presubmit_max_age_days_live_reread_without_rebuild():
    container = _build(PRESUBMIT_MAX_LISTING_AGE_DAYS=90)
    params = container.agent_loop._presubmit_safety_params
    assert params.get("max_age_days") == 90

    container.setup_service.set_automation_prefs(presubmit_max_listing_age_days=14)
    assert params.get("max_age_days") == 14


def test_presubmit_duplicate_cooldown_days_live_reread_without_rebuild():
    container = _build(PRESUBMIT_DUPLICATE_COOLDOWN_DAYS=30)
    params = container.agent_loop._presubmit_safety_params
    assert params.get("duplicate_cooldown_days") == 30

    container.setup_service.set_automation_prefs(presubmit_duplicate_cooldown_days=0)
    assert params.get("duplicate_cooldown_days") == 0


def test_presubmit_eligibility_enabled_live_reread_without_rebuild():
    container = _build(PRESUBMIT_ELIGIBILITY_ENABLED=True)
    params = container.agent_loop._presubmit_safety_params
    assert params.get("eligibility_enabled") is True

    container.setup_service.set_automation_prefs(presubmit_eligibility_enabled=False)
    assert params.get("eligibility_enabled") is False


def test_presubmit_live_override_actually_changes_the_check_verdict():
    """Not just a ``.get()`` echo: feeding the SAME container-built params object
    into the real ``check_per_company_volume_cap`` -- exactly as ``AgentLoop.
    _process_approvals`` and ``DigestService`` both do -- produces a DIFFERENT
    block/no-block verdict after a Settings save, with NO container rebuild."""
    container = _build(PRESUBMIT_MAX_APPS_PER_COMPANY_PER_DAY=3)
    storage = container.storage
    cid = CampaignId(new_id())
    storage.campaigns.add(Campaign(id=cid, name="C"))
    existing = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="Existing Role",
        company="Acme Corp",
        source_url="https://acme.test/job",
    )
    storage.postings.add(existing)
    storage.applications.add(
        Application(
            id=ApplicationId(new_id()),
            campaign_id=cid,
            posting_id=existing.id,
            status=ApplicationState.APPROVED,
            created_at=datetime.now(UTC),
        )
    )
    new_posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=cid,
        title="New Role",
        company="Acme Corp",
        source_url="https://acme.test/job2",
    )
    storage.postings.add(new_posting)
    storage.commit()

    params = container.agent_loop._presubmit_safety_params
    # Default cap 3, only 1 existing application today -- not blocked yet.
    check_per_company_volume_cap(
        cid, new_posting, storage,
        max_per_day=params.get("max_apps_per_company_per_day", 3),
    )  # must not raise

    container.setup_service.set_automation_prefs(
        presubmit_max_apps_per_company_per_day=1
    )
    with pytest.raises(PresubmitBlock):
        check_per_company_volume_cap(
            cid, new_posting, storage,
            max_per_day=params.get("max_apps_per_company_per_day", 3),
        )


# ---------------------------------------------------------------------------
# #22b -- ats_match_rate_floor (PrefillService)
# ---------------------------------------------------------------------------


def test_ats_match_rate_floor_falls_back_to_settings_when_unset():
    container = _build(ATS_MATCH_RATE_FLOOR=0.55)
    assert container.prefill_service._effective_match_rate_floor() == pytest.approx(0.55)


def test_ats_match_rate_floor_live_reread_without_rebuild():
    container = _build(ATS_MATCH_RATE_FLOOR=0.2)
    pf = container.prefill_service
    assert pf._effective_match_rate_floor() == pytest.approx(0.2)

    container.setup_service.set_automation_prefs(ats_match_rate_floor=0.9)
    assert pf._effective_match_rate_floor() == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# #23 -- approval-gate timeout (DbosOrchestrator, container-built live-getter)
# ---------------------------------------------------------------------------
# NOTE: the ``dbos`` package is an optional extra not installed in the hermetic
# lane, and ``build_container`` registers durable workflows on the real
# orchestrator it builds (which would import ``dbos`` for a real
# ``ORCHESTRATOR_BACKEND=dbos`` container). So these tests build a normal
# (default ``shim``) container to get a REAL, wired ``setup_service``, then call
# the container's own ``_build_orchestrator`` helper directly (which only
# constructs ``DbosOrchestrator`` -- no registration/launch, no ``dbos`` import)
# to exercise the live-getter it wires in.


def test_approval_timeout_falls_back_to_settings_when_nothing_saved():
    container = _build(APPROVAL_TIMEOUT_DAYS=7)
    dbos_settings = Settings(
        _env_file=None, APPROVAL_TIMEOUT_DAYS=7, ORCHESTRATOR_BACKEND="dbos"
    )
    orch = _build_orchestrator(dbos_settings, container.setup_service)
    assert orch._resolve_timeout_seconds(None) == pytest.approx(7 * 86_400)


def test_approval_timeout_days_live_reread_without_rebuild():
    container = _build(APPROVAL_TIMEOUT_DAYS=30)
    dbos_settings = Settings(
        _env_file=None, APPROVAL_TIMEOUT_DAYS=30, ORCHESTRATOR_BACKEND="dbos"
    )
    orch = _build_orchestrator(dbos_settings, container.setup_service)
    assert orch._resolve_timeout_seconds(None) == pytest.approx(30 * 86_400)

    # SAME orchestrator instance, SAME setup_service -- no rebuild -- honors the
    # live save on the very next call.
    container.setup_service.set_automation_prefs(approval_timeout_days=5)
    assert orch._resolve_timeout_seconds(None) == pytest.approx(5 * 86_400)


def test_approval_wait_seconds_precedence_and_live_reread():
    container = _build()
    dbos_settings = Settings(_env_file=None, ORCHESTRATOR_BACKEND="dbos")
    orch = _build_orchestrator(dbos_settings, container.setup_service)

    container.setup_service.set_automation_prefs(approval_wait_seconds=120.0)
    # #189 precedence: the per-second override wins over the days-based setting.
    assert orch._resolve_timeout_seconds(None) == pytest.approx(120.0)


def test_explicit_timeout_arg_still_wins_over_live_override():
    """An explicit per-call ``timeout`` (as the pipeline's ``ctx.approval_timeout``
    supplies) must still take precedence -- the live re-read only fills in when the
    caller passes ``None`` (unchanged behavior)."""
    container = _build()
    container.setup_service.set_automation_prefs(approval_timeout_days=1)
    dbos_settings = Settings(_env_file=None, ORCHESTRATOR_BACKEND="dbos")
    orch = _build_orchestrator(dbos_settings, container.setup_service)
    assert orch._resolve_timeout_seconds(42.0) == 42.0


def test_no_setup_service_falls_back_to_static_constructor_value():
    """Legacy/direct construction without a container (``setup_service=None``)
    stays byte-identical to the pre-fix behavior: only the constructor snapshot
    is ever consulted."""
    settings = Settings(
        _env_file=None, APPROVAL_TIMEOUT_DAYS=12, ORCHESTRATOR_BACKEND="dbos"
    )
    orch = _build_orchestrator(settings, None)
    assert orch._resolve_timeout_seconds(None) == pytest.approx(12 * 86_400)
