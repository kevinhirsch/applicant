"""Unit tests for Phase 4 services + the dormant-surface registry.

* ChatService: gap finding, confirmation-gated integral proposals, non-integral
  auto-apply, offline degrade (FR-CHAT-1 / FR-FB-3).
* AdminQueryService: real history / screenshots / workflow / variant read-models
  (FR-OBS-2 / FR-LOG-3 / FR-UI-6 / FR-RESUME-6).
* Dormant registry: registry/UI consistency + live-status correctness (FR-UI-2).
"""

from __future__ import annotations

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.admin_query_service import AdminQueryService
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.chat_service import ChatService
from applicant.application.services.criteria_service import CriteriaService
from applicant.core.entities.application import Application
from applicant.core.entities.application_screenshot import ApplicationScreenshot
from applicant.core.entities.resume_variant import ResumeVariant
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    ResumeVariantId,
    ScreenshotId,
    new_id,
)
from applicant.core.state_machine import ApplicationState
from applicant.dormant import DORMANT_SURFACES, STATUS_DORMANT, STATUS_LIVE


def _chat_service():
    storage = InMemoryStorage()
    attrs = AttributeCloudService(storage)
    criteria = CriteriaService(storage)
    # No LLM -> deterministic offline reply (FR-CHAT-1 degrade).
    return ChatService(attribute_service=attrs, criteria_service=criteria, llm=None), storage


# === ChatService (FR-CHAT-1 / FR-FB-3) ====================================
def test_chat_identifies_core_attribute_gaps():
    svc, _ = _chat_service()
    cid = CampaignId(new_id())
    gaps = svc.identify_gaps(cid)
    assert "first name" in gaps and "email address" in gaps
    assert "target roles / search criteria" in gaps


def test_chat_integral_proposal_requires_confirmation():
    svc, _ = _chat_service()
    cid = CampaignId(new_id())
    result = svc.converse(cid, "my first name is Kevin")
    assert len(result.proposed_changes) == 1
    prop = result.proposed_changes[0]
    assert prop.is_integral is True
    assert prop.requires_confirmation is True
    assert prop.applied is False  # never auto-committed


def test_chat_non_integral_proposal_autoapplies():
    svc, storage = _chat_service()
    cid = CampaignId(new_id())
    result = svc.converse(cid, "my years of experience is 8")
    prop = result.proposed_changes[0]
    assert prop.requires_confirmation is False
    assert prop.applied is True
    assert svc.identify_gaps(cid)  # still some core gaps remain
    assert any(a.name == "years of experience" for a in storage.attributes.list_for_campaign(cid))


def test_chat_confirm_commits_integral_change():
    svc, storage = _chat_service()
    cid = CampaignId(new_id())
    svc.converse(cid, "my first name is Kevin")
    attr = svc.confirm_change(cid, "first name", "Kevin")
    assert attr.value == "Kevin"
    assert attr.is_integral is True


def test_chat_offline_reply_is_deterministic():
    svc, _ = _chat_service()
    cid = CampaignId(new_id())
    result = svc.converse(cid, "hello")
    assert "confirmation" in result.message.lower()


def test_chat_sensitive_value_is_not_autoapplied():
    svc, storage = _chat_service()
    cid = CampaignId(new_id())
    # A sensitive attribute (EEO-style) must never be auto-applied (FR-ATTR-6).
    result = svc.converse(cid, "my race is prefer-not-to-say")
    prop = result.proposed_changes[0]
    assert prop.is_sensitive is True
    assert prop.applied is False
    assert prop.requires_confirmation is True


# === AdminQueryService (FR-OBS-2 / FR-LOG-3 / FR-UI-6) =====================
def _storage_with_app():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    storage.applications.add(
        Application(
            id=aid,
            campaign_id=cid,
            posting_id=JobPostingId(new_id()),
            status=ApplicationState.PREFILLING,
            role_name="Senior Engineer",
            work_mode="remote",
        )
    )
    storage.screenshots.add(
        ApplicationScreenshot(
            id=ScreenshotId(new_id()), application_id=aid, page_ref="page-1", page_url="file://1"
        )
    )
    storage.commit()
    return storage, cid, aid


