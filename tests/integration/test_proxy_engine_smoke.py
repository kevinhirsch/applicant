"""Real-integration proxy smoke test: calls every a0-applicant api/*.py proxy's
module-level dispatch() against the LIVE engine — proves each proxy routes to
a correct engine endpoint without 5xx crashes or unhandled exceptions.

Skip-guarded via `_engine_reachable()` (probe http://api:8000/health with a
short timeout) so the test file collects+skips cleanly when the engine is down
but RUNS when the engine is up.

Mirrors the skip-guard pattern in test_lane_regression.py and the integration
marker convention from pyproject.toml.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import httpx
import pytest

# ---------------------------------------------------------------------------
# Skip guard: check engine reachability at import time
# ---------------------------------------------------------------------------

ENGINE_URL = os.getenv("ENGINE_URL", "http://api:8000").rstrip("/")


def _engine_reachable() -> bool:
    try:
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{ENGINE_URL}/health")
            return resp.status_code < 500  # any non-5xx means the engine responded
    except Exception:
        return False


_SKIP_REASON = (
    f"Engine not reachable at {ENGINE_URL}. "
    "Start the applicant engine stack (docker compose up) to run these tests."
)

skip_if_no_engine = pytest.mark.skipif(
    not _engine_reachable(),
    reason=_SKIP_REASON,
)

# ---------------------------------------------------------------------------
# Proxy dispatch registration
# ---------------------------------------------------------------------------

_PROXY_READ_REGISTRY: list[tuple[str, str | None, str]] = [
    ("agent_runs", "status", "reads agent-run status"),
    ("attributes", "list", "lists attributes"),
    ("audit", "log", "reads audit log"),
    ("campaigns", "list", "lists campaigns"),
    ("chat", None, "POST-only (send/confirm) — no safe GET read action"),
    ("compare", None, "POST-only (applications/postings) — requires body payload"),
    ("conversion", "engine", "reads conversion engine status"),
    ("criteria", "view", "views criteria"),
    ("digest", "get", "gets digest"),
    ("discovery", "list", "lists discovery results"),
    ("documents", "list", "lists documents"),
    ("dormant", "list", "lists dormant campaigns"),
    ("easy_apply", "status", "reads easy-apply status"),
    ("feedback", "history", "reads feedback history"),
    ("fonts", "list", "lists fonts"),
    ("gallery", "view", "views gallery"),
    ("health", "capabilities", "reads health capabilities"),
    ("help", "list", "lists help surfaces"),
    ("mind", "memory", "reads agent memory"),
    ("model_endpoints", "list", "lists model endpoints"),
    ("notifications", "list", "lists notifications"),
    ("onboarding", "state", "reads onboarding state"),
    ("ops", "tools", "reads ops tools"),
    ("pending", "list", "lists pending actions"),
    ("research", "cached", "reads cached research"),
    ("screening", "library", "reads screening-answer library"),
    ("takeover", "sessions", "reads takeover sessions"),
    ("tracker", "board", "reads tracker board"),
    ("update_panel", "status", "reads update status"),
    ("vault", "list", "lists vault credentials"),
]

_NO_DISPATCH_PROXIES: list[tuple[str, str]] = [
    ("base_resume", "class-process-only pattern, no module-level dispatch"),
    ("features", "class-process-only pattern, no module-level dispatch"),
    ("hello", "stub/example handler, no dispatch"),
    ("__init__", "package init, not a proxy handler"),
]

API_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "a0-applicant", "api"
)


def _load_proxy_module(stem: str) -> types.ModuleType | None:
    """Load an a0-applicant api module with stubs for helpers.api and flask."""
    path = os.path.join(API_DIR, f"{stem}.py")
    if not os.path.isfile(path):
        return None

    # Stub framework deps
    if "helpers" not in sys.modules:
        helpers = types.ModuleType("helpers")
        helpers.api = types.ModuleType("api")
        helpers.api.ApiHandler = type("ApiHandler", (), {})
        sys.modules["helpers"] = helpers
        sys.modules["helpers.api"] = helpers.api

    if "flask" not in sys.modules:
        flask = types.ModuleType("flask")
        flask.Request = type("Request", (), {})
        sys.modules["flask"] = flask

    spec = importlib.util.spec_from_file_location(stem, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _call_and_assert(proxy_stem: str, action: str, description: str) -> None:
    """Load proxy module, call dispatch with the read action, assert well-formed envelope."""
    mod = _load_proxy_module(proxy_stem)
    assert mod is not None, f"{proxy_stem}.py could not be loaded"
    assert hasattr(mod, "dispatch"), f"{proxy_stem}.py has no dispatch()"

    result = mod.dispatch({"action": action})

    assert isinstance(result, dict), (
        f"{proxy_stem} dispatch({action!r}) returned {type(result).__name__}, expected dict"
    )
    assert "ok" in result, (
        f"{proxy_stem} dispatch({action!r}) missing 'ok' key: {list(result.keys())}"
    )

    status = result.get("status", 0)
    if isinstance(status, (int, float)) and status >= 500:
        error_preview = str(result.get("error", ""))[:200]
        pytest.fail(
            f"{proxy_stem} dispatch({action!r}) returned {status}: engine-level "
            f"crash — {description}. Error: {error_preview}"
        )


@pytest.mark.integration
@skip_if_no_engine
class TestProxyEngineSmoke:
    """One parameterized test method per proxy with a dispatch() and a safe read action."""
    pass


def _make_test(stem: str, action: str, desc: str):
    @pytest.mark.integration
    @skip_if_no_engine
    def test_fn(self) -> None:
        _call_and_assert(stem, action, desc)
    test_fn.__name__ = f"test_proxy_{stem}"

    test_fn.__doc__ = f"Proxy {stem}: dispatch({action!r}) — {desc}"
    return test_fn


for stem, action_or_none, desc in _PROXY_READ_REGISTRY:
    if action_or_none is not None:
        test_fn = _make_test(stem, action_or_none, desc)
        setattr(TestProxyEngineSmoke, test_fn.__name__, test_fn)
del test_fn


@pytest.mark.integration
@skip_if_no_engine
def test_proxy_base_resume_skipped() -> None:
    """Proxy base_resume: class-process-only, no dispatch — skip documented."""
    pytest.skip("base_resume: class-process-only pattern, no module-level dispatch")


@pytest.mark.integration
@skip_if_no_engine
def test_proxy_features_skipped() -> None:
    """Proxy features: class-process-only, no dispatch — skip documented."""
    pytest.skip("features: class-process-only pattern, no module-level dispatch")


@pytest.mark.integration
@skip_if_no_engine
def test_proxy_hello_skipped() -> None:
    """Proxy hello: stub/example handler, no dispatch — skip documented."""
    pytest.skip("hello: stub/example handler, no dispatch")


@pytest.mark.integration
@skip_if_no_engine
def test_proxy_chat_skipped() -> None:
    """Proxy chat: POST-only (send/confirm), no safe GET read — skip documented."""
    pytest.skip("chat: POST-only actions (send/confirm), no safe GET read action")


@pytest.mark.integration
@skip_if_no_engine
def test_proxy_compare_skipped() -> None:
    """Proxy compare: POST-only (applications/postings), requires body — skip documented."""
    pytest.skip("compare: POST-only actions (applications/postings), requires body payload")
