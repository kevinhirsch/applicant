"""Required-to-apply hard gate (the minimal-form directive).

The onboarding FORM requires virtually nothing — only "connect a model" lets setup
BEGIN — but autonomous applying (discovery -> apply) is BLOCKED until the
required-to-apply essentials exist (target roles, work mode, locations, salary
floor, key skills, and a résumé). These tests prove:

* the core rule reports exactly the missing essentials, never fabricated;
* ``OnboardingService.apply_readiness`` derives those from REAL criteria + résumé;
* the gate (``SetupService.is_automated_work_allowed``) stays CLOSED while any
  essential is missing and opens EXACTLY when the required set completes;
* the minimal path (LLM only, no profile) lets setup begin but keeps applying
  blocked, and setup-status surfaces the remaining items + a plain reason.
"""

from __future__ import annotations

import pytest

from applicant.adapters.resume_parser.resume_parser import ResumeParser
from applicant.adapters.storage.app_config_store import InMemoryAppConfigStore
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.onboarding_service import OnboardingService
from applicant.application.services.setup_service import SetupService
from applicant.core.entities.campaign import Campaign
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import CampaignId
from applicant.core.rules.apply_readiness import (
    LABEL_KEY_SKILLS,
    LABEL_LOCATIONS,
    LABEL_RESUME,
    LABEL_SALARY_FLOOR,
    LABEL_TARGET_ROLES,
    LABEL_WORK_MODE,
    evaluate_apply_readiness,
)

CID = "camp-apply"


class _FakeCriteria:
    """A criteria service whose ``get_criteria`` returns a settable snapshot."""

    def __init__(self, criteria: SearchCriteria) -> None:
        self._criteria = criteria

    def get_criteria(self, campaign_id: CampaignId) -> SearchCriteria:
        return self._criteria


def _full_criteria(cid: str) -> SearchCriteria:
    return SearchCriteria(
        campaign_id=CampaignId(cid),
        titles=("Software Engineer",),
        locations=("Remote",),
        work_modes=("remote",),
        salary_floor=120000,
        keywords=("python", "fastapi"),
    )


@pytest.fixture
def onboarding():
    storage = InMemoryStorage()
    storage.campaigns.add(Campaign(id=CampaignId(CID), name="c"))
    store = InMemoryAppConfigStore()
    svc = OnboardingService(storage=storage, config_store=store, resume_parser=ResumeParser())
    return svc, storage, store


# --- core rule ---------------------------------------------------------------


def test_rule_all_present_is_ready():
    r = evaluate_apply_readiness(
        has_titles=True,
        has_work_modes=True,
        has_locations=True,
        has_salary_floor=True,
        has_keywords=True,
        has_resume=True,
    )
    assert r.ready is True
    assert r.missing == ()


def test_rule_reports_exact_missing_in_stable_order():
    r = evaluate_apply_readiness(
        has_titles=False,
        has_work_modes=False,
        has_locations=False,
        has_salary_floor=False,
        has_keywords=False,
        has_resume=False,
    )
    assert r.ready is False
    assert r.missing == (
        LABEL_TARGET_ROLES,
        LABEL_WORK_MODE,
        LABEL_LOCATIONS,
        LABEL_SALARY_FLOOR,
        LABEL_KEY_SKILLS,
        LABEL_RESUME,
    )
    assert "To start applying, I still need" in r.reason
    # No FR-/NFR- jargon in the user-facing reason.
    assert "FR-" not in r.reason and "NFR-" not in r.reason


def test_rule_single_missing():
    r = evaluate_apply_readiness(
        has_titles=True,
        has_work_modes=True,
        has_locations=True,
        has_salary_floor=False,
        has_keywords=True,
        has_resume=True,
    )
    assert r.ready is False
    assert r.missing == (LABEL_SALARY_FLOOR,)


# --- onboarding-service readiness from real data -----------------------------


def test_readiness_blocked_with_no_data(onboarding):
    svc, *_ = onboarding
    svc.set_criteria_service(_FakeCriteria(SearchCriteria(campaign_id=CampaignId(CID))))
    r = svc.apply_readiness(CID)
    assert r.ready is False
    # Every essential is missing when nothing has been gathered.
    assert set(r.missing) == {
        LABEL_TARGET_ROLES,
        LABEL_WORK_MODE,
        LABEL_LOCATIONS,
        LABEL_SALARY_FLOOR,
        LABEL_KEY_SKILLS,
        LABEL_RESUME,
    }
    assert svc.is_ready_to_apply(CID) is False


def test_readiness_only_resume_missing(onboarding):
    svc, *_ = onboarding
    svc.set_criteria_service(_FakeCriteria(_full_criteria(CID)))
    r = svc.apply_readiness(CID)
    # Criteria are complete but no résumé ingested yet -> blocked on the résumé only.
    assert r.ready is False
    assert r.missing == (LABEL_RESUME,)


