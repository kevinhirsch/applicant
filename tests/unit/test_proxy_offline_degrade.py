"""Hermetic offline-degrade contract sweep over every a0-applicant plugin API proxy.

DoD (AZ6-1 slice, #854): for every proxy in a0-applicant/api/*.py, point the
engine at an unroutable host and assert that dispatch() for a read/default
action (1) returns a dict, (2) NEVER raises, and (3) never produces a 5xx
envelope. Offline therefore yields the honest degrade envelope
``{"ok": False, "status": 0, "error": ...}`` that each handler's module-level
``_forward()`` produces (grounded: ``_forward`` never raises).

This is a UNIT test (hermetic — no live engine). The proxy-discovery
registry, SKIP-list, and stub-based module loader mirror
tests/integration/test_proxy_engine_smoke.py exactly. The only difference is
the engine is deliberately unreachable (ENGINE_URL=http://127.0.0.1:1) so the
offline contract is exercised unconditionally.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Proxy dispatch registry + SKIP list — mirrored exactly from
# tests/integration/test_proxy_engine_smoke.py (AZ6-1: discover the SAME way)
# ---------------------------------------------------------------------------

# Unroutable host: every forward to the engine fails with a connection error.
OFFLINE_ENGINE_URL = "http://127.0.0.1:1"

_PROXY_READ_REGISTRY: list[tuple[str, str, str]] = [
    ("agent_runs", "status", "reads agent-run status"),
    ("attributes", "list", "lists attributes"),
    ("audit", "log", "reads audit log"),
    ("campaigns", "list", "lists campaigns"),
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

# Same documented POST-only / no-safe-read proxies as the smoke test. They have
# no read/default action that forwards offline, but they stay crash-safe.
_NO_READ_ACTION_PROXIES: list[tuple[str, str]] = [
    ("chat", "POST-only (send/confirm) — no safe GET read action"),
    ("compare", "POST-only (applications/postings) — requires body payload"),
]

API_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "a0-applicant", "api"
)


def _load_proxy_module(stem: str) -> types.ModuleType | None:
    """Load an a0-applicant api module with stubs for helpers.api and flask."""
    path = os.path.join(API_DIR, f"{stem}.py")
    if not os.path.isfile(path):
        return None

    # Stub framework deps (mirrors test_proxy_engine_smoke.py verbatim)
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


@pytest.fixture
def offline_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every proxy's _engine() to an unroutable host (hermetic offline)."""
    monkeypatch.setenv("ENGINE_URL", OFFLINE_ENGINE_URL)


@pytest.mark.parametrize(
    ("proxy_stem", "action", "description"),
    _PROXY_READ_REGISTRY,
    ids=[f"{stem}/{action}" for stem, action, _ in _PROXY_READ_REGISTRY],
)
def test_proxy_offline_degrades_honestly(
    offline_engine: None,
    proxy_stem: str,
    action: str,
    description: str,
) -> None:
    """dispatch(read-action) -> dict, never raises, never 5xx when engine is down."""
    mod = _load_proxy_module(proxy_stem)
    assert mod is not None, f"{proxy_stem}.py could not be loaded"
    assert hasattr(mod, "dispatch"), f"{proxy_stem}.py has no dispatch()"

    result = mod.dispatch({"action": action})

    assert isinstance(result, dict), (
        f"{proxy_stem} dispatch({action!r}) returned {type(result).__name__}, expected dict"
    )
    status = result.get("status", 0)
    assert not (isinstance(status, (int, float)) and status >= 500), (
        f"{proxy_stem} dispatch({action!r}) returned {status}: 5xx while the engine "
        f"is offline — {description}. Result: {str(result)[:300]}"
    )
    # Honest offline degrade envelope: a failed forward must be {ok: False,
    # status: 0, error: ...} — exactly what api/*.py _forward() produces.
    if status == 0:
        assert result.get("ok") is False, (
            f"{proxy_stem} dispatch({action!r}) reported ok={result.get('ok')!r} with "
            f"status 0 — expected degrade envelope {{'ok': False, 'status': 0, 'error': ...}}"
        )
        assert result.get("error"), (
            f"{proxy_stem} dispatch({action!r}) status 0 is missing a real 'error': {result!r}"
        )


def test_proxy_offline_sweep_is_nonempty(offline_engine: None) -> None:
    """Guard against a silently-empty sweep (0 collected tests = 0 coverage)."""
    assert len(_PROXY_READ_REGISTRY) >= 1
    assert len(_NO_DISPATCH_PROXIES) >= 1
    assert len(_NO_READ_ACTION_PROXIES) >= 1


def test_proxy_skip_list_is_honest(offline_engine: None) -> None:
    """Documented no-dispatch proxies truly expose no module-level dispatch."""
    for stem, reason in _NO_DISPATCH_PROXIES:
        mod = _load_proxy_module(stem)
        assert mod is not None, f"{stem}.py could not be loaded"
        assert not hasattr(mod, "dispatch"), (
            f"{stem}.py claims '{reason}' but exposes dispatch(); SKIP list is stale"
        )


@pytest.mark.parametrize(
    ("proxy_stem", "reason"),
    _NO_READ_ACTION_PROXIES,
    ids=[stem for stem, _ in _NO_READ_ACTION_PROXIES],
)
def test_proxy_no_read_action_stays_crash_safe(
    offline_engine: None,
    proxy_stem: str,
    reason: str,
) -> None:
    """POST-only proxies: an empty/default call never raises and never 5xxs."""
    mod = _load_proxy_module(proxy_stem)
    assert mod is not None, f"{proxy_stem}.py could not be loaded"
    result = mod.dispatch({})
    assert isinstance(result, dict), (
        f"{proxy_stem} dispatch({{}}) returned {type(result).__name__}, expected dict"
    )
    status = result.get("status", 0)
    assert not (isinstance(status, (int, float)) and status >= 500), (
        f"{proxy_stem} dispatch({{}}) returned 5xx status {status} offline — {reason}"
    )
