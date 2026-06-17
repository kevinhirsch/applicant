"""Tests for the Ollama model-management proxy (routes/ollama_routes.py).

Spins up a mock Ollama HTTP server so the proxy's status / list / pull (SSE) /
remove behavior is exercised end-to-end without a real Ollama daemon.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.middleware import require_admin
from routes.ollama_routes import setup_ollama_routes, _ollama_root


class _MockOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _json(self, code, obj):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        if self.path == "/api/tags":
            self._json(200, {"models": [
                {"name": "demo:latest", "size": 42, "modified_at": "now"}]})
        else:
            self._json(404, {})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        if self.path == "/api/pull":
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for line in ({"status": "pulling manifest"},
                         {"status": "pulling x", "total": 100, "completed": 100},
                         {"status": "success"}):
                self.wfile.write((json.dumps(line) + "\n").encode())
                self.wfile.flush()
        else:
            self._json(404, {})

    def do_DELETE(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self._json(200, {})


@pytest.fixture()
def mock_ollama(monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockOllama)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OLLAMA_BASE_URL", f"http://127.0.0.1:{port}/v1")
    yield f"http://127.0.0.1:{port}"
    srv.shutdown()


@pytest.fixture()
def client(mock_ollama):
    app = FastAPI()
    app.include_router(setup_ollama_routes())
    app.dependency_overrides[require_admin] = lambda: None  # bypass admin gate
    return TestClient(app)


def test_status_reports_reachable(client, mock_ollama):
    assert client.get("/api/ollama/status").json() == {
        "reachable": True, "endpoint": mock_ollama}


def test_list_models(client):
    data = client.get("/api/ollama/models").json()
    assert data["models"][0]["name"] == "demo:latest"


def test_pull_streams_progress_to_done(client):
    with client.stream("POST", "/api/ollama/pull", data={"name": "demo"}) as r:
        events = [json.loads(l[6:]) for l in r.iter_lines()
                  if l.startswith("data: ")]
    assert any(e.get("status") == "success" for e in events)
    assert events[-1].get("status") == "done"   # our terminal sentinel


def test_delete_model(client):
    assert client.delete("/api/ollama/models?name=demo").json() == {"ok": True}


def test_pull_requires_a_name(client):
    # Missing/empty Form field is rejected by validation (422), never proxied.
    assert client.post("/api/ollama/pull", data={}).status_code == 422


def test_delete_requires_a_name(client):
    assert client.delete("/api/ollama/models?name=").status_code == 400


@pytest.mark.parametrize("base,expected", [
    ("http://ollama:11434/v1", "http://ollama:11434"),
    ("http://host.docker.internal:11434/v1/", "http://host.docker.internal:11434"),
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
])
def test_ollama_root_strips_v1(monkeypatch, base, expected):
    monkeypatch.setenv("OLLAMA_BASE_URL", base)
    assert _ollama_root() == expected