def test_admin_history_reflects_real_application():
    storage, cid, aid = _storage_with_app()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert len(rows) == 1
    assert rows[0]["application_id"] == str(aid)
    assert rows[0]["screenshot_count"] == 1
    assert rows[0]["role_name"] == "Senior Engineer"


def test_admin_screenshots_returns_real_rows():
    storage, cid, aid = _storage_with_app()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    shots = svc.screenshots(aid)
    assert len(shots) == 1 and shots[0]["page_ref"] == "page-1"


def test_admin_workflow_state_introspects_orchestrator():
    storage, cid, aid = _storage_with_app()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    state = svc.workflow_state(aid)
    assert state["workflow_id"] == f"application:{aid}"
    assert state["pending_recovery"] is False


def test_admin_variant_library_reports_lineage():
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    root = ResumeVariant(id=ResumeVariantId(new_id()), campaign_id=cid, storage_path="root.tex")
    child = ResumeVariant(
        id=ResumeVariantId(new_id()),
        campaign_id=cid,
        storage_path="child.tex",
        parent_id=root.id,
        approved=True,
        fit_scores={"posting-1": 0.8},
    )
    storage.resume_variants.add(root)
    storage.resume_variants.add(child)
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    lib = {v["variant_id"]: v for v in svc.variant_library(cid)}
    assert lib[str(root.id)]["is_root"] is True
    assert lib[str(child.id)]["lineage_depth"] == 1
    assert lib[str(child.id)]["approved"] is True


# === Tool-toggle enforcement at service dispatch (FR-UI-4) ================
def test_discovery_dispatch_blocked_when_tool_disabled():
    import pytest

    from applicant.adapters.discovery.factory import build_default_discovery
    from applicant.adapters.embedding.local_embedding import LocalEmbedding
    from applicant.adapters.tools.tool_registry import ToolDisabledError, ToolRegistry
    from applicant.application.services.discovery_service import DiscoveryService

    storage = InMemoryStorage()
    reg = ToolRegistry()
    svc = DiscoveryService(
        storage, build_default_discovery(), LocalEmbedding(), tool_registry=reg
    )
    cid = CampaignId(new_id())
    # Enabled -> dispatch runs (returns a list, possibly empty).
    assert isinstance(svc.run_discovery(cid), list)
    # Disabled -> dispatch is blocked at the boundary (FR-UI-4).
    reg.set_enabled("discovery", False)
    with pytest.raises(ToolDisabledError):
        svc.run_discovery(cid)


def test_scoring_dispatch_blocked_when_tool_disabled():
    import pytest

    from applicant.adapters.embedding.local_embedding import LocalEmbedding
    from applicant.adapters.tools.tool_registry import ToolDisabledError, ToolRegistry
    from applicant.application.services.scoring_service import ScoringService
    from applicant.core.entities.job_posting import JobPosting
    from applicant.core.ids import JobPostingId

    storage = InMemoryStorage()
    reg = ToolRegistry()
    svc = ScoringService(storage, None, LocalEmbedding(), tool_registry=reg)
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=CampaignId(new_id()),
        title="Engineer",
        company="Acme",
        source_url="https://example.com/job",
        description="Build things",
    )
    svc.score_posting(posting)  # enabled -> ok
    reg.set_enabled("scoring", False)
    with pytest.raises(ToolDisabledError):
        svc.score_posting(posting)


# === Dormant registry / UI consistency (FR-UI-2) ==========================
def test_dormant_registry_statuses_are_valid():
    for s in DORMANT_SURFACES:
        assert s.status in (STATUS_LIVE, STATUS_DORMANT)
        assert s.requirement_ids  # every surface cites >=1 requirement
        assert s.wiring_notes


