"""Settings > Automation config-store persistence + router wiring for dark-engine
audit items 91/97/98/99/102/105/106/107, wired into the SAME ``AutomationPrefsIn``
pattern items 82/84/85/87/88 already established:

  * 91 -- ``ats_match_rate_floor`` (mirrors ``ATS_MATCH_RATE_FLOOR``, default 0.2):
    the minimum fields-filled ratio below which an application is flagged for
    review instead of offered for submit.
  * 97 -- ``presubmit_eligibility_enabled`` (mirrors
    ``PRESUBMIT_ELIGIBILITY_ENABLED``, default True): whether postings are
    filtered on work-authorization/sponsorship/clearance requirements.
  * 98 -- ``presubmit_max_listing_age_days`` (mirrors
    ``PRESUBMIT_MAX_LISTING_AGE_DAYS``, default 90): blocks postings older
    than this.
  * 99 -- ``memory_write_approval``/``skills_write_approval`` (mirror
    ``MEMORY_WRITE_APPROVAL``/``SKILLS_WRITE_APPROVAL``, default True each)
    and ``memory_max_chars``/``user_max_chars`` (mirror ``MEMORY_MAX_CHARS``/
    ``USER_MAX_CHARS``, default 8000/4000): auto-apply vs staged memory
    writes, and the prompt budget.
  * 102 -- ``llm_smart_routing_prefer_local`` (mirrors
    ``LLM_SMART_ROUTING_PREFER_LOCAL``, default True): whether the smart
    router's tier ladder prefers a local endpoint.
  * 105 -- ``context_compress_threshold`` (mirrors
    ``CONTEXT_COMPRESS_THRESHOLD``, default 64000; 0 disables).
  * 106 -- ``loop_failure_alert_threshold`` (mirrors
    ``LOOP_FAILURE_ALERT_THRESHOLD``, default 3).
  * 107 -- ``prefill_use_planner`` (mirrors ``PREFILL_USE_PLANNER``, default
    False): experimental plan-as-data prefill planner flag.

Two layers of coverage, matching the shape of ``test_automation_prefs_
retention_cooldown.py`` (service-level) plus ``test_retention_sweep_route.py``
(router-level, real ``create_app()``):

  1. ``SetupService.get_automation_prefs``/``set_automation_prefs`` directly
     (config-store persistence + validation), and
  2. ``GET``/``PUT /api/setup/automation`` through a real app so the
     env-default merge in the router (``get_automation_prefs`` in
     ``setup.py``) is proven, not just the service.

Each assertion here was hand-verified to go RED when the corresponding piece
of the wiring is reverted (file-copy backup, not ``git stash`` -- shared
across sibling worktrees in this session), then GREEN again after restoring.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.app.main import create_app
from applicant.application.services.setup_service import SetupService


def _svc(store=None) -> SetupService:
    return SetupService(config_store=store or InMemoryAppConfigStore())


# ── SetupService: persistence + validation ─────────────────────────────────


def test_get_automation_prefs_is_empty_before_anything_is_saved():
    svc = _svc()
    prefs = svc.get_automation_prefs()
    for key in (
        "ats_match_rate_floor",
        "presubmit_eligibility_enabled",
        "presubmit_max_listing_age_days",
        "memory_write_approval",
        "skills_write_approval",
        "memory_max_chars",
        "user_max_chars",
        "llm_smart_routing_prefer_local",
        "context_compress_threshold",
        "loop_failure_alert_threshold",
        "prefill_use_planner",
    ):
        assert key not in prefs


def test_set_then_get_round_trips_all_new_knobs():
    svc = _svc()
    svc.set_automation_prefs(
        ats_match_rate_floor=0.5,
        presubmit_eligibility_enabled=False,
        presubmit_max_listing_age_days=30,
        memory_write_approval=False,
        skills_write_approval=False,
        memory_max_chars=12000,
        user_max_chars=6000,
        llm_smart_routing_prefer_local=False,
        context_compress_threshold=32000,
        loop_failure_alert_threshold=5,
        prefill_use_planner=True,
    )
    prefs = svc.get_automation_prefs()
    assert prefs["ats_match_rate_floor"] == 0.5
    assert prefs["presubmit_eligibility_enabled"] is False
    assert prefs["presubmit_max_listing_age_days"] == 30
    assert prefs["memory_write_approval"] is False
    assert prefs["skills_write_approval"] is False
    assert prefs["memory_max_chars"] == 12000
    assert prefs["user_max_chars"] == 6000
    assert prefs["llm_smart_routing_prefer_local"] is False
    assert prefs["context_compress_threshold"] == 32000
    assert prefs["loop_failure_alert_threshold"] == 5
    assert prefs["prefill_use_planner"] is True


def test_boundary_values_are_allowed():
    """0.0/1.0 fill-rate floor, 0-day listing age, 0 compression threshold, and
    threshold-of-1 are legitimate documented edge values, not errors."""
    svc = _svc()
    svc.set_automation_prefs(ats_match_rate_floor=0.0)
    assert svc.get_automation_prefs()["ats_match_rate_floor"] == 0.0
    svc.set_automation_prefs(ats_match_rate_floor=1.0)
    assert svc.get_automation_prefs()["ats_match_rate_floor"] == 1.0
    svc.set_automation_prefs(presubmit_max_listing_age_days=0)
    assert svc.get_automation_prefs()["presubmit_max_listing_age_days"] == 0
    svc.set_automation_prefs(context_compress_threshold=0)
    assert svc.get_automation_prefs()["context_compress_threshold"] == 0
    svc.set_automation_prefs(loop_failure_alert_threshold=1)
    assert svc.get_automation_prefs()["loop_failure_alert_threshold"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ats_match_rate_floor": -0.01},
        {"ats_match_rate_floor": 1.01},
        {"presubmit_max_listing_age_days": -1},
        {"memory_max_chars": 0},
        {"memory_max_chars": -100},
        {"user_max_chars": 0},
        {"user_max_chars": -1},
        {"context_compress_threshold": -1},
        {"loop_failure_alert_threshold": 0},
        {"loop_failure_alert_threshold": -3},
    ],
)
def test_invalid_ranges_are_rejected(kwargs):
    svc = _svc()
    with pytest.raises(ValueError):
        svc.set_automation_prefs(**kwargs)
    # Rejected write must not partially land.
    assert svc.get_automation_prefs() == {}


def test_partial_save_of_new_knobs_leaves_existing_knobs_untouched():
    svc = _svc()
    svc.set_automation_prefs(egress_timezone="America/New_York", ats_match_rate_floor=0.3)
    svc.set_automation_prefs(loop_failure_alert_threshold=7)
    prefs = svc.get_automation_prefs()
    assert prefs["egress_timezone"] == "America/New_York"  # untouched
    assert prefs["ats_match_rate_floor"] == 0.3  # untouched by the second call
    assert prefs["loop_failure_alert_threshold"] == 7  # newly set
    assert "presubmit_max_listing_age_days" not in prefs  # never touched


def test_state_persists_across_instances_over_the_same_store():
    """Simulated restart (FR-OOBE-1 pattern): a fresh SetupService over the
    same AppConfigStore must see the prior save."""
    store = InMemoryAppConfigStore()
    svc1 = _svc(store)
    svc1.set_automation_prefs(
        memory_write_approval=False,
        skills_write_approval=True,
        prefill_use_planner=True,
    )
    svc2 = _svc(store)
    prefs = svc2.get_automation_prefs()
    assert prefs["memory_write_approval"] is False
    assert prefs["skills_write_approval"] is True
    assert prefs["prefill_use_planner"] is True


# ── Router: GET/PUT /api/setup/automation over a real app ──────────────────


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        # Open the LLM gate (the router carries require_llm_configured).
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_get_defaults_to_settings_values_when_nothing_persisted(client):
    """Before any operator save, GET must reflect the real env-sourced
    ``Settings`` defaults (config.py), not a fabricated/omitted value."""
    prefs = client.get("/api/setup/automation").json()
    assert prefs["ats_match_rate_floor"] == pytest.approx(0.2)
    assert prefs["presubmit_eligibility_enabled"] is True
    assert prefs["presubmit_max_listing_age_days"] == 90
    assert prefs["memory_write_approval"] is True
    assert prefs["skills_write_approval"] is True
    assert prefs["memory_max_chars"] == 8000
    assert prefs["user_max_chars"] == 4000
    assert prefs["llm_smart_routing_prefer_local"] is True
    assert prefs["context_compress_threshold"] == 64000
    assert prefs["loop_failure_alert_threshold"] == 3
    assert prefs["prefill_use_planner"] is False


def test_put_persists_and_round_trips_on_next_get(client):
    put = client.put(
        "/api/setup/automation",
        json={
            "ats_match_rate_floor": 0.4,
            "presubmit_eligibility_enabled": False,
            "presubmit_max_listing_age_days": 45,
            "memory_write_approval": False,
            "skills_write_approval": False,
            "memory_max_chars": 5000,
            "user_max_chars": 2000,
            "llm_smart_routing_prefer_local": False,
            "context_compress_threshold": 16000,
            "loop_failure_alert_threshold": 8,
            "prefill_use_planner": True,
        },
    )
    assert put.status_code == 204

    prefs = client.get("/api/setup/automation").json()
    assert prefs["ats_match_rate_floor"] == pytest.approx(0.4)
    assert prefs["presubmit_eligibility_enabled"] is False
    assert prefs["presubmit_max_listing_age_days"] == 45
    assert prefs["memory_write_approval"] is False
    assert prefs["skills_write_approval"] is False
    assert prefs["memory_max_chars"] == 5000
    assert prefs["user_max_chars"] == 2000
    assert prefs["llm_smart_routing_prefer_local"] is False
    assert prefs["context_compress_threshold"] == 16000
    assert prefs["loop_failure_alert_threshold"] == 8
    assert prefs["prefill_use_planner"] is True


@pytest.mark.parametrize(
    "body,message_fragment",
    [
        ({"ats_match_rate_floor": -0.1}, "0.0 and 1.0"),
        ({"ats_match_rate_floor": 1.5}, "0.0 and 1.0"),
        ({"presubmit_max_listing_age_days": -5}, "negative"),
        ({"memory_max_chars": 0}, "positive"),
        ({"user_max_chars": -50}, "positive"),
        ({"context_compress_threshold": -1}, "negative"),
        ({"loop_failure_alert_threshold": 0}, "at least 1"),
    ],
)
def test_put_rejects_invalid_ranges_with_400(client, body, message_fragment):
    resp = client.put("/api/setup/automation", json=body)
    assert resp.status_code == 400
    assert message_fragment in resp.json()["detail"]
