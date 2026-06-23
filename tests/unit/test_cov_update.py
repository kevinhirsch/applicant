"""Coverage: update ROUTER + UpdateTrigger control plane (src/applicant/app/routers/update.py).

The in-UI Update button is now a control plane over the `updater` sidecar: the api
drops a request flag in a shared control dir and the sidecar runs the real update.
These tests drive the status surface, the safe no-op trigger (no updater deployed),
the LLM gate, and the UpdateTrigger branches against a temp control dir — nothing
real is ever dispatched.
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from applicant.app.main import create_app
from applicant.app.routers.update import UpdateTrigger


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        r = c.post(
            "/api/setup/llm",
            json={"provider": "ollama", "base_url": "http://localhost:11434/v1", "model": "llama3.1"},
        )
        assert r.status_code == 204
        yield c


def test_index_returns_status_surface(client):
    res = client.get("/api/update")
    assert res.status_code == 200
    body = res.json()
    assert body["surface"] == "update"
    # No control volume in the test process -> idle + updater not available.
    assert body["state"] == "idle"
    assert body["updater_available"] is False
    assert body["log_tail"] == []


def test_trigger_http_safe_when_no_updater(client):
    # No updater heartbeat -> safe no-op (started False) with an actionable message.
    res = client.post("/api/update/trigger")
    assert res.status_code == 200
    body = res.json()
    assert body["started"] is False
    assert "updater" in body["message"].lower()


def test_trigger_router_blocked_before_llm_gate():
    app = create_app()
    with TestClient(app) as c:
        assert c.post("/api/update/trigger").status_code == 409


# --- UpdateTrigger control-plane branches (temp control dir) -----------------
def _beat(control_dir, *, age_s: float = 0.0) -> None:
    """Write a heartbeat file, optionally aged into the past."""
    alive = control_dir / "updater.alive"
    alive.write_text("", encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        import os

        os.utime(alive, (old, old))


def test_no_updater_is_safe_noop(tmp_path):
    result = UpdateTrigger(control_dir=tmp_path).trigger_update()
    assert result.started is False
    assert "normal way" in result.message
    # And nothing was written.
    assert not (tmp_path / "request").exists()


def test_stale_heartbeat_counts_as_no_updater(tmp_path):
    _beat(tmp_path, age_s=3600)  # an hour old -> stale
    trig = UpdateTrigger(control_dir=tmp_path)
    assert trig.status()["updater_available"] is False
    assert trig.trigger_update().started is False


def test_fresh_heartbeat_writes_request(tmp_path):
    _beat(tmp_path)
    trig = UpdateTrigger(control_dir=tmp_path)
    assert trig.status()["updater_available"] is True
    result = trig.trigger_update()
    assert result.started is True
    assert (tmp_path / "request").exists()


def test_trigger_blocks_when_already_running(tmp_path):
    _beat(tmp_path)
    (tmp_path / "status.json").write_text(
        json.dumps({"state": "running", "message": "Updating…"}), encoding="utf-8"
    )
    result = UpdateTrigger(control_dir=tmp_path).trigger_update()
    assert result.started is False
    assert "already" in result.message.lower()
    assert not (tmp_path / "request").exists()  # did not re-request


def test_status_reads_state_and_log_tail(tmp_path):
    _beat(tmp_path)
    (tmp_path / "status.json").write_text(
        json.dumps(
            {"state": "success", "message": "Update complete.", "started_at": "t0", "finished_at": "t1"}
        ),
        encoding="utf-8",
    )
    (tmp_path / "update.log").write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    st = UpdateTrigger(control_dir=tmp_path).status()
    assert st["state"] == "success"
    assert st["message"] == "Update complete."
    assert st["finished_at"] == "t1"
    assert len(st["log_tail"]) == 60  # tail is capped
    assert st["log_tail"][-1] == "line 199"


def test_status_tolerates_corrupt_files(tmp_path):
    (tmp_path / "status.json").write_text("not json{", encoding="utf-8")
    st = UpdateTrigger(control_dir=tmp_path).status()
    assert st["state"] == "idle"  # falls back cleanly
    assert st["updater_available"] is False
