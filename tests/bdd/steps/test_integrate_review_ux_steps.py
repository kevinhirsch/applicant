"""Step bindings for the Integrate step — REVIEW-UX + MODEL-CONFIG wiring seams.

Real regression coverage (no ``@pending`` tag): the wiring ships on this branch. The
steps drive the actual seams — ``register_routers`` (via ``create_app``),
``ChatService._maybe_toolbox``, the ``review`` proxy ``dispatch``, and the container's
``_effective_smart_routing`` — through in-memory doubles, never UI/network/DB.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pytest_bdd import given, scenarios, then, when

from applicant.app.container import _effective_smart_routing
from applicant.app.main import create_app
from applicant.application.services.chat_service import ChatService

scenarios("../features/integrate_review_ux.feature")

_PROXY = Path(__file__).resolve().parents[3] / "a0-applicant/api/review.py"


@pytest.fixture
def ictx() -> dict:
    return {}


# --- review router registered ------------------------------------------------
@given("the application is built")
def _app(ictx):
    ictx["app"] = create_app()


@then("the review router is mounted at /api/review")
def _review_mounted(ictx):
    paths: set[str] = set()
    for r in ictx["app"].routes:
        p = getattr(r, "path", None)
        if p:
            paths.add(p)
        orig = getattr(r, "original_router", None)
        if orig is not None:
            for sub in getattr(orig, "routes", []):
                sp = getattr(sub, "path", None)
                if sp:
                    paths.add(sp)
    assert any(p.startswith("/api/review") for p in paths)
    assert "/api/review/{application_id}/continue" in paths


# --- ChatService offers the RUX-6 action tools -------------------------------
class _FakeLLM:
    def is_configured(self):
        return True

    def supports_tools(self):
        return True

    def complete_with_tools(self, *a, **k):
        raise AssertionError("not called")


@given("a tool-capable campaign chat with the criteria and digest services it holds")
def _chat(ictx):
    ictx["chat"] = ChatService(
        attribute_service=object(),
        criteria_service=SimpleNamespace(),
        digest_service=SimpleNamespace(),
        llm=_FakeLLM(),
        chat_tools="auto",
    )


@when("the chat assembles its toolbox")
def _assemble(ictx):
    ictx["toolbox"] = ictx["chat"]._maybe_toolbox("camp-1")


@then("the toolbox offers edit_criteria, rescore, draft_application and discard_job")
def _offers(ictx):
    toolbox = ictx["toolbox"]
    assert toolbox is not None
    names = {s["function"]["name"] for s in toolbox.tool_schemas()}
    assert {"edit_criteria", "rescore", "draft_application", "discard_job"} <= names


# --- review proxy translates an action to the engine -------------------------
@given("the review proxy is loaded")
def _proxy(ictx):
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
    spec = importlib.util.spec_from_file_location("_az_review_bdd", _PROXY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ictx["proxy"] = mod


@when("the panel decides to continue an application")
def _decide_continue(ictx):
    mod = ictx["proxy"]
    seen: dict = {}

    def fake(method, path, body=None, timeout=30):
        if path == "/api/campaigns":
            return {"ok": True, "status": 200, "data": [{"id": "c1", "active": True}]}
        seen.update(method=method, path=path)
        return {"ok": True, "status": 200, "data": {}}

    with patch.object(mod, "_forward", fake):
        mod.dispatch({"action": "decide", "application_id": "app-1", "decision": "continue"})
    ictx["seen"] = seen


@then("the proxy forwards a POST to the engine continue endpoint")
def _forwarded(ictx):
    assert ictx["seen"]["method"] == "POST"
    assert ictx["seen"]["path"] == "/api/review/app-1/continue"


# --- smart-routing override precedence ---------------------------------------
@given("the environment default for smart routing is on")
def _env_on(ictx):
    ictx["settings"] = SimpleNamespace(
        llm_smart_routing=True, llm_smart_routing_prefer_local=False
    )


@when("the operator has persisted an override turning it off")
def _override_off(ictx):
    ictx["setup"] = SimpleNamespace(
        get_smart_routing=lambda: {"enabled": False, "prefer_local": None}
    )


@then("the effective smart-routing decision is off")
def _effective_off(ictx):
    enabled, _ = _effective_smart_routing(ictx["setup"], ictx["settings"])
    assert enabled is False