def test_dormant_registry_keys_present_in_debug_or_other_surface():
    """Every registered surface is present in the UI (FR-UI-2: no dead/missing UI).

    The debug surface hosts the Phase 4 panels (tools, history, debug, update,
    variant library, aggressiveness, multi-campaign switcher); the remaining
    surfaces (digest, redline, remote takeover) live on their own dedicated pages.
    """
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "static" / "applicant"
    debug_html = (frontend / "debug.html").read_text(encoding="utf-8")
    # Surfaces represented on the debug surface.
    for token in ("tools-section", "history-section", "update-section", "variants-section",
                  "aggressiveness-section", "campaign-switcher-section"):
        assert token in debug_html
    # Surfaces represented on dedicated pages.
    assert (frontend / "digest.html").is_file()  # digest_in_app
    assert (frontend / "review.html").is_file()  # redline_surface
    assert (frontend / "chat.html").is_file()  # chatbot
    assert (frontend / "criteria.html").is_file()  # criteria_editor (FR-UI-6)
    assert (frontend / "attributes.html").is_file()  # attribute_editor (FR-UI-6)


def test_live_surfaces_have_no_lingering_dormant_class_in_their_panel():
    """A surface flipped to live must not be grayed (FR-UI-2)."""
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend" / "static" / "applicant"
    debug_html = (frontend / "debug.html").read_text(encoding="utf-8")
    # The live logs/screenshots/variants sections carry the on-badge, not the
    # applicant-dormant class.
    for section_id in ("logs-section", "screenshots-section", "variants-section"):
        idx = debug_html.index(f'id="{section_id}"')
        # Walk back to the opening <section ...> tag for this id.
        section_open = debug_html.rfind("<section", 0, idx)
        section_tag = debug_html[section_open:idx]
        assert "applicant-dormant" not in section_tag


# === #14: admin history batches screenshots/outcomes + supports limit =======
def test_admin_history_batches_via_campaign_queries():
    """#14: application_history uses screenshots.list_for_campaign +
    outcomes.list_for_campaign (one query each) instead of per-application N+1."""
    storage, cid, aid = _storage_with_app()

    calls = {"shots_campaign": 0, "outcomes_campaign": 0, "shots_app": 0, "outcomes_app": 0}

    real_shot_app = storage.screenshots.list_for_application
    real_out_app = storage.outcomes.list_for_application

    def _shots_campaign(campaign_id):
        calls["shots_campaign"] += 1
        return [s for a in storage.applications.list_for_campaign(campaign_id)
                for s in real_shot_app(a.id)]

    def _outcomes_campaign(campaign_id):
        calls["outcomes_campaign"] += 1
        return [o for a in storage.applications.list_for_campaign(campaign_id)
                for o in real_out_app(a.id)]

    def _shot_app(aid):
        calls["shots_app"] += 1
        return real_shot_app(aid)

    def _out_app(aid):
        calls["outcomes_app"] += 1
        return real_out_app(aid)

    storage.screenshots.list_for_campaign = _shots_campaign
    storage.outcomes.list_for_campaign = _outcomes_campaign
    storage.screenshots.list_for_application = _shot_app
    storage.outcomes.list_for_application = _out_app

    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    rows = svc.application_history(cid)
    assert len(rows) == 1 and rows[0]["screenshot_count"] == 1
    # Batched: exactly one campaign-wide query each, no per-application calls.
    assert calls["shots_campaign"] == 1 and calls["outcomes_campaign"] == 1
    assert calls["shots_app"] == 0 and calls["outcomes_app"] == 0


def test_admin_history_respects_limit():
    """#14: application_history bounds returned rows by limit."""
    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    for _i in range(5):
        storage.applications.add(
            Application(
                id=ApplicationId(new_id()),
                campaign_id=cid,
                posting_id=JobPostingId(new_id()),
                status=ApplicationState.PREFILLING,
            )
        )
    storage.commit()
    svc = AdminQueryService(storage, CheckpointShimOrchestrator())
    assert len(svc.application_history(cid, limit=2)) == 2
