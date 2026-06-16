"""Step bindings for the Phase 1 acceptance scenarios (master spec §10).

Maps the §10 anchors — Master aggregator (wave one), Source-yield learning with
exploration, Pending-actions portal — to real services + adapters + core rules so the
scenarios genuinely pass. HTTP scenarios open the LLM gate via the setup endpoint
(zero-CLI) exactly as the app would. Phase-local fixtures live here, not in the shared
conftest.
"""

from __future__ import annotations

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.adapters.discovery.jobspy_searxng import JobSpySearxngDiscovery
from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.notification.apprise_notifier import AppriseNotifier
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.digest_service import DigestService
from applicant.application.services.discovery_service import DiscoveryService
from applicant.application.services.learning_service import LearningService
from applicant.application.services.scoring_service import (
    DEFAULT_VIABILITY_THRESHOLD,
    ScoringService,
)
from applicant.core.entities.pending_action import PendingAction
from applicant.core.entities.search_criteria import SearchCriteria
from applicant.core.ids import ApplicationId, CampaignId, PendingActionId, new_id

scenarios(
    "../features/p1_discovery_digest.feature",
    "../features/p1_scoring_feedback.feature",
    "../features/p1_pending_actions.feature",
    "../features/p1_source_yield_learning.feature",
    "../features/p1_criteria_runmodes.feature",
)


# --- phase-local fixtures --------------------------------------------------
@pytest.fixture
def p1ctx() -> dict:
    return {}


@pytest.fixture
def storage() -> InMemoryStorage:
    return InMemoryStorage()


@pytest.fixture
def embedding() -> LocalEmbedding:
    return LocalEmbedding()


@pytest.fixture
def discovery() -> JobSpySearxngDiscovery:
    return JobSpySearxngDiscovery()


def _open_gate(client) -> None:
    r = client.post(
        "/api/setup/llm",
        json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
    )
    assert r.status_code == 204


# --- discovery + digest ----------------------------------------------------
@given("a campaign with engineering search criteria")
def campaign_with_criteria(p1ctx):
    cid = CampaignId(new_id())
    p1ctx["campaign_id"] = cid
    p1ctx["criteria"] = SearchCriteria(campaign_id=cid, titles=("engineer",))


@when("discovery runs over the enabled offline sources")
def run_discovery(p1ctx, storage, discovery, embedding):
    svc = DiscoveryService(storage, discovery, embedding)
    p1ctx["storage"] = storage
    p1ctx["postings"] = svc.run_discovery(p1ctx["campaign_id"], p1ctx["criteria"])


@then("normalized job postings are persisted for the campaign")
def postings_persisted(p1ctx):
    persisted = p1ctx["storage"].postings.list_for_campaign(p1ctx["campaign_id"])
    assert persisted and len(persisted) == len(p1ctx["postings"])


@then("every posting records which source yielded it")
def postings_have_source(p1ctx):
    assert all(p.source_key for p in p1ctx["postings"])


@given("discovered postings have been scored for viability")
def scored_postings(p1ctx, storage, discovery, embedding):
    cid = CampaignId(new_id())
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    DiscoveryService(storage, discovery, embedding).run_discovery(cid, crit)
    p1ctx["campaign_id"] = cid
    p1ctx["criteria"] = crit
    p1ctx["storage"] = storage
    p1ctx["scoring"] = ScoringService(storage, llm=None, embedding=embedding, threshold=0)


@when("the daily digest is built")
def build_digest(p1ctx):
    svc = DigestService(
        p1ctx["storage"], AppriseNotifier(), p1ctx.get("scoring")
    )
    p1ctx["digest"] = svc.build_digest_payload(p1ctx["campaign_id"], p1ctx.get("criteria"))


@then("each digest row carries a score and a why-suggested rationale")
def rows_have_rationale(p1ctx):
    rows = p1ctx["digest"]["rows"]
    assert rows
    assert all(r["viability_score"] is not None and r["why_suggested"] for r in rows)


@given("a campaign with no discovered postings")
def empty_campaign(p1ctx, storage):
    p1ctx["campaign_id"] = CampaignId(new_id())
    p1ctx["storage"] = storage
    p1ctx["scoring"] = None
    p1ctx["criteria"] = None


@then("the digest is flagged empty with an empty-day note")
def digest_empty(p1ctx):
    assert p1ctx["digest"]["empty"] is True
    assert p1ctx["digest"]["note"]


# --- scoring + feedback ----------------------------------------------------
@given("the viability threshold defaults to seventy")
def threshold_default(p1ctx, storage, embedding):
    p1ctx["scoring"] = ScoringService(storage, llm=None, embedding=embedding)
    assert p1ctx["scoring"].threshold == DEFAULT_VIABILITY_THRESHOLD == 70


@when("a posting is scored against matching criteria")
def score_posting(p1ctx, storage, discovery, embedding):
    cid = CampaignId(new_id())
    crit = SearchCriteria(campaign_id=cid, titles=("engineer",), keywords=("python",))
    postings = DiscoveryService(storage, discovery, embedding).run_discovery(cid, crit)
    p1ctx["scoring_result"] = p1ctx["scoring"].score_posting(postings[0], crit)


