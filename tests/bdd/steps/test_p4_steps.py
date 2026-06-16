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

from applicant.adapters.tools.tool_registry import ToolDisabledError, ToolRegistry
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
    "../features/p4_tool_toggles.feature",
    "../features/p4_dormant_surfaces.feature",
)

_FRONTEND = Path(__file__).resolve().parents[3] / "frontend" / "static" / "applicant"


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


@then("the logs, screenshots, and variant-library panels are present but dormant")
def dormant_panels_grayed(p4ctx):
    html = p4ctx["html"]
    # The grayed class is present and applied to dormant panels (FR-UI-2).
    assert "applicant-dormant" in html
    assert html.count("admin-badge-off") >= 3  # logs + screenshots + variant library
    for token in ("Logs", "Screenshots", "Variant library"):
        assert token in html


@given("a not-yet-wired observability endpoint")
def pending_endpoint(p4ctx):
    from applicant.app.routers.admin import application_screenshots, logs

    p4ctx["screenshots"] = application_screenshots("app-123")
    p4ctx["logs"] = logs()


@then("it reports a pending status with no fabricated rows")
def reports_pending(p4ctx):
    assert p4ctx["screenshots"]["status"] == "pending"
    assert p4ctx["screenshots"]["screenshots"] == []
    assert p4ctx["logs"]["status"] == "pending"
    assert p4ctx["logs"]["entries"] == []


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
