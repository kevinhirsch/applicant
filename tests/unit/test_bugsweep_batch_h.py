"""Bugsweep batch H — error-handling / robustness fixes.

Each test fails BEFORE its corresponding fix and passes after:

1. Global DomainError -> 4xx exception handler + ``NotFound`` type.
2. MaterialService not-found raises map to 404; bad-kind to 422.
3. AgentRunService configure/start raise NotFound (404) + invalid run_mode 422.
4. OpenAI-compatible LLM: non-JSON 200 climbs the ladder / exhausts; malformed
   ``choices`` shape doesn't crash; garbage ``/models`` returns [].
5. Digest side-effect guarding (no 500 after the Decision commit) + scoring
   alignment guarded so a flaky embedding can't 500 the digest.
6. Upload / embedding / payload hardening.
"""

from __future__ import annotations

import io

import httpx
import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from applicant.adapters.llm.openai_compatible import OpenAICompatibleLLM
from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.app.main import create_app
from applicant.application.services.agent_run_service import AgentRunService
from applicant.application.services.digest_service import DigestService
from applicant.application.services.material_service import MaterialService
from applicant.core.entities.campaign import Campaign
from applicant.core.errors import (
    DomainError,
    IllegalStateTransition,
    InvalidInput,
    NotFound,
    OnboardingIncomplete,
    ReviewRequired,
    SensitiveFieldViolation,
    TruthfulnessViolation,
)
from applicant.core.ids import (
    CampaignId,
    GeneratedDocumentId,
    new_id,
)
from applicant.ports.driven.llm import ChatMessage, LLMLadderExhausted, TierConfig, TierLadder
from tests.conftest import open_automated_work_gate


# ===========================================================================
# Fix 1 — global DomainError -> 4xx exception handler
# ===========================================================================
@pytest.mark.unit
def test_global_handler_maps_each_domain_error_to_canonical_4xx():
    """A route raising each mapped DomainError returns the right status, not 500."""
    app = create_app()
    probe = APIRouter(prefix="/api/_probe")

    @probe.get("/{which}")
    def _raise(which: str):
        mapping = {
            "review": ReviewRequired("x"),
            "illegal": IllegalStateTransition("a", "b"),
            "sensitive": SensitiveFieldViolation("x"),
            "truth": TruthfulnessViolation("x"),
            "onboarding": OnboardingIncomplete("x"),
            "invalid": InvalidInput("x"),
            "notfound": NotFound("x"),
            "base": DomainError("x"),
        }
        raise mapping[which]

    app.include_router(probe)
    client = TestClient(app)

    expected = {
        "review": 409,
        "illegal": 409,
        "sensitive": 422,
        "truth": 422,
        "onboarding": 409,
        "invalid": 422,
        "notfound": 404,
        "base": 400,  # catch-all
    }
    for which, code in expected.items():
        r = client.get(f"/api/_probe/{which}")
        assert r.status_code == code, (which, r.status_code)
        # Clean JSON body, no traceback leak.
        assert "detail" in r.json()
        assert "Traceback" not in r.text


# ===========================================================================
# Fix 2 — MaterialService not-found -> 404, bad-kind -> 422
# ===========================================================================
def _material(storage) -> MaterialService:
    return MaterialService(storage)


@pytest.mark.unit
def test_material_approve_missing_document_raises_notfound():
    svc = _material(InMemoryStorage())
    with pytest.raises(NotFound):
        svc.approve(GeneratedDocumentId(new_id()))


@pytest.mark.unit
def test_material_decline_missing_document_raises_notfound():
    svc = _material(InMemoryStorage())
    with pytest.raises(NotFound):
        svc.decline(GeneratedDocumentId(new_id()))


@pytest.mark.unit
def test_material_bad_revision_kind_raises_invalid_input():
    svc = _material(InMemoryStorage())
    with pytest.raises(InvalidInput):
        svc.apply_turn(GeneratedDocumentId(new_id()), "bogus", "x")


@pytest.mark.integration
def test_documents_approve_bad_id_returns_404():
    app = create_app()
    with TestClient(app) as c:
        c.post(
            "/api/setup/llm",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.1",
            },
        )
        r = c.post(f"/api/documents/{new_id()}/approve")
        assert r.status_code == 404