def test_readiness_ready_when_resume_present(onboarding):
    svc, storage, store = onboarding
    svc.set_criteria_service(_FakeCriteria(_full_criteria(CID)))
    # Simulate a base résumé having been ingested (the real signal has_base_resume reads).
    rec = store.get(f"onboarding.{CID}") or {"intake": {}}
    rec.setdefault("intake", {})["base_resume"] = {
        "document_path": "/tmp/r.pdf",
        "parsed": True,
    }
    store.set(f"onboarding.{CID}", rec)
    assert svc.has_base_resume(CID) is True
    r = svc.apply_readiness(CID)
    assert r.ready is True
    assert r.missing == ()
    assert svc.is_ready_to_apply(CID) is True


def test_free_text_statement_satisfies_roles_and_skills(onboarding):
    svc, *_ = onboarding
    # A chat-only setup: no typed titles/keywords, just a human-readable statement.
    crit = SearchCriteria(
        campaign_id=CampaignId(CID),
        human_readable="Remote senior python roles paying at least 120k",
        locations=("Remote",),
        work_modes=("remote",),
        salary_floor=120000,
    )
    svc.set_criteria_service(_FakeCriteria(crit))
    r = svc.apply_readiness(CID)
    # Roles + key skills are covered by the statement; only the résumé remains.
    assert r.missing == (LABEL_RESUME,)


# --- gate integration --------------------------------------------------------


def _setup_with_gate(onboarding):
    svc, storage, store = onboarding
    svc.set_criteria_service(_FakeCriteria(_full_criteria(CID)))

    def _gate() -> bool:
        return svc.is_ready_to_apply(CID)

    def _reporter():
        return svc.apply_readiness(CID)

    setup = SetupService(
        llm_configured=True,  # model connected (the only thing that lets setup begin)
        config_store=InMemoryAppConfigStore(),
        onboarding_gate=_gate,
    )
    setup.set_apply_readiness_reporter(_reporter)
    return setup, svc, store


def test_gate_closed_while_essential_missing(onboarding):
    setup, svc, store = _setup_with_gate(onboarding)
    # LLM is configured but the résumé essential is still missing -> BLOCKED.
    assert setup.is_setup_gate_open() is True  # setup may BEGIN (model connected)
    assert setup.is_automated_work_allowed() is False  # applying is hard-gated
    readiness = setup.apply_readiness()
    assert readiness.ready is False
    assert LABEL_RESUME in readiness.missing


def test_gate_opens_exactly_when_required_set_completes(onboarding):
    setup, svc, store = _setup_with_gate(onboarding)
    assert setup.is_automated_work_allowed() is False
    # Complete the LAST missing essential (the résumé).
    rec = store.get(f"onboarding.{CID}") or {"intake": {}}
    rec.setdefault("intake", {})["base_resume"] = {"document_path": "/tmp/r.pdf", "parsed": True}
    store.set(f"onboarding.{CID}", rec)
    # Now — and only now — the gate opens.
    assert setup.is_automated_work_allowed() is True
    assert setup.apply_readiness().ready is True


def test_minimal_path_begins_setup_but_blocks_applying(onboarding):
    """Connect-a-model only: setup gate open, but applying stays blocked."""
    svc, storage, store = onboarding
    # No criteria gathered, no résumé — a brand-new user who only connected a model.
    svc.set_criteria_service(_FakeCriteria(SearchCriteria(campaign_id=CampaignId(CID))))

    def _gate() -> bool:
        return svc.is_ready_to_apply(CID)

    setup = SetupService(
        llm_configured=True,
        config_store=InMemoryAppConfigStore(),
        onboarding_gate=_gate,
    )
    setup.set_apply_readiness_reporter(lambda: svc.apply_readiness(CID))
    assert setup.is_setup_gate_open() is True
    assert setup.is_automated_work_allowed() is False
    r = setup.apply_readiness()
    assert r.ready is False
    assert LABEL_TARGET_ROLES in r.missing  # status surfaces the remaining items


def test_apply_readiness_none_without_reporter():
    setup = SetupService(llm_configured=True, config_store=InMemoryAppConfigStore())
    # No reporter wired -> readiness payload omitted; gate behavior unchanged.
    assert setup.apply_readiness() is None


# --- setup-status surface (reachable via the real app) -----------------------


def test_setup_status_surfaces_remaining_required_items():
    """The status payload reports the missing essentials + reason once a campaign exists."""
    from fastapi.testclient import TestClient

    from applicant.app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        # Connect a model so setup may begin + a campaign can be created.
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434", "model": "llama3"},
        )
        assert r.status_code in (200, 204)
        cr = c.post("/api/campaigns", json={"name": "My job search"})
        assert cr.status_code < 300, cr.text

        status = c.get("/api/setup/status").json()
        # The model is connected (setup may begin) but applying is still blocked:
        # a fresh campaign has no salary floor or résumé yet.
        assert status["llm_configured"] is True
        assert status["automated_work_allowed"] is False
        assert status["apply_ready"] is False
        # The status surfaces the REAL remaining essentials (not fabricated): a
        # brand-new campaign always still lacks the résumé.
        assert isinstance(status["apply_missing"], list) and status["apply_missing"]
        assert LABEL_RESUME in status["apply_missing"]
        assert status["apply_blocked_reason"]
        assert "FR-" not in status["apply_blocked_reason"]
