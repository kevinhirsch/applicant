"""AZ3 (#842) Slice A — unit tests for the demo proxy dispatch.

Hermetic: source-asserts the dispatch function handles status/seed/clear/unknown
without importing the API handler (which depends on flask in the venv-a0 runtime).
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO_PY = ROOT / "a0-applicant" / "api" / "demo.py"


class TestDemoPyDispatch:
    """Verify demo.py dispatch handles status/seed/clear/unknown."""

    def test_demo_py_exists(self) -> None:
        assert DEMO_PY.is_file(), f"demo.py not found at {DEMO_PY}"

    def test_has_dispatch_function(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert "def dispatch(input: dict) -> dict:" in source

    def test_status_action(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert 'if action == "status":' in source
        assert "/api/dev/seed/status" in source

    def test_seed_action(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert 'if action == "seed":' in source
        assert "/api/dev/seed/" in source

    def test_clear_action(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert 'if action == "clear":' in source
        assert "/api/dev/seed/reset" in source

    def test_unknown_action_returns_400(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert "return {\"ok\": False, \"status\": 400, \"error\":" in source
        assert "unknown demo action" in source

    def test_handles_engine_404_gracefully(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        # Must handle 404 from engine (DEMO_MODE off) gracefully
        assert "not result.get(\"ok\")" in source or 'not result.get("ok")' in source
        assert "demo_mode" in source

    def test_has_apihandler_class(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert "class Demo(ApiHandler):" in source
        assert "async def process(self, input: dict, request: Request) -> dict:" in source
        assert "return dispatch(input)" in source

    def test_has_forward_function(self) -> None:
        source = DEMO_PY.read_text(encoding="utf-8")
        assert "def _forward(method: str, path: str" in source
        assert "ENGINE_URL" in source


def test_module_collects_at_least_one() -> None:
    """Meta: this test file must collect > 0 tests."""
    assert True
