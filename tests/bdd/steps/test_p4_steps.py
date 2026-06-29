"""Step bindings for the Phase 4 acceptance scenarios (master spec §10).

Maps the §10 anchors to the real Phase 4 surfaces with NO external services:

* "Conversion is approval plus submission" -> AdvancedLearningService closes the
  real-conversion loop on an approval PLUS a submission outcome (auto OR one-tap
  manual mark-submitted), and folds the converting role signature for the next run
  (FR-LEARN-2/3/5, FR-LOG-4); attribute cross-referencing auto-applies non-integral
  values and gates integral ones via the core confirmation gate (FR-LEARN-4/FR-FB-3).
* "Tool registry toggles" -> ToolRegistry default-enabled registry, persisted
  toggle, and dispatch enforcement (FR-UI-4).
* "Dormant surfaces present-but-grayed" -> debug.html ships every panel and grays
  the not-yet-wired ones; pending endpoints never fake data; the Update button is
  safe by default (FR-UI-2, FR-OBS-2, FR-OOBE-4).

Every scenario maps to >=1 requirement ID (cited in the feature files).
Phase-local fixtures live here, not in the shared conftest.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.adapters.tools.tool_registry import ToolDisabledError, ToolRegistry
from applicant.application.services.attribute_cloud_service import AttributeCloudService
from applicant.application.services.campaign_service import CampaignService
from applicant.application.services.learning_advanced import AdvancedLearningService
from applicant.application.services.learning_service import LearningService
from applicant.core.entities.application import Application
from applicant.core.entities.attribute import AttributeStore
from applicant.core.entities.learning_model import LearningModel
from applicant.core.entities.outcome_event import OutcomeEvent, OutcomeSource
from applicant.core.ids import (
    ApplicationId,
    CampaignId,
    JobPostingId,
    OutcomeEventId,
    new_id,
)
from applicant.core.state_machine import ApplicationState

scenarios(
    "../features/p4_conversion_learning.feature",
    "../features/p4_multi_campaign.feature",
    "../features/p4_tool_toggles.feature",
    "../features/p4_dormant_surfaces.feature",
    "../features/p4_chatbot.feature",
    "../features/p4_update_button.feature",
)

_FRONTEND = Path(__file__).resolve().parents[3] / "workspace" / "static"


# --- phase-local fixtures --------------------------------------------------
@pytest.fixture
def p4ctx() -> dict:
    return {}


@pytest.fixture
def advanced() -> AdvancedLearningService:
    # base LearningService needs no real storage/embedding for the folds used here.
    return AdvancedLearningService(base=LearningService(storage=None, embedding=None))


# === Conversion learning (FR-LEARN-2/3/4/5) ================================
@given("a fresh learning model and an approved application")
def fresh_model_and_app(p4ctx):
    cid = CampaignId(new_id())
    aid = ApplicationId(new_id())
    p4ctx["campaign_id"] = cid
    p4ctx["model"] = LearningModel(campaign_id=cid)
    p4ctx["application"] = Application(
        id=aid,
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        role_name="Senior Backend Engineer",
        work_mode="remote",
    )
    p4ctx["outcomes"] = []


@when("no submission outcome has been recorded")
def no_submission(p4ctx):
    # Intentionally leave outcomes empty: approval alone is not a conversion (§10).
    assert p4ctx["outcomes"] == []


@when("a submission outcome event is recorded for the application")
def auto_submission(p4ctx, advanced):
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()),
        application_id=p4ctx["application"].id,
        type="submitted",
        source=OutcomeSource.AUTO,
    )
    p4ctx["outcomes"].append(event)
    p4ctx["model_after"] = advanced.record_conversion(
        p4ctx["model"], p4ctx["application"], p4ctx["outcomes"]
    )


@when("a manual mark-submitted outcome event is recorded for the application")
def manual_submission(p4ctx, advanced):
    event = OutcomeEvent(
        id=OutcomeEventId(new_id()),
        application_id=p4ctx["application"].id,
        type="submitted",
        source=OutcomeSource.MANUAL,
    )
    p4ctx["outcomes"].append(event)
    p4ctx["model_after"] = advanced.record_conversion(
        p4ctx["model"], p4ctx["application"], p4ctx["outcomes"]
    )


@then("the application is not counted as converted")
def not_converted(p4ctx, advanced):
    assert advanced.is_conversion(p4ctx["application"], p4ctx["outcomes"]) is False


@then("the converting role signature stays empty")
def signature_empty(p4ctx, advanced):
    model_after = advanced.record_conversion(
        p4ctx["model"], p4ctx["application"], p4ctx["outcomes"]
    )
    assert model_after.converting_role_signature == {}


@then("the application is counted as converted for the campaign")
def is_converted(p4ctx, advanced):
    # Conversion = approval (state) PLUS submission (outcome event) — §10.
    assert advanced.is_conversion(p4ctx["application"], p4ctx["outcomes"]) is True


@then("the converting role signature is updated for the next run")
def signature_updated(p4ctx):
    sig = p4ctx["model_after"].converting_role_signature
    assert sig  # non-empty
    assert "role:senior backend engineer" in sig
    assert "work_mode:remote" in sig


# === Attribute cross-referencing (FR-LEARN-4 + FR-FB-3) ====================
@given("an empty attribute store for a campaign")
def empty_attr_store(p4ctx):
    cid = CampaignId(new_id())
    p4ctx["campaign_id"] = cid
    p4ctx["store"] = AttributeStore(campaign_id=cid)


@when("an input cross-references a non-integral attribute value")
def xref_non_integral(p4ctx, advanced):
    store, proposal = advanced.cross_reference_attribute(
        p4ctx["store"],
        name="years_python",
        value="8",
        source="resume",
        is_integral=False,
    )
    p4ctx["store"] = store
    p4ctx["proposal"] = proposal


@when("an input cross-references an integral attribute value without confirmation")
def xref_integral_unconfirmed(p4ctx, advanced):
    store, proposal = advanced.cross_reference_attribute(
        p4ctx["store"],
        name="legal_name",
        value="Jane Q. Public",
        source="screening_answer",
        is_integral=True,
        user_confirmed=False,
    )
    p4ctx["store"] = store
    p4ctx["proposal"] = proposal


@then("the non-integral attribute is applied automatically")
def non_integral_applied(p4ctx):
    assert p4ctx["proposal"].applied is True
    assert p4ctx["proposal"].needs_confirmation is False
    assert p4ctx["store"].find("years_python") is not None


@then("the integral attribute is not committed")
def integral_not_committed(p4ctx):
    assert p4ctx["proposal"].applied is False
    assert p4ctx["store"].find("legal_name") is None  # nothing written


@then("the proposal requires user confirmation")
def proposal_needs_confirmation(p4ctx):
    assert p4ctx["proposal"].needs_confirmation is True


# === Conversion persistence + multi-campaign (FR-LEARN-2/5, NFR-EXT-1) =====
@pytest.fixture
def p4_storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def p4_services(p4_storage):
    base = LearningService(p4_storage, LocalEmbedding())
    return {
        "storage": p4_storage,
        "base": base,
        "advanced": AdvancedLearningService(base=base, storage=p4_storage),
        "campaigns": CampaignService(p4_storage),
        "attrs": AttributeCloudService(p4_storage),
    }


def _store_converted_app(storage, campaign_id, job_title="Senior Backend Engineer"):
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=campaign_id,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.APPROVED,
        job_title=job_title,
        work_mode="remote",
    )
    storage.applications.add(app)
    storage.outcomes.add(
        OutcomeEvent(id=OutcomeEventId(new_id()), application_id=app.id, type="submitted")
    )
    storage.commit()
    return app


@given("a stored campaign with an approved application and a submission outcome")
def stored_campaign_with_conversion(p4ctx, p4_services):
    campaign = p4_services["campaigns"].create_campaign("Converter")
    other = p4_services["campaigns"].create_campaign("Bystander")
    p4ctx["campaign"] = campaign
    p4ctx["other_campaign"] = other
    p4ctx["app"] = _store_converted_app(p4_services["storage"], campaign.id)


@when("the conversion loop is closed and the learning state persisted")
def close_and_persist(p4ctx, p4_services):
    p4_services["advanced"].record_and_persist_conversion(
        p4ctx["campaign"].id, p4ctx["app"]
    )


@then("reloading the campaign learning state shows the converting-role signature")
def reload_shows_signature(p4ctx, p4_services):
    reloaded = p4_services["base"].load_model(p4ctx["campaign"].id)
    assert reloaded.converting_role_signature
    assert "role:senior backend engineer" in reloaded.converting_role_signature


@then("a bare approval in another campaign leaves that campaign's signature empty")
def other_campaign_empty(p4ctx, p4_services):
    reloaded = p4_services["base"].load_model(p4ctx["other_campaign"].id)
    assert reloaded.converting_role_signature == {}


@given("two campaigns A and B")
def two_campaigns(p4ctx, p4_services):
    p4ctx["a"] = p4_services["campaigns"].create_campaign("A")
    p4ctx["b"] = p4_services["campaigns"].create_campaign("B")


@when("each campaign stores its own value for the same attribute")
def store_isolated_values(p4ctx, p4_services):
    attrs = p4_services["attrs"]
    attrs.upsert(p4ctx["a"].id, "preferred_location", "Remote")
    attrs.upsert(p4ctx["b"].id, "preferred_location", "Austin, TX")


@when("a field mapping is learned once as shared cross-campaign knowledge")
def learn_shared_mapping(p4ctx, p4_services):
    attrs = p4_services["attrs"]
    a_attr = attrs.get_by_name(p4ctx["a"].id, "preferred_location")
    p4ctx["mapping"] = attrs.bind_field(
        "workday", "#location", attribute_id=a_attr.id, shared=True
    )


@then("each campaign resolves the shared mapping to its own value")
def resolves_per_campaign(p4ctx, p4_services):
    attrs = p4_services["attrs"]
    assert p4ctx["mapping"].is_shared is True
    a = attrs.resolve_attribute_for_field(p4ctx["a"].id, "workday", "#location")
    b = attrs.resolve_attribute_for_field(p4ctx["b"].id, "workday", "#location")
    assert a.value == "Remote" and b.value == "Austin, TX"


@then("only one global field mapping exists for that field")
def one_global_mapping(p4ctx, p4_services):
    assert len(p4_services["storage"].field_mappings.list_for_site("workday")) == 1


@when("campaign A records a real conversion")
def campaign_a_converts(p4ctx, p4_services):
    app = _store_converted_app(p4_services["storage"], p4ctx["a"].id)
    p4_services["advanced"].record_and_persist_conversion(p4ctx["a"].id, app)


@then("campaign A's converting-role signature is learned")
def a_learned(p4ctx, p4_services):
    model = p4_services["base"].load_model(p4ctx["a"].id)
    assert "role:senior backend engineer" in model.converting_role_signature


@then("campaign B's converting-role signature stays empty")
def b_empty(p4ctx, p4_services):
    model = p4_services["base"].load_model(p4ctx["b"].id)
    assert model.converting_role_signature == {}


# === Tool toggles (FR-UI-4) ================================================
@given("a fresh tool registry")
def fresh_registry(p4ctx):
    p4ctx["registry"] = ToolRegistry()


@then("all ten agent tools are present and enabled")
def ten_tools_enabled(p4ctx):
    tools = p4ctx["registry"].all_tools()
    assert len(tools) == 10
    assert all(tools.values()) is True


@when("the operator toggles the discovery tool off")
def toggle_off(p4ctx):
    p4ctx["registry"].set_enabled("discovery", False)


@when("the operator toggles the discovery tool back on")
def toggle_on(p4ctx):
    p4ctx["registry"].set_enabled("discovery", True)


@then("the discovery tool reads as disabled")
def reads_disabled(p4ctx):
    assert p4ctx["registry"].is_enabled("discovery") is False


@then("dispatching the discovery tool is rejected")
def dispatch_rejected(p4ctx):
    with pytest.raises(ToolDisabledError):
        p4ctx["registry"].ensure_enabled("discovery")


@then("dispatching the discovery tool is allowed")
def dispatch_allowed(p4ctx):
    p4ctx["registry"].ensure_enabled("discovery")  # must not raise


# === Dormant surfaces (FR-UI-2 / FR-OBS-2 / FR-OOBE-4) =====================
@given("the rendered debug surface")
def rendered_debug(p4ctx):
    p4ctx["html"] = (_FRONTEND / "debug.html").read_text(encoding="utf-8")


@then("the tool-toggle, history, and update panels are present and live")
def live_panels_present(p4ctx):
    html = p4ctx["html"]
    assert 'id="tools-section"' in html
    assert 'id="history-section"' in html
    assert 'id="update-section"' in html
    # live panels carry the on-badge
    assert "admin-badge-on" in html


@then("the logs, screenshots, and variant-library panels are present and live")
def live_obs_panels_present(p4ctx):
    html = p4ctx["html"]
    # These panels are wired; assert their section ids and user-facing headings.
    for section in ("logs-section", "screenshots-section", "variants-section"):
        assert f'id="{section}"' in html
    for token in ("Activity log", "Screenshots", "Resume variants"):
        assert token in html


@then("the genuinely dormant surfaces are present but grayed")
def genuinely_dormant_grayed(p4ctx):
    html = p4ctx["html"]
    # Not-yet-available surfaces stay present-but-grayed with the off-badge
    # (resume aggressiveness and the multiple-job-searches switcher).
    assert "applicant-dormant" in html
    assert html.count("admin-badge-off") >= 2
    for token in ("Resume aggressiveness", "Multiple job searches"):
        assert token in html


@given("a campaign with a logged application")
def campaign_with_logged_app(p4ctx):
    from applicant.application.services.admin_query_service import AdminQueryService
    from applicant.observability.logging import configure_logging, get_logger

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    app = Application(
        id=ApplicationId(new_id()),
        campaign_id=cid,
        posting_id=JobPostingId(new_id()),
        status=ApplicationState.PREFILLING,
        role_name="Staff Engineer",
        work_mode="remote",
    )
    storage.applications.add(app)
    storage.commit()
    # Emit a log line into the ring buffer (FR-LOG-3).
    configure_logging(log_format="json", log_level="INFO")
    get_logger("p4test").info("debug_surface_check", application_id=str(app.id))
    # Use a real shim orchestrator (file-backed) for workflow-state introspection.
    from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator

    p4ctx["campaign_id"] = cid
    p4ctx["app"] = app
    p4ctx["admin_query"] = AdminQueryService(storage, CheckpointShimOrchestrator())


@then("the debug history reflects the real application")
def history_reflects_real(p4ctx):
    rows = p4ctx["admin_query"].application_history(p4ctx["campaign_id"])
    assert len(rows) == 1
    assert rows[0]["application_id"] == str(p4ctx["app"].id)
    assert rows[0]["role_name"] == "Staff Engineer"


@then("the logs endpoint returns recent redacted entries")
def logs_returns_entries(p4ctx):
    entries = p4ctx["admin_query"].logs(50)
    assert any(e.get("event") == "debug_surface_check" for e in entries)


@given("the update trigger with no override set")
def update_trigger_default(p4ctx, monkeypatch):
    from applicant.app.routers.update import UpdateTrigger

    monkeypatch.delenv("APPLICANT_UPDATE_ENABLED", raising=False)
    p4ctx["trigger"] = UpdateTrigger()


@when("the update is triggered")
def trigger_update(p4ctx):
    p4ctx["result"] = p4ctx["trigger"].trigger_update()


@then("it does not start a destructive update and explains why")
def update_safe(p4ctx):
    result = p4ctx["result"]
    assert result.started is False
    assert result.message  # non-empty explanation


# === Chatbot (FR-CHAT-1 / FR-FB-3) ========================================
@pytest.fixture
def chat_ctx() -> dict:
    return {}


@given("a chatbot for an empty campaign")
def chatbot_for_campaign(chat_ctx):
    from applicant.application.services.attribute_cloud_service import AttributeCloudService
    from applicant.application.services.chat_service import ChatService
    from applicant.application.services.criteria_service import CriteriaService

    storage = InMemoryStorage()
    chat_ctx["storage"] = storage
    chat_ctx["campaign_id"] = CampaignId(new_id())
    chat_ctx["chat"] = ChatService(
        attribute_service=AttributeCloudService(storage),
        criteria_service=CriteriaService(storage),
        llm=None,
    )


@when('the user sends "hello"')
def user_says_hello(chat_ctx):
    chat_ctx["result"] = chat_ctx["chat"].converse(chat_ctx["campaign_id"], "hello")


@then("the chatbot reports the missing core attributes")
def reports_missing(chat_ctx):
    gaps = chat_ctx["result"].gaps
    assert "first name" in gaps and "email address" in gaps


@when("the user states an integral attribute value")
def states_integral(chat_ctx):
    chat_ctx["result"] = chat_ctx["chat"].converse(
        chat_ctx["campaign_id"], "my first name is Kevin"
    )


@then("the chatbot proposes the change requiring confirmation")
def proposes_gated(chat_ctx):
    proposals = chat_ctx["result"].proposed_changes
    assert proposals and proposals[0].requires_confirmation is True
    assert proposals[0].applied is False


@then("the change is not committed until the user confirms")
def not_committed_until_confirm(chat_ctx):
    cid = chat_ctx["campaign_id"]
    storage = chat_ctx["storage"]
    assert not any(a.name == "first name" for a in storage.attributes.list_for_campaign(cid))
    chat_ctx["chat"].confirm_change(cid, "first name", "Kevin")
    assert any(a.name == "first name" for a in storage.attributes.list_for_campaign(cid))


@when("the user states a non-integral attribute value")
def states_non_integral(chat_ctx):
    chat_ctx["result"] = chat_ctx["chat"].converse(
        chat_ctx["campaign_id"], "my years of experience is 8"
    )


@then("the chatbot applies the change immediately")
def applies_immediately(chat_ctx):
    proposals = chat_ctx["result"].proposed_changes
    assert proposals and proposals[0].applied is True
    assert proposals[0].requires_confirmation is False


# === Update script ordering (FR-INSTALL-2 / FR-OOBE-4) ====================
@pytest.fixture
def update_ctx() -> dict:
    return {}


@given("the update script")
def update_script(update_ctx):
    script = Path(__file__).resolve().parents[3] / "scripts" / "update.sh"
    update_ctx["text"] = script.read_text(encoding="utf-8")


@then("it backs up the database before running migrations")
def backup_before_migrate(update_ctx):
    text = update_ctx["text"]
    backup_idx = text.index("pg_dump")
    migrate_idx = text.index("alembic upgrade head")
    assert backup_idx < migrate_idx  # backup BEFORE migrate (safe order)


@then("a failure leaves the backup intact for rollback")
def failure_leaves_backup(update_ctx):
    # The script documents and supports --rollback restoring the latest backup.
    assert "--rollback" in update_ctx["text"]
    assert "set -euo pipefail" in update_ctx["text"]  # aborts the run on any failure


@then("it restores the most recent backup on rollback")
def restores_latest_backup(update_ctx):
    text = update_ctx["text"]
    assert "ROLLBACK" in text
    assert "ls -1t" in text  # picks the most-recent backup
    assert "psql" in text  # restores it into Postgres
