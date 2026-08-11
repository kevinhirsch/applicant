"""AZ3-5 (#843): Dormant-surface preservation — desktop assist + aggressiveness.

Pins that the two named surfaces are present in the registry with a reason,
the proxy forwards them, the endpoint supplies wiring_notes, and the panel
generically renders dormant-status surfaces as grayed/disabled with reason.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

# --- imports for registry + endpoint tests ---
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from applicant.dormant import DORMANT_SURFACES, STATUS_DORMANT, STATUS_LIVE

PANEL = Path(__file__).resolve().parents[2] / "a0-applicant/webui/dormant.html"
HANDLER = Path(__file__).resolve().parents[2] / "a0-applicant/api/dormant.py"


@pytest.fixture(scope="module")
def html() -> str:
    return PANEL.read_text(encoding="utf-8")


@pytest.fixture()
def mod():
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

    spec = importlib.util.spec_from_file_location("_az3_dormant", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRegistryPinsBothSurfaces:
    """resume_aggressiveness and desktop_assist exist in DORMANT_SURFACES with reason."""

    def test_resume_aggressiveness_present(self):
        keys = [s.key for s in DORMANT_SURFACES]
        assert "resume_aggressiveness" in keys

    def test_desktop_assist_present(self):
        keys = [s.key for s in DORMANT_SURFACES]
        assert "desktop_assist" in keys

    def test_both_have_nonempty_wiring_notes(self):
        by_key = {s.key: s for s in DORMANT_SURFACES}
        assert by_key["resume_aggressiveness"].wiring_notes
        assert by_key["desktop_assist"].wiring_notes


class TestEndpointIncludesWiringNotes:
    """The engine JSON response includes wiring_notes for every surface."""

    def test_response_contains_wiring_notes(self):
        from applicant.app.routers.ui import dormant_surfaces

        resp = dormant_surfaces()
        data = resp.body
        # Parse the JSON body
        import json

        items = json.loads(data.decode())
        assert isinstance(items, list)
        by_key = {item["key"]: item for item in items}
        assert "resume_aggressiveness" in by_key
        assert "desktop_assist" in by_key
        assert "wiring_notes" in by_key["resume_aggressiveness"]
        assert "wiring_notes" in by_key["desktop_assist"]
        assert by_key["resume_aggressiveness"]["wiring_notes"]
        assert by_key["desktop_assist"]["wiring_notes"]


class TestProxyForwardsDormantPath:
    """Proxy dispatch routes "list" to GET /api/dormant-surfaces."""

    def test_list_forwards_get(self, mod):
        seen = {}

        def fake(method, path, body=None, timeout=10):
            seen.update(method=method, path=path)
            return {"ok": True, "status": 200, "data": [{"key": "redline_surface", "name": "Redline Surface", "status": "live", "live_phase": "active"}]}

        with patch.object(mod, "_forward", fake):
            r = mod.dispatch({"action": "list"})
        assert seen == {"method": "GET", "path": "/api/dormant-surfaces"}
        assert r["ok"] is True
        assert r["data"][0]["key"] == "redline_surface"


class TestPanelRendersGrayedDormant:
    """Source assertion: panel HTML maps surfaces, applies disabled/grayed style when dormant, shows wiring_notes, no action button."""

    def test_reason_column_present(self, html):
        assert "s.wiring_notes" in html

    def test_dormant_grayed_style(self, html):
        # CSS rule targeting dormant rows with opacity/color/pointer-events
        assert "dormant-row" in html
        assert "opacity" in html or "pointer-events" in html or "color" in html

    def test_no_enabled_action_button(self, html):
        # The tbody template should not contain <button> elements
        tbody_start = html.find("<tbody>")
        tbody_end = html.find("</tbody>", tbody_start)
        tbody = html[tbody_start:tbody_end]
        assert "<button" not in tbody
        assert 'onclick' not in tbody

    def test_dormant_class_applied_conditionally(self, html):
        # Template condition on s.status === 'dormant' for class binding
        assert "s.status === 'dormant'" in html
        assert "dormant-row" in html
