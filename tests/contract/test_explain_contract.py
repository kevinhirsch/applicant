"""EXPLAIN backend — contract tests.

Two contracts:

* ``GET /api/explain/{posting_id}`` — the engine HTTP shape (LLM gate, 404 on a
  missing posting, the ``to_payload()`` field shape, and the lazy-compute-and-
  cache behavior the router promises).
* the a0 shell's ``a0-applicant/api/explain.py`` proxy ``dispatch`` routing —
  loaded standalone (framework imports stubbed) and exercised the same way
  ``tests/unit/test_az2_digest_proxy.py`` exercises its digest sibling.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.core.entities.job_posting import JobPosting
from applicant.core.ids import CampaignId, JobPostingId, new_id

# ---------------------------------------------------------------------------
# GET /api/explain/{posting_id} — engine HTTP shape
# ---------------------------------------------------------------------------


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def llm_client(app):
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def _seed_posting(client, *, viability_score: float | None = 0.7, **overrides) -> tuple[str, str]:
    cid = client.post("/api/campaigns", json={"name": "Explain contract"}).json()["id"]
    storage = client.app.state.container.storage
    posting_id = new_id()
    defaults = dict(
        id=JobPostingId(posting_id),
        campaign_id=CampaignId(cid),
        title="Scrum Master",
        company="Acme",
        source_url="https://job-boards.greenhouse.io/acme/jobs/123",
        description="Run Agile ceremonies for two teams.",
        viability_score=viability_score,
    )
    defaults.update(overrides)
    storage.postings.add(JobPosting(**defaults))
    storage.commit()
    return cid, posting_id


@pytest.mark.contract
class TestExplainEndpointContract:
    def test_blocked_before_llm_gate(self, app):
        with TestClient(app) as c:
            res = c.get("/api/explain/whatever")
        assert res.status_code == 409

    def test_missing_posting_is_404(self, llm_client):
        res = llm_client.get("/api/explain/does-not-exist")
        assert res.status_code == 404

    def test_payload_shape(self, llm_client):
        _cid, posting_id = _seed_posting(llm_client, viability_score=0.72)

        res = llm_client.get(f"/api/explain/{posting_id}")
        assert res.status_code == 200
        body = res.json()

        assert body["posting_id"] == posting_id
        assert body["score"] == pytest.approx(0.72)
        assert body["score_pct"] == 72
        assert isinstance(body["summary"], str) and body["summary"]
        assert isinstance(body["factors"], list) and body["factors"]
        for factor in body["factors"]:
            assert set(factor) == {
                "label",
                "polarity",
                "weight",
                "contribution",
                "source",
                "detail",
            }
            assert factor["polarity"] in {"green", "red", "neutral"}
            assert factor["source"] in {"deterministic", "llm"}

        total_contribution = sum(f["contribution"] for f in body["factors"])
        assert total_contribution == pytest.approx(72.0, abs=0.1)

    def test_lazily_computes_and_caches_onto_the_posting(self, llm_client):
        _cid, posting_id = _seed_posting(llm_client, viability_score=0.4)
        storage = llm_client.app.state.container.storage

        before = storage.postings.get(JobPostingId(posting_id))
        assert "breakdown" not in (before.rationale or {})

        res = llm_client.get(f"/api/explain/{posting_id}")
        assert res.status_code == 200

        after = storage.postings.get(JobPostingId(posting_id))
        assert "breakdown" in after.rationale
        assert after.rationale["breakdown"]["score"] == pytest.approx(0.4)

    def test_second_read_reuses_the_cached_breakdown(self, llm_client):
        _cid, posting_id = _seed_posting(llm_client, viability_score=0.55)

        first = llm_client.get(f"/api/explain/{posting_id}").json()
        second = llm_client.get(f"/api/explain/{posting_id}").json()
        assert first == second


# ---------------------------------------------------------------------------
# a0-applicant/api/explain.py proxy — dispatch routing
# ---------------------------------------------------------------------------

HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/explain.py"


@pytest.fixture()
def proxy_mod():
    api = types.ModuleType("helpers.api")

    class _AH:
        def __init__(self, *a, **k):
            pass

    api.ApiHandler = _AH
    helpers = sys.modules.setdefault("helpers", types.ModuleType("helpers"))
    helpers.api = api
    sys.modules["helpers.api"] = api
    flask = sys.modules.setdefault("flask", types.ModuleType("flask"))
    flask.Request = object

    spec = importlib.util.spec_from_file_location("_az2_explain", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.contract
class TestExplainProxyContract:
    def test_get_forwards_to_engine(self, proxy_mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path, body=body)
            return {"ok": True, "status": 200, "data": {"posting_id": "p1"}}

        with patch.object(proxy_mod, "_forward", fake):
            result = proxy_mod.dispatch({"action": "get", "posting_id": "p1"})

        assert seen == {"method": "GET", "path": "/api/explain/p1", "body": None}
        assert result == {"ok": True, "status": 200, "data": {"posting_id": "p1"}}

    def test_default_action_is_get(self, proxy_mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": {}}

        with patch.object(proxy_mod, "_forward", fake):
            proxy_mod.dispatch({"posting_id": "p2"})

        assert seen == {"method": "GET", "path": "/api/explain/p2"}

    def test_missing_posting_id_is_rejected(self, proxy_mod):
        result = proxy_mod.dispatch({"action": "get"})
        assert result == {"ok": False, "status": 400, "error": "posting_id required"}

    def test_unknown_action_is_rejected(self, proxy_mod):
        result = proxy_mod.dispatch({"action": "bogus", "posting_id": "p1"})
        assert result["ok"] is False
        assert result["status"] == 400
        assert "unknown explain action" in result["error"]

    def test_handler_class_delegates_to_dispatch(self, proxy_mod):
        assert issubclass(proxy_mod.Explain, proxy_mod.ApiHandler)