# ===========================================================================
# Fix 3 — AgentRunService config/start NotFound + invalid run_mode
# ===========================================================================
@pytest.mark.unit
def test_configure_run_missing_campaign_raises_notfound():
    svc = AgentRunService(InMemoryStorage())
    with pytest.raises(NotFound):
        svc.configure_run(CampaignId(new_id()), throughput_target=5)


@pytest.mark.unit
def test_configure_run_invalid_run_mode_raises_invalid_input():
    storage = InMemoryStorage()
    c = Campaign(id=CampaignId(new_id()), name="c")
    storage.campaigns.add(c)
    storage.commit()
    svc = AgentRunService(storage)
    with pytest.raises(InvalidInput):
        svc.configure_run(c.id, run_mode="bogus")


@pytest.mark.unit
def test_start_run_missing_campaign_raises_not_silent():
    svc = AgentRunService(InMemoryStorage())
    with pytest.raises(NotFound):
        svc.start_run(CampaignId(new_id()), "do a thing next")


@pytest.mark.integration
def test_agent_runs_router_bad_campaign_404_and_bad_mode_422():
    app = create_app()
    with TestClient(app) as c:
        open_automated_work_gate(c)
        # Bad campaign -> 404 (was a KeyError -> 500).
        r = c.put(f"/api/agent-runs/{new_id()}/config", json={"throughput_target": 5})
        assert r.status_code == 404
        # Real campaign + bogus run_mode -> 422 (was a ValueError -> 500).
        cid = c.post("/api/campaigns", json={"name": "j"}).json()["id"]
        r = c.put(f"/api/agent-runs/{cid}/config", json={"run_mode": "bogus"})
        assert r.status_code == 422


# ===========================================================================
# Fix 4 — LLM adapter robustness
# ===========================================================================
def _two_tier(transport) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        ladder=TierLadder(
            tiers=[
                TierConfig(provider="openai", base_url="https://a/v1", model="m1", context_window=8192),
                TierConfig(provider="openai", base_url="https://b/v1", model="m2", context_window=8192),
            ]
        ),
        transport=transport,
    )


@pytest.mark.unit
def test_non_json_200_climbs_ladder_to_next_tier():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "a":
            # A proxy/CDN returns an HTML 200 (not JSON).
            return httpx.Response(200, text="<html>nope</html>")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "from tier 2"}}]}
        )

    llm = _two_tier(httpx.MockTransport(handler))
    result = llm.complete([ChatMessage(role="user", content="hi")])
    assert result.text == "from tier 2"
    assert calls == ["a", "b"]


@pytest.mark.unit
def test_non_json_200_all_tiers_raises_ladder_exhausted_not_jsondecode():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>nope</html>")

    llm = _two_tier(httpx.MockTransport(handler))
    with pytest.raises(LLMLadderExhausted):
        llm.complete([ChatMessage(role="user", content="hi")])


@pytest.mark.unit
def test_malformed_choices_shape_does_not_crash():
    def handler(request: httpx.Request) -> httpx.Response:
        # choices[0] is a string, not a dict.
        return httpx.Response(200, json={"choices": ["oops"]})

    llm = _two_tier(httpx.MockTransport(handler))
    result = llm.complete([ChatMessage(role="user", content="hi")])
    assert result.text == ""


@pytest.mark.unit
def test_garbage_models_response_returns_empty_list():
    def handler(request: httpx.Request) -> httpx.Response:
        # A list of non-dict junk under "data".
        return httpx.Response(200, json={"data": ["x", 1, None]})

    llm = OpenAICompatibleLLM(
        provider="openai",
        base_url="https://a/v1",
        model="m",
        transport=httpx.MockTransport(handler),
    )
    assert llm.list_models() == []


# ===========================================================================
# Fix 5 — digest side-effect guarding + scoring alignment guard
# ===========================================================================
class _BoomNotifier:
    def acted(self, *_a, **_k):
        raise RuntimeError("notifier down")

    def acted_digest(self, *_a, **_k):
        raise RuntimeError("notifier down")


class _BoomLearning:
    def ingest_decline_atomic(self, *_a, **_k):
        raise RuntimeError("learning store down")

    def load_model(self, *_a, **_k):
        raise RuntimeError("learning store down")