@then("the score is reported on a zero-to-one scale with a rationale")
def score_reported(p1ctx):
    s = p1ctx["scoring_result"]
    assert 0.0 <= s.score <= 1.0
    assert s.rationale


@given("an application surfaced in the digest")
def app_in_digest(p1ctx, storage):
    p1ctx["storage"] = storage
    p1ctx["application_id"] = ApplicationId(new_id())


@when("the user declines it with feedback")
def decline_with_feedback(p1ctx):
    svc = DigestService(p1ctx["storage"], AppriseNotifier())
    p1ctx["decision"] = svc.decline(
        p1ctx["application_id"], feedback_text="too junior", criteria_delta={"seniority": "senior"}
    )


@then("a decline decision is recorded carrying the feedback text")
def decline_recorded(p1ctx):
    decisions = p1ctx["storage"].decisions.list_for_application(p1ctx["application_id"])
    assert len(decisions) == 1
    assert decisions[0].feedback_text == "too junior"
    assert decisions[0].type.value == "decline"


@given("an integral attribute already exists")
def integral_attribute(p1ctx, app_client):
    _open_gate(app_client)
    p1ctx["client"] = app_client
    p1ctx["campaign_id"] = new_id()
    r = app_client.post(
        "/api/attributes",
        json={
            "campaign_id": p1ctx["campaign_id"],
            "name": "Full legal name",
            "value": "Kevin Hirsch",
            "is_integral": True,
            "confirm": True,
        },
    )
    assert r.status_code == 201


@when("the value is changed without confirmation through the API")
def change_without_confirmation(p1ctx):
    p1ctx["resp"] = p1ctx["client"].post(
        "/api/attributes",
        json={
            "campaign_id": p1ctx["campaign_id"],
            "name": "Full legal name",
            "value": "Someone Else",
            "is_integral": True,
            "confirm": False,
        },
    )


@then("the change is rejected with a confirmation-required response")
def change_rejected(p1ctx):
    assert p1ctx["resp"].status_code == 409


@given("the LLM gate is open")
def gate_open_only(p1ctx, app_client):
    _open_gate(app_client)
    p1ctx["client"] = app_client
    p1ctx["campaign_id"] = new_id()


@when("an AI-guessed value is submitted for a sensitive attribute")
def submit_ai_sensitive(p1ctx):
    p1ctx["resp"] = p1ctx["client"].post(
        "/api/attributes",
        json={
            "campaign_id": p1ctx["campaign_id"],
            "name": "Gender",
            "value": "",
            "is_sensitive": True,
            "ai_suggested": "male",
            "confirm": True,
        },
    )


@then("the sensitive-field policy rejects the guess")
def sensitive_rejected(p1ctx):
    assert p1ctx["resp"].status_code == 422


# --- pending actions -------------------------------------------------------
@given("a campaign with an open pending action")
def campaign_with_pending(p1ctx, app_client):
    _open_gate(app_client)
    p1ctx["client"] = app_client
    container = app_client.app.state.container
    cid = CampaignId(new_id())
    pid = PendingActionId(new_id())
    container.storage.pending_actions.add(
        PendingAction(id=pid, campaign_id=cid, kind="digest_approval", title="Review Acme role")
    )
    container.storage.commit()
    p1ctx["campaign_id"] = cid
    p1ctx["action_id"] = pid


@when("the pending-actions portal is queried")
def query_portal(p1ctx):
    p1ctx["resp"] = p1ctx["client"].get(f"/api/pending-actions/{p1ctx['campaign_id']}")


@then("the open action is listed")
def action_listed(p1ctx):
    assert p1ctx["resp"].status_code == 200
    body = p1ctx["resp"].json()
    assert body["count"] == 1
    assert body["items"][0]["title"] == "Review Acme role"


@when("the action is resolved through the API")
def resolve_action(p1ctx):
    r = p1ctx["client"].post(f"/api/pending-actions/{p1ctx['action_id']}/resolve")
    assert r.status_code == 204


@then("the pending-actions portal lists no open items")
def no_open_items(p1ctx):
    body = p1ctx["client"].get(f"/api/pending-actions/{p1ctx['campaign_id']}").json()
    assert body["count"] == 0


@given("the LLM gate is open for outcomes")
def gate_open_outcomes(p1ctx, app_client):
    _open_gate(app_client)
    p1ctx["client"] = app_client
    p1ctx["application_id"] = new_id()


@when("an application is marked submitted through the API")
def mark_submitted_api(p1ctx):
    p1ctx["resp"] = p1ctx["client"].post(
        f"/api/outcomes/applications/{p1ctx['application_id']}/mark-submitted"
    )


@then("a manual submitted outcome is recorded")
def manual_outcome_recorded(p1ctx):
    assert p1ctx["resp"].status_code == 201
    body = p1ctx["resp"].json()
    assert body["type"] == "submitted" and body["source"] == "manual"


