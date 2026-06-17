"""Hermetic tests for Lane C — Cookbook-served local models internal endpoint
(routes/applicant_internal_routes.py::local_models + helpers).

No network, no real Cookbook: the Cookbook serving state is faked by pointing
``DATA_DIR`` at a tmp dir and writing a ``cookbook_state.json``. Covers:

- token gate (channel disabled / wrong token -> 403)
- owner scoping (X-Applicant-Owner echoed back)
- live serve tasks -> clean endpoint list (port parsed, host derived)
- empty case (no state file / nothing served)
- non-live / image / malformed tasks are filtered out
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.applicant_internal_routes import (
    INTERNAL_OWNER_HEADER,
    INTERNAL_TOKEN_HEADER,
    _cookbook_served_models,
    _serve_base_url,
    setup_applicant_internal_routes,
)

TOKEN = "s" * 64


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APPLICANT_INTERNAL_TOKEN", TOKEN)
    return tmp_path


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(setup_applicant_internal_routes())
    return TestClient(app)


def _write_state(state_dir, state):
    (state_dir / "cookbook_state.json").write_text(json.dumps(state), encoding="utf-8")


# === route: auth gate =======================================================
def test_local_models_token_gated(client, state_dir):
    assert client.get("/api/applicant/internal/local-models").status_code == 403
    bad = client.get(
        "/api/applicant/internal/local-models", headers={INTERNAL_TOKEN_HEADER: "nope"}
    )
    assert bad.status_code == 403


def test_local_models_disabled_without_secret(client, tmp_path, monkeypatch):
    monkeypatch.delenv("APPLICANT_INTERNAL_TOKEN", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    resp = client.get(
        "/api/applicant/internal/local-models", headers={INTERNAL_TOKEN_HEADER: TOKEN}
    )
    assert resp.status_code == 403


# === route: empty case ======================================================
def test_local_models_empty_when_no_state(client, state_dir):
    resp = client.get(
        "/api/applicant/internal/local-models", headers={INTERNAL_TOKEN_HEADER: TOKEN}
    )
    assert resp.status_code == 200
    assert resp.json() == {"owner": None, "models": []}


def test_local_models_empty_when_nothing_served(client, state_dir):
    _write_state(state_dir, {"tasks": [{"type": "download", "status": "running"}]})
    resp = client.get(
        "/api/applicant/internal/local-models", headers={INTERNAL_TOKEN_HEADER: TOKEN}
    )
    assert resp.json() == {"owner": None, "models": []}


# === route: live serve + owner scoping ======================================
def test_local_models_lists_live_serve_and_scopes_owner(client, state_dir):
    _write_state(
        state_dir,
        {
            "tasks": [
                {
                    "sessionId": "serve-abc",
                    "type": "serve",
                    "status": "ready",
                    "repoId": "Qwen/Qwen2.5-7B-Instruct",
                    "payload": {"_cmd": "vllm serve Qwen/Qwen2.5-7B-Instruct --port 8001"},
                }
            ]
        },
    )
    resp = client.get(
        "/api/applicant/internal/local-models",
        headers={INTERNAL_TOKEN_HEADER: TOKEN, INTERNAL_OWNER_HEADER: "kevin"},
    )
    body = resp.json()
    assert body["owner"] == "kevin"
    assert body["models"] == [
        {
            "model_id": "Qwen/Qwen2.5-7B-Instruct",
            "name": "Qwen2.5-7B-Instruct",
            "base_url": "http://localhost:8001/v1",
            "status": "ready",
            "remote": "local",
            "served_by": "cookbook",
        }
    ]


# === pure helper: served-model extraction ===================================
def test_served_models_default_port_and_remote_host():
    state = {
        "tasks": [
            {"type": "serve", "status": "running", "modelId": "m1", "payload": {"_cmd": "vllm serve m1"}},
            {
                "type": "serve",
                "status": "ready",
                "modelId": "org/m2",
                "remoteHost": "user@gpu-box",
                "payload": {"_cmd": "vllm serve org/m2 --port 9000"},
            },
        ]
    }
    out = _cookbook_served_models(state)
    assert out[0]["base_url"] == "http://localhost:8000/v1"  # default port
    assert out[1]["base_url"] == "http://gpu-box:9000/v1"  # ssh alias -> bare host
    assert out[1]["remote"] == "user@gpu-box"


def test_served_models_filters_non_live_and_image_and_malformed():
    state = {
        "tasks": [
            {"type": "serve", "status": "queued", "modelId": "queued", "payload": {"_cmd": "vllm serve queued --port 8002"}},
            {"type": "serve", "status": "stopped", "modelId": "dead", "payload": {"_cmd": "vllm serve dead --port 8003"}},
            {"type": "serve", "status": "ready", "modelId": "img", "payload": {"_cmd": "python scripts/diffusion_server.py --port 8100"}},
            {"type": "serve", "status": "ready", "payload": {"_cmd": "vllm serve --port 8004"}},  # no model id
            "not-a-dict",
        ]
    }
    assert _cookbook_served_models(state) == []


def test_served_models_dedupes_same_base_url():
    state = {
        "tasks": [
            {"type": "serve", "status": "ready", "modelId": "a", "payload": {"_cmd": "vllm serve a --port 8000"}},
            {"type": "serve", "status": "running", "modelId": "b", "payload": {"_cmd": "vllm serve b --port 8000"}},
        ]
    }
    out = _cookbook_served_models(state)
    assert len(out) == 1


def test_served_models_handles_dict_tasks_and_bad_state():
    assert _cookbook_served_models({}) == []
    assert _cookbook_served_models({"tasks": "nope"}) == []
    state = {"tasks": {"k": {"type": "serve", "status": "ready", "modelId": "x", "payload": {"_cmd": "vllm serve x --port 8000"}}}}
    assert _cookbook_served_models(state)[0]["model_id"] == "x"


def test_serve_base_url_helper():
    assert _serve_base_url("vllm serve m --port 8123", "") == "http://localhost:8123/v1"
    assert _serve_base_url("vllm serve m", "") == "http://localhost:8000/v1"
    assert _serve_base_url("x --port 7", "user@h") == "http://h:7/v1"