@pytest.mark.unit
def test_decline_persists_decision_even_if_notifier_and_learning_fail():
    storage = InMemoryStorage()
    svc = DigestService(
        storage,
        notification=object(),
        notification_service=_BoomNotifier(),
        learning=_BoomLearning(),
    )
    # Must not raise even though notifier + learning blow up post-commit.
    decision = svc.decline(CampaignId(new_id()), feedback_text="not remote")
    # The Decision is still persisted.
    persisted = storage.decisions.list_for_application(decision.application_id)
    assert any(d.id == decision.id for d in persisted)


class _BoomEmbeddingLearning:
    """A LearningService double whose alignment call raises (flaky embedding)."""

    def load_model(self, campaign_id):
        return object()

    def converting_alignment(self, _model, _text):
        raise RuntimeError("embedding flaked")


@pytest.mark.unit
def test_scoring_signature_alignment_guarded_against_flaky_embedding():
    from applicant.application.services.scoring_service import ScoringService
    from applicant.core.entities.job_posting import JobPosting
    from applicant.core.ids import JobPostingId

    class _Embed:
        def similarity(self, _a, _b):
            return 0.9

    svc = ScoringService(
        InMemoryStorage(), llm=None, embedding=_Embed(), learning=_BoomEmbeddingLearning()
    )
    posting = JobPosting(
        id=JobPostingId(new_id()),
        campaign_id=CampaignId(new_id()),
        title="Backend Engineer",
        company="ACME",
        source_url="https://jobs.test/1",
        description="python",
    )
    # Must not raise; alignment falls back to 0.0 so scoring still returns.
    scoring = svc.score_posting(posting)
    assert scoring.score >= 0.0


# ===========================================================================
# Fix 6 — upload / embedding / payload hardening
# ===========================================================================
@pytest.mark.integration
def test_empty_base_resume_upload_returns_4xx_not_500():
    app = create_app()
    with TestClient(app) as c:
        c.post(
            "/api/setup/llm",
            json={
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "model": "llama3.1",
            },
        )
        cid = c.post("/api/campaigns", json={"name": "j"}).json()["id"]
        r = c.post(
            f"/api/onboarding/{cid}/base-resume",
            files={"file": ("resume.txt", io.BytesIO(b"   "), "text/plain")},
        )
        assert 400 <= r.status_code < 500


class _EmptyEmbedding:
    """Embedding that returns an empty result for embed()."""

    def embed(self, _texts):
        return [[]]


@pytest.mark.unit
def test_converting_alignment_with_empty_embedding_does_not_crash():
    from applicant.application.services.learning_service import LearningService
    from applicant.core.entities.learning_model import LearningModel

    svc = LearningService(InMemoryStorage(), _EmptyEmbedding())
    model = LearningModel(
        campaign_id=CampaignId(new_id()),
        converting_role_signature={"vector": [0.1, 0.2, 0.3]},
    )
    # An empty embedding result must not crash conversion learning.
    assert svc.converting_alignment(model, "some jd text") == 0.0


@pytest.mark.unit
def test_record_converting_role_with_empty_embedding_returns_model_unchanged():
    from applicant.application.services.learning_service import LearningService
    from applicant.core.entities.learning_model import LearningModel

    svc = LearningService(InMemoryStorage(), _EmptyEmbedding())
    model = LearningModel(campaign_id=CampaignId(new_id()))
    out = svc.record_converting_role(model, "jd text")
    assert out.converting_samples == 0


@pytest.mark.unit
def test_pending_action_with_none_payload_does_not_attribute_error():
    from applicant.application.services.pending_actions_service import PendingActionsService
    from applicant.core.entities.pending_action import PendingAction
    from applicant.core.ids import PendingActionId

    storage = InMemoryStorage()
    cid = CampaignId(new_id())
    # A pending action with a None payload (legacy/degenerate row).
    action = PendingAction(
        id=PendingActionId(new_id()),
        campaign_id=cid,
        kind="x",
        title="t",
        payload=None,
    )
    storage.pending_actions.add(action)
    storage.commit()
    svc = PendingActionsService(storage)
    # resolve_by_dedup walks payloads; a None payload must not AttributeError.
    svc.resolve_by_dedup(cid, "nope")
