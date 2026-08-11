"""EPIC MODEL-CONFIG — per-use-case model configuration proxy.

The model-config panel is served by the a0 shell, but the Applicant engine is
internal-only ("api:8000"). This handler forwards the UI's calls to the engine's
per-use-case model-config API, keeping the engine the single source of truth:

  * get_use_cases    -> GET    /api/setup/llm/use-cases
  * set_use_case     -> PUT    /api/setup/llm/use-cases/{use_case}
  * clear_use_case   -> DELETE /api/setup/llm/use-cases/{use_case}
  * get_smart_routing-> GET    /api/setup/llm/smart-routing
  * set_smart_routing-> PUT    /api/setup/llm/smart-routing
  * from_endpoint    -> POST   /api/setup/llm/from-endpoint  (deferred UI item)

Self-contained (plugin sibling-imports are unreliable); the pure "dispatch"/
"_forward" logic is module-level so it is unit-testable without the framework.
Mirrors ``a0-applicant/api/tiers.py``.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from helpers.api import ApiHandler
from flask import Request


def _engine() -> str:
    return os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def _forward(method: str, path: str, body: dict | None = None, timeout: int = 10) -> dict:
    """Call the engine; return a normalized ``{ok, status, data|error}`` envelope (never raises)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{_engine()}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode() or "{}"
            return {"ok": True, "status": r.status, "data": json.loads(raw) if raw.strip() else {}}
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}


def dispatch(input: dict) -> dict:
    inp = input or {}
    action = str(inp.get("action") or "get_use_cases").strip().lower()

    if action == "get_use_cases":
        return _forward("GET", "/api/setup/llm/use-cases")

    if action == "set_use_case":
        use_case = str(inp.get("use_case") or "").strip()
        if not use_case:
            return {"ok": False, "status": 400, "error": "use_case is required"}
        body = {
            "mode": inp.get("mode", "default"),
            "endpoint_id": inp.get("endpoint_id", ""),
            "model": inp.get("model", ""),
        }
        quoted = urllib.parse.quote(use_case, safe="")
        return _forward("PUT", f"/api/setup/llm/use-cases/{quoted}", body)

    if action == "clear_use_case":
        use_case = str(inp.get("use_case") or "").strip()
        if not use_case:
            return {"ok": False, "status": 400, "error": "use_case is required"}
        quoted = urllib.parse.quote(use_case, safe="")
        return _forward("DELETE", f"/api/setup/llm/use-cases/{quoted}")

    if action == "get_smart_routing":
        return _forward("GET", "/api/setup/llm/smart-routing")

    if action == "set_smart_routing":
        body = {}
        if "enabled" in inp:
            body["enabled"] = inp["enabled"]
        if "prefer_local" in inp:
            body["prefer_local"] = inp["prefer_local"]
        return _forward("PUT", "/api/setup/llm/smart-routing", body)

    if action == "from_endpoint":
        endpoint_id = str(inp.get("endpoint_id") or "").strip()
        model = str(inp.get("model") or "").strip()
        if not endpoint_id or not model:
            return {"ok": False, "status": 400, "error": "endpoint_id and model are required"}
        return _forward(
            "POST",
            "/api/setup/llm/from-endpoint",
            {"endpoint_id": endpoint_id, "model": model},
        )

    return {"ok": False, "status": 400, "error": f"unknown model_config action {action!r}"}


class ModelConfig(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict:
        return dispatch(input)
