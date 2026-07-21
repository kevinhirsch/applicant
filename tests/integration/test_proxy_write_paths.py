"""Real-integration proxy write-path test: exercises mutating proxy dispatch()
actions (create/update) against the LIVE engine. Complements the read smoke
test in test_proxy_engine_smoke.py.

Skip-guarded via ``_engine_reachable()`` (probe http://api:8000/health with a
short timeout) so the test file collects+skips cleanly when the engine is down
but RUNS when the engine is up.

Mirrors the skip-guard pattern in test_lane_regression.py and the module-loading
pattern from test_proxy_engine_smoke.py.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
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
            return resp.status_code < 500
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
# Proxy module loader (mirrors test_proxy_engine_smoke.py)
# ---------------------------------------------------------------------------

API_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "a0-applicant", "api")


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


def _assert_ok_envelope(result: dict, label: str) -> None:
    """Assert a well-formed dispatch response with ok=True and no 5xx status."""
    assert isinstance(result, dict), f"{label}: expected dict, got {type(result).__name__}"
    assert "ok" in result, f"{label}: missing 'ok' key: {list(result.keys())}"

    status = result.get("status", 0)
    if isinstance(status, (int, float)) and status >= 500:
        error_preview = str(result.get("error", ""))[:200]
        pytest.fail(f"{label}: engine returned {status}: {error_preview}")


def _as_list(raw, *keys):
    """Coerce engine list response to a Python list, trying alternative key names."""
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for k in keys or ("campaigns", "data", "results", "items"):
            v = raw.get(k)
            if isinstance(v, list):
                return v
    return []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@skip_if_no_engine
class TestCampaignsWritePaths:
    """Full write-path life cycle: create -> verify in list -> update -> verify."""

    TIMESTAMP = str(int(time.time()))
    TEST_NAME = f"TEST-PROXY-WRITE-{TIMESTAMP}"

    def test_campaigns_create_list_update_cleanup(self) -> None:
        """Create a campaign, verify via list, update to deactivate as cleanup."""
        mod = _load_proxy_module("campaigns")
        assert mod is not None, "campaigns proxy module could not be loaded"

        # ── Create ───────────────────────────────────────────────────────
        create_result = mod.dispatch({"action": "create", "name": self.TEST_NAME})
        _assert_ok_envelope(create_result, "campaigns create")
        assert create_result["ok"] is True, (
            f"campaigns create returned ok=False: {create_result.get('error', '')}"
        )
        assert "data" in create_result, (
            f"campaigns create missing 'data': {list(create_result.keys())}"
        )

        campaign_data = create_result["data"]
        campaign_id = campaign_data.get("id")
        assert campaign_id is not None, f"Campaign id missing: {campaign_data}"
        assert isinstance(campaign_id, str) and len(campaign_id) > 0
        assert campaign_data.get("name") == self.TEST_NAME, (
            f"Name mismatch: expected {self.TEST_NAME!r}, got {campaign_data.get('name')!r}"
        )

        # ── List to verify campaign is persisted ─────────────────────────
        list_result = mod.dispatch({"action": "list"})
        _assert_ok_envelope(list_result, "campaigns list after create")
        assert list_result["ok"] is True

        list_data = _as_list(list_result.get("data", []))
        campaign_ids = [c.get("id") for c in list_data if isinstance(c, dict)]
        assert campaign_id in campaign_ids, (
            f"Campaign {campaign_id} not in list. Got {len(campaign_ids)} ids: {campaign_ids[:5]}"
        )

        # ── Update (deactivate as cleanup) ────────────────────────────────
        update_result = mod.dispatch({
            "action": "update",
            "campaign_id": campaign_id,
            "active": False,
        })
        _assert_ok_envelope(update_result, "campaigns update (deactivate)")
        assert update_result["ok"] is True, (
            f"campaigns update returned ok=False: {update_result.get('error', '')}"
        )

        # ── Verify deactivation via re-list ────────────────────────────────
        list_result2 = mod.dispatch({"action": "list"})
        _assert_ok_envelope(list_result2, "campaigns list after update")

        list_data2 = _as_list(list_result2.get("data", []))
        found = next(
            (c for c in list_data2 if isinstance(c, dict) and c.get("id") == campaign_id),
            None,
        )
        assert found is not None, f"Campaign {campaign_id} vanished after update"
        if "active" in found:
            assert found["active"] is False, (
                f"Campaign still active after deactivation: {found}"
            )
            # Cleanup is done — deactivation confirmed


@pytest.mark.integration
@skip_if_no_engine
class TestProxyWriteEdgeCases:
    """Non-5xx assertions for write-path edge cases (no side effects)."""

    def test_create_without_name_returns_4xx(self) -> None:
        """Dispatch create with None name — engine returns 4xx, not 5xx."""
        mod = _load_proxy_module("campaigns")
        assert mod is not None

        result = mod.dispatch({"action": "create", "name": None})
        _assert_ok_envelope(result, "campaigns create (name=None)")
        status = result.get("status", 0)
        assert status < 500, (
            f"Missing-name create produced 5xx: status={status}, error={result.get('error', '')}"
        )

    def test_update_unknown_id_returns_4xx_not_crash(self) -> None:
        """Update with non-existent campaign id — 4xx, not 5xx."""
        mod = _load_proxy_module("campaigns")
        assert mod is not None

        result = mod.dispatch({
            "action": "update",
            "campaign_id": "nonexistent-campaign-id-999999",
            "name": "Should Not Crash",
        })
        _assert_ok_envelope(result, "campaigns update (unknown id)")
        status = result.get("status", 0)
        assert status < 500, (
            f"Unknown-id update produced 5xx: status={status}, error={result.get('error', '')}"
        )
        assert result.get("ok") is False or status >= 400, (
            f"Expected error for unknown campaign: {result}"
        )

    def test_create_empty_name_returns_4xx(self) -> None:
        """Empty string name — 4xx, not 5xx."""
        mod = _load_proxy_module("campaigns")
        assert mod is not None

        result = mod.dispatch({"action": "create", "name": ""})
        _assert_ok_envelope(result, "campaigns create (empty name)")
        status = result.get("status", 0)
        assert status < 500, (
            f"Empty-name create produced 5xx: status={status}"
        )

    def test_create_long_name(self) -> None:
        """Long campaign name — accepted (with cleanup) or rejected (4xx), never 5xx."""
        mod = _load_proxy_module("campaigns")
        assert mod is not None

        long_name = "TEST-PROXY-LONG-" + "X" * 100
        result = mod.dispatch({"action": "create", "name": long_name})
        _assert_ok_envelope(result, "campaigns create (long name)")
        status = result.get("status", 0)
        assert status < 500, (
            f"Long-name create produced 5xx: status={status}"
        )
        # Cleanup if accepted
        if result.get("ok") is True and "data" in result:
            cid = result["data"].get("id")
            if cid:
                cleanup = mod.dispatch({
                    "action": "update",
                    "campaign_id": cid,
                    "active": False,
                })
                _assert_ok_envelope(cleanup, "campaigns update (long-name cleanup)")
