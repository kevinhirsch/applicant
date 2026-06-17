"""Coverage: update ROUTER + UpdateTrigger (src/applicant/app/routers/update.py).

The in-UI Update button invokes a guarded one-liner update script. Real dispatch is
opt-in (APPLICANT_UPDATE_ENABLED=1 AND the script must exist) so the default path is a
non-destructive dry-run. These tests drive: the index, the HTTP /trigger dry-run, the
"script not found" branch, and the opt-in real-dispatch branch with ``subprocess.Popen``
mocked so nothing actually runs. ``scripts/`` is never touched (a temp script is used).
"""

from __future__ import annotations

from pathlib import Path

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


def test_index(client):
    res = client.get("/api/update")
    assert res.status_code == 200
    assert res.json() == {"surface": "update", "status": "live", "phase": 4}


def test_trigger_http_is_dry_run_by_default(client):
    # APPLICANT_UPDATE_ENABLED is not set -> safe dry-run (started False).
    res = client.post("/api/update/trigger")
    assert res.status_code == 200
    body = res.json()
    assert body["started"] is False
    # The repo script exists, so the message is the "would invoke" dry-run note.
    assert "Dry run" in body["message"]


def test_trigger_router_blocked_before_llm_gate():
    app = create_app()
    with TestClient(app) as c:
        assert c.post("/api/update/trigger").status_code == 409


# --- UpdateTrigger unit branches (no app needed) ----------------------------
def test_trigger_reports_missing_script(tmp_path, monkeypatch):
    monkeypatch.delenv("APPLICANT_UPDATE_ENABLED", raising=False)
    missing = tmp_path / "does-not-exist.sh"
    result = UpdateTrigger(script_path=missing).trigger_update()
    assert result.started is False
    assert "not found" in result.message


def test_trigger_dry_run_when_script_present_but_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("APPLICANT_UPDATE_ENABLED", raising=False)
    script = tmp_path / "update.sh"
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    result = UpdateTrigger(script_path=script).trigger_update()
    assert result.started is False
    assert "Dry run" in result.message
    assert "update.sh" in result.message


def test_trigger_real_dispatch_when_enabled(tmp_path, monkeypatch):
    """With APPLICANT_UPDATE_ENABLED=1 AND the script present, the trigger dispatches the
    update detached. ``subprocess.Popen`` is mocked so no real process is spawned."""
    script = tmp_path / "update.sh"
    script.write_text("#!/bin/bash\necho hi\n", encoding="utf-8")
    monkeypatch.setenv("APPLICANT_UPDATE_ENABLED", "1")

    calls: list[list[str]] = []

    class _FakePopen:
        def __init__(self, args, **kwargs):
            calls.append(args)

    import subprocess

    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    result = UpdateTrigger(script_path=script).trigger_update()
    assert result.started is True
    assert "Started" in result.message
    # CRIT-ops fix: the enabled path MUST pass --apply so the script actually
    # performs the update (backup/migrate/restart) instead of a no-op dry run.
    assert calls == [["/bin/bash", str(script), "--apply"]]
    assert "--apply" in result.message


def test_default_script_path_points_at_repo_scripts():
    # Sanity: the resolved default path lands on scripts/update.sh under the repo root.
    trigger = UpdateTrigger()
    assert Path(trigger._script).name == "update.sh"
    assert "scripts" in str(trigger._script)
