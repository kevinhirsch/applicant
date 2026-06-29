"""Hermetic end-to-end user-journey gate (#364, release-readiness §3.2).

Proves the **assembled product** — not unit-by-unit — drives a seeded campaign all the
way through the autonomous pipeline to the human-in-the-loop stop-boundary:

    discovery -> viability scoring -> daily digest -> approve -> tailor/review-gate
    -> pre-fill -> **STOP-BOUNDARY (AWAITING_FINAL_APPROVAL, no auto-submit)**

and asserts the two safety invariants the master spec demands of a public surface that
auto-acts on the user's behalf:

* **A human-review / pending item is produced** (the user is given the decision), and
* **No auto-submit occurs** — review-before-submit is honored: the pipeline parks at
  ``AWAITING_FINAL_APPROVAL`` and records NO submission/finish outcome. The engine
  cannot self-authorize a final submit (NFR-CAUTION-1 / FR-PREFILL-4 / FR-RESUME-8).

This runs in the DEFAULT hermetic lane (NOT ``@integration``). It drives the REAL
assembled FastAPI app (``create_app()`` over the ``TestClient`` — the same boot the
public front-door proxies into) and the REAL services (``ScoringService(llm=None)`` +
``LocalEmbedding``, ``DigestService``, ``CriteriaService``, ``AgentLoop`` over the
checkpoint-shim orchestrator), against the booted app's OWN in-memory storage.

The pre-fill leg drives a real stealth browser in production — the one piece that cannot
run hermetically — so, per the readiness guidance, that single leg is exercised at its
nearest service seam: a fake ``prefill_service`` that honors the same ``PrefillResult``
state contract the loop persists, landing the application at the final-approval gate
exactly as production does (it NEVER returns a submitted/terminal state). The
review-before-submit gate itself is additionally asserted directly against the core rule
(``ensure_submittable``), so the stop-boundary is proven at both the assembled-pipeline
level and the pure-rule level.

Wiring patterns reused from ``tests/bdd/steps/test_p0_steps.py`` (HTTP gate-open +
campaign/criteria/résumé intake over the UI endpoints) and
``tests/unit/test_loop_end_to_end.py`` (the fake gate pre-fill + real-service loop
assembly).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from applicant.adapters.embedding.local_embedding import LocalEmbedding
from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator
from applicant.app.main import create_app
from applicant.application.services.agent_loop import AgentLoop
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.criteria_service import CriteriaService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.scoring_service import ScoringService
from applicant.core.entities.job_posting import JobPosting
from applicant.core.errors import ReviewRequired
from applicant.core.ids import CampaignId, JobPostingId, new_id
from applicant.core.rules.review_gate import ReviewableMaterial, ensure_submittable
from applicant.core.state_machine import ApplicationState
from tests.conftest import open_automated_work_gate

# Terminal states the pipeline must NOT self-advance into (the stop-boundary).
_SUBMITTED_STATES = {
    ApplicationState.SUBMITTED_BY_USER,
    ApplicationState.FINISHED_BY_ENGINE,
}


# --- the pre-fill seam: a truthful browser that lands at the human gate ------
class _PrefillResult:
    def __init__(self, state: ApplicationState) -> None:
        self.state = state


class _GatePrefill:
    """Models the browser pre-fill at its service seam (the ONE non-hermetic leg).

    The REAL pre-fill drives a stealth browser, so it is faked here. It honors the same
    ``PrefillResult.state`` contract the loop persists, so the assembled pipeline lands
    at ``AWAITING_FINAL_APPROVAL`` exactly as production does — the review/stop-boundary.
    It NEVER returns a submitted/terminal state: the loop must not self-authorize past
    the human-in-the-loop gate.
    """

    def __init__(self) -> None:
        self.calls = 0

    def prefill_application(self, application, url, attributes=None, *, cautious=True):
        self.calls += 1
        return _PrefillResult(ApplicationState.AWAITING_FINAL_APPROVAL)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def _seed_posting(storage, cid: CampaignId, *, title: str, description: str) -> JobPostingId:
    pid = JobPostingId(new_id())
    storage.postings.add(
        JobPosting(
            id=pid,
            campaign_id=cid,
            title=title,
            company="Acme",
            description=description,
            source_url=f"http://jobs/{new_id()}",
        )
    )
    return pid


def _assemble_loop(container, orchestrator) -> tuple[AgentLoop, _GatePrefill]:
    """Wire the AgentLoop over the booted app's OWN storage + real services.

    Only the browser pre-fill is faked (it would launch a real stealth browser); the
    scoring/criteria/digest services are real, driving the app's real in-memory storage.
    """
    storage = container.storage
    embedding = LocalEmbedding()
    scoring = ScoringService(storage, llm=None, embedding=embedding)
    criteria = CriteriaService(storage)
    digest = DigestService(
        storage,
        notification=None,
        scoring=scoring,
        criteria=criteria,
        pending_actions=None,
    )
    prefill = _GatePrefill()
    loop = AgentLoop(
        storage=storage,
        agent_run_service=AgentRunService(storage),
        scoring_service=scoring,
        digest_service=digest,
        criteria_service=criteria,
        prefill_service=prefill,
        orchestrator=orchestrator,
        setup_service=container.setup_service,
    )
    return loop, prefill


def test_seeded_campaign_reaches_stop_boundary_with_human_review_and_no_autosubmit(
    client, tmp_path
):
    """discovery -> score -> digest -> approve -> pre-fill -> STOP-BOUNDARY, over the
    assembled app: a human-review item is produced AND nothing is auto-submitted."""
    # --- OOBE / automated-work gate, opened over the UI endpoints (FR-ONBOARD-2). ---
    open_automated_work_gate(client)
    container = client.app.state.container
    storage = container.storage

    # --- a campaign with real apply-criteria, created over the UI surface. ---
    cid_str = client.post("/api/campaigns", json={"name": "E2E journey"}).json()["id"]
    r = client.put(
        f"/api/criteria/{cid_str}",
        json={
            "titles": ["Python Engineer"],
            "locations": ["Remote"],
            "work_modes": ["remote"],
            "keywords": ["python", "fastapi"],
            "salary_floor": 120000,
            "confirm": True,
        },
    )
    assert r.status_code == 200, r.text
    cid = CampaignId(cid_str)

    # --- DISCOVERY: two postings land for the campaign (an on-criteria role and an
    # off-criteria one, so the real lexical scorer must discriminate). Discovery's
    # network fetch is the non-hermetic part; its OUTPUT (postings in storage) is what
    # the rest of the pipeline consumes, so we seed that output directly. ---
    match_pid = _seed_posting(
        storage, cid, title="Python Engineer", description="Build python fastapi services"
    )
    _seed_posting(storage, cid, title="Warehouse Associate", description="Lift boxes in a depot")
    storage.commit()

    # --- SCORE + DIGEST: delivering the digest over the UI endpoint runs the real
    # scoring + digest build (FR-DIG-1/3/4). The digest is reachable HTTP surface. ---
    deliver = client.post(f"/api/digest/{cid_str}/deliver")
    assert deliver.status_code == 200, deliver.text
    body = deliver.json()
    assert body["empty"] is False
    # Exactly the ONE viable role makes the digest; the off-criteria one is dropped.
    assert body["row_count"] == 1

    scores = {p.title: p.viability_score for p in storage.postings.list_for_campaign(cid)}
    assert all(v is not None for v in scores.values()), "every discovered posting must be scored"
    assert scores["Python Engineer"] > scores["Warehouse Associate"], (
        "the real scorer must rank the on-criteria role above the off-criteria one"
    )

    # The digest payload is readable over HTTP (the in-app updates surface).
    digest_payload = client.get(f"/api/digest/{cid_str}").json()
    assert len(digest_payload["rows"]) == 1

    # --- A HUMAN-REVIEW / pending item is produced: the digest-delivery materializes a
    # digest-approval pending action awaiting the user's decision (FR-UI-3). ---
    pending = storage.pending_actions.list_open(cid)
    assert pending, "digest delivery must produce a human-review pending item"
    assert any(pa.kind == "digest_approval" for pa in pending)

    # --- APPROVE: the user approves the viable role over the UI endpoint, which
    # promotes the posting to an APPROVED application (FR-DIG-3). ---
    approve = client.post(f"/api/digest/applications/{match_pid}/approve")
    assert approve.status_code == 201, approve.text
    assert approve.json()["type"] == "approve"
    app_before = storage.applications.list_for_campaign(cid)
    assert len(app_before) == 1
    assert app_before[0].status is ApplicationState.APPROVED

    # --- TAILOR / REVIEW-GATE (pure-rule seam): generated material cannot be submitted
    # until the user approves it; an approved bundle can (FR-RESUME-8 / FR-ANSWER-1). ---
    with pytest.raises(ReviewRequired):
        ensure_submittable([ReviewableMaterial("cover-letter", is_generated=True, approved=False)])
    ensure_submittable([ReviewableMaterial("cover-letter", is_generated=True, approved=True)])

    # --- PRE-FILL -> STOP-BOUNDARY: one loop tick over the assembled pipeline (real
    # services + the booted app's storage; only the browser faked) advances the approved
    # application to the human-in-the-loop gate. ---
    orchestrator = CheckpointShimOrchestrator(str(tmp_path / "checkpoints"))
    loop, prefill = _assemble_loop(container, orchestrator)
    loop.tick(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    apps = storage.applications.list_for_campaign(cid)
    assert len(apps) == 1, "exactly the one approved posting became an application"
    app = apps[0]
    assert str(app.posting_id) == str(match_pid)
    assert prefill.calls == 1, "the pipeline ran the pre-fill leg exactly once"

    # The pipeline handed off AT the human gate.
    assert app.status is ApplicationState.AWAITING_FINAL_APPROVAL

    # --- THE STOP-BOUNDARY HOLDS: no auto-submit. The engine recorded NO
    # submission/finish outcome and did NOT walk into a terminal submitted state. ---
    assert storage.outcomes.list_for_application(app.id) == [], (
        "review-before-submit violated: the engine self-authorized an outcome"
    )
    assert app.status not in _SUBMITTED_STATES, (
        "review-before-submit violated: the engine advanced past the human gate"
    )


def test_off_criteria_only_campaign_produces_no_application_and_no_submit(client, tmp_path):
    """A campaign whose only discovered role is below the viability bar starts no
    application and (trivially) never submits — the loop never fabricates work."""
    open_automated_work_gate(client)
    container = client.app.state.container
    storage = container.storage

    cid_str = client.post("/api/campaigns", json={"name": "Off-criteria only"}).json()["id"]
    client.put(
        f"/api/criteria/{cid_str}",
        json={
            "titles": ["Python Engineer"],
            "locations": ["Remote"],
            "work_modes": ["remote"],
            "keywords": ["python", "fastapi", "kubernetes"],
            "salary_floor": 120000,
            "confirm": True,
        },
    )
    cid = CampaignId(cid_str)
    _seed_posting(storage, cid, title="Warehouse Associate", description="Lift boxes in a depot")
    storage.commit()

    # Deliver the digest, then run a tick with NO approval recorded.
    client.post(f"/api/digest/{cid_str}/deliver")
    orchestrator = CheckpointShimOrchestrator(str(tmp_path / "checkpoints"))
    loop, prefill = _assemble_loop(container, orchestrator)
    loop.tick(cid, datetime(2026, 6, 16, 9, 0, tzinfo=UTC))

    # Nothing was approved, so no application was started and no pre-fill ran.
    assert storage.applications.list_for_campaign(cid) == []
    assert prefill.calls == 0
    # And, trivially, nothing was submitted anywhere in the campaign.
    for posting in storage.postings.list_for_campaign(cid):
        # postings have no outcomes; assert the campaign produced zero applications above.
        assert posting.viability_score is not None  # it WAS scored (discovery->score ran)