# --- source-yield learning -------------------------------------------------
@given("a fresh learning model for a campaign")
def fresh_model(p1ctx, storage, embedding):
    p1ctx["learning"] = LearningService(storage, embedding)
    p1ctx["model"] = p1ctx["learning"].model_for(CampaignId(new_id()))


@when("source yields from a run are recorded")
def record_yields(p1ctx):
    p1ctx["model"] = p1ctx["learning"].record_source_yield(
        p1ctx["model"], {"jobspy": 9, "searxng": 2}
    )


@then("the higher-yielding source ranks above the lower-yielding one")
def ranking_ordered(p1ctx):
    ranking = p1ctx["learning"].source_ranking(p1ctx["model"])
    assert ranking.index("jobspy") < ranking.index("searxng")


@given("a learning model that has only ever seen one source")
def one_seen_source(p1ctx, storage, embedding):
    p1ctx["learning"] = LearningService(storage, embedding)
    model = p1ctx["learning"].model_for(CampaignId(new_id()))
    p1ctx["model"] = p1ctx["learning"].record_source_yield(model, {"jobspy": 5})


@when("the exploit and explore sets are computed over several sources")
def compute_split(p1ctx):
    all_sources = ["jobspy", "searxng", "remotive", "weworkremotely"]
    p1ctx["exploit"], p1ctx["explore"] = p1ctx["learning"].exploration_split(
        p1ctx["model"], all_sources
    )


@then("at least one unseen source is reserved for exploration")
def explore_reserved(p1ctx):
    assert p1ctx["explore"], "exploration budget must reserve at least one source"
    assert any(s not in ("jobspy",) for s in p1ctx["explore"])


# --- criteria + run controls (FR-CRIT-2/3, FR-AGENT-1/2/7, FR-LEARN-5) -----
@given("a campaign exists")
def a_campaign_exists(p1ctx, app_client):
    from tests.conftest import open_automated_work_gate

    # agent-run controls are automated work (FR-AGENT) and so sit behind the
    # automated-work gate (FR-ONBOARD-2/FR-OOBE-3); open it fully.
    open_automated_work_gate(app_client)
    p1ctx["client"] = app_client
    r = app_client.post("/api/campaigns", json={"name": "BDD campaign"})
    assert r.status_code == 201
    p1ctx["campaign_id"] = r.json()["id"]


@when("the user edits the campaign keywords through the API")
def edit_keywords(p1ctx):
    p1ctx["resp"] = p1ctx["client"].put(
        f"/api/criteria/{p1ctx['campaign_id']}", json={"keywords": ["python", "fastapi"]}
    )
    assert p1ctx["resp"].status_code == 200


@then("the criteria reflect the user's edit")
def criteria_reflect_edit(p1ctx):
    body = p1ctx["client"].get(f"/api/criteria/{p1ctx['campaign_id']}").json()
    assert body["keywords"] == ["python", "fastapi"]


@when("the user changes an integral criterion without confirmation")
def change_integral_criterion(p1ctx):
    p1ctx["resp"] = p1ctx["client"].put(
        f"/api/criteria/{p1ctx['campaign_id']}", json={"titles": ["staff engineer"]}
    )


@then("the criteria change is rejected with a confirmation-required response")
def criteria_change_rejected(p1ctx):
    assert p1ctx["resp"].status_code == 409


@when("learning proposes a non-integral criteria adjustment")
def learning_proposes_adjustment(p1ctx):
    p1ctx["resp"] = p1ctx["client"].post(
        f"/api/criteria/{p1ctx['campaign_id']}/learned",
        json={"adjustment": {"keywords": ["django"]}, "rationale": "approved roles use django"},
    )
    assert p1ctx["resp"].status_code == 200


@then("the adjustment is applied and surfaced with a human-readable summary")
def adjustment_surfaced(p1ctx):
    body = p1ctx["resp"].json()
    assert body["keywords"] == ["django"]
    assert body["learned_adjustments"]["summary"]


@when("the user sets the throughput target above the hard cap")
def set_throughput_over_cap(p1ctx):
    p1ctx["resp"] = p1ctx["client"].put(
        f"/api/agent-runs/{p1ctx['campaign_id']}/config", json={"throughput_target": 100}
    )
    assert p1ctx["resp"].status_code == 200


@then("the persisted throughput target is clamped to thirty")
def throughput_clamped(p1ctx):
    assert p1ctx["resp"].json()["throughput_target"] == 30


@when("an agent run is started with an intent sentence")
def start_run_with_intent(p1ctx):
    container = p1ctx["client"].app.state.container
    container.agent_run_service.start_run(
        p1ctx["campaign_id"], "Scan remote boards for backend roles next."
    )


@then("the latest intent for the campaign is that sentence")
def latest_intent_matches(p1ctx):
    body = p1ctx["client"].get(f"/api/agent-runs/{p1ctx['campaign_id']}/intent").json()
    assert body["intent"] == "Scan remote boards for backend roles next."
