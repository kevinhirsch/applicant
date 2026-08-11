"""AZ3 (#845) Slice D — help-intent detection for chat dispatch.

Hermetic tests for _detect_help_intent() and dispatch() short-circuit.
The pure functions accept injected content so they are unit-testable
without the flask/api.help import chain.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import ANY, patch

import pytest

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
CHAT_PY = ROOT / "a0-applicant" / "api" / "chat.py"

# --- Sample help content (matches help_content.yaml structure) -----------
SAMPLE_CONTENT: dict = {
    "tracker": {
        "title": "Tracker",
        "steps": [
            "Open the tracker to see a pipeline view of all your applications.",
            "Filter by stage, campaign, or date range to focus on specific items.",
            "Drag applications between stages to update their progress.",
            "Click any application row to open its full detail view.",
        ],
        "prerequisites": "At least one application in flight",
    },
    "documents": {
        "title": "Documents",
        "steps": [
            "Upload application-related documents (resumes, cover letters, references).",
            "Preview and download files directly from the documents list.",
        ],
        "prerequisites": "A base resume or cover letter uploaded in your profile",
    },
    "chat": {
        "title": "Chat",
        "steps": ["Ask questions about your applications, documents, or campaigns."],
        "prerequisites": "A configured AI model endpoint",
    },
}

# --- Helpers for loading chat.py with stubs ------------------------------


def _load_chat_module():
    """Load chat.py with stubbed flask/helpers dependencies.

    Uses the importlib.util pattern established by test_az3_feedback_proxy.
    """
    if "helpers.api" not in sys.modules:
        helpers_api = types.ModuleType("helpers.api")
        helpers_api.ApiHandler = type("ApiHandler", (), {"process": lambda self, i, r: {}})
        sys.modules["helpers.api"] = helpers_api

    if "flask" not in sys.modules:
        flask = types.ModuleType("flask")
        flask.Request = type("Request", (), {})
        sys.modules["flask"] = flask

    spec = importlib.util.spec_from_file_location("chat", CHAT_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load spec from {CHAT_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =========================================================================
# Tests for _detect_help_intent
# =========================================================================


class TestDetectHelpIntent:
    """D4(a): pure unit tests for _detect_help_intent()."""

    def _make_module(self):
        return _load_chat_module()

    def test_how_do_i_matches_known_surface(self) -> None:
        """'How do I use the tracker?' matches 'tracker' via title containment."""
        mod = self._make_module()
        result = mod._detect_help_intent(
            "How do I use the tracker?",
            content=SAMPLE_CONTENT,
        )
        assert result == "tracker", f"expected 'tracker', got {result!r}"

    def test_how_does_known_surface(self) -> None:
        """'How does Documents work?' matches 'documents'."""
        mod = self._make_module()
        result = mod._detect_help_intent(
            "How does documents work?",
            content=SAMPLE_CONTENT,
        )
        assert result == "documents", f"expected 'documents', got {result!r}"

    def test_how_to_known_surface(self) -> None:
        """'How to chat?' matches 'chat'."""
        mod = self._make_module()
        result = mod._detect_help_intent(
            "How to chat?",
            content=SAMPLE_CONTENT,
        )
        assert result == "chat", f"expected 'chat', got {result!r}"

    def test_non_help_message_returns_none(self) -> None:
        """A plain message like 'send my resume' returns None."""
        mod = self._make_module()
        result = mod._detect_help_intent(
            "send my resume",
            content=SAMPLE_CONTENT,
        )
        assert result is None, f"expected None, got {result!r}"

    def test_help_intent_no_match_returns_none(self) -> None:
        """'How does the flux capacitor work?' — no surface title matches."""
        mod = self._make_module()
        result = mod._detect_help_intent(
            "How does the flux capacitor work?",
            content=SAMPLE_CONTENT,
        )
        assert result is None, f"expected None, got {result!r}"

    def test_empty_message_returns_none(self) -> None:
        """Empty string returns None."""
        mod = self._make_module()
        result = mod._detect_help_intent("", content=SAMPLE_CONTENT)
        assert result is None

    def test_non_string_message_returns_none(self) -> None:
        """Non-string message returns None."""
        mod = self._make_module()
        result = mod._detect_help_intent(42, content=SAMPLE_CONTENT)  # type: ignore[arg-type]
        assert result is None

    def test_none_content_loads_help_module(self) -> None:
        """When content=None (production path) the lazy import works
        because chat.py stubs helpers.api/flask in sys.modules, allowing
        api.help to load and find the real YAML content. Returns the
        matched surface id."""
        mod = self._make_module()
        result = mod._detect_help_intent("How do I use the tracker?", content=None)
        # After stubbing, the lazy import loads the real help_content.yaml
        # which contains 'tracker' with title 'Tracker'
        assert result is not None, "expected a surface match via lazy import"
        assert isinstance(result, str)


# =========================================================================
# Tests for dispatch short-circuit
# =========================================================================


class TestDispatchHelpShortCircuit:
    """D4(b): dispatch() short-circuits on help intent; non-help falls through."""

    @pytest.fixture
    def mod(self):
        return _load_chat_module()

    def test_help_intent_returns_answer_envelope(self, mod) -> None:
        """A 'how do I...' message matching a known surface returns
        the short-circuit envelope with answer, surface, deep_link."""
        # Patch _detect_help_intent to return a known surface
        with patch.object(mod, "_detect_help_intent", return_value="tracker"):
            result = mod.dispatch({
                "action": "send",
                "campaign_id": "test",
                "message": "How do I use the tracker?",
            })

        assert result is not None
        assert result.get("ok") is True
        assert result.get("status") == 200
        data = result.get("data", {})
        assert "answer" in data, f"missing 'answer' in {data}"
        assert data["surface"] == "tracker"
        assert data["deep_link"] == "help.html?surface=tracker"

    def test_help_intent_nonmatching_surface_falls_back_gracefully(self, mod) -> None:
        """When _detect_help_intent matches but content is unavailable,
        still returns ok:true with a graceful text fallback."""
        with patch.object(mod, "_detect_help_intent", return_value="nonexistent"):
            result = mod.dispatch({
                "action": "send",
                "campaign_id": "test",
                "message": "How does the nonexistent feature work?",
            })

        assert result is not None
        assert result.get("ok") is True
        assert result.get("status") == 200
        data = result.get("data", {})
        assert "answer" in data
        assert data["surface"] == "nonexistent"
        assert data["deep_link"] == "help.html?surface=nonexistent"

    def test_non_help_message_forwards_to_engine(self, mod) -> None:
        """A non-help message (no 'how do I…' pattern) falls through to
        _forward unchanged."""
        sentinel = {}

        with patch.object(mod, "_forward", return_value=sentinel) as mock_fwd:
            result = mod.dispatch({
                "action": "send",
                "campaign_id": "my_campaign",
                "message": "send my resume",
            })

        mock_fwd.assert_called_once_with("POST", "/api/chat", ANY)
        assert result is sentinel


# =========================================================================
# Meta: collection sanity
# =========================================================================


def test_module_collects_at_least_one() -> None:
    """Meta sanity: the test module must collect > 0 tests."""
    assert True, "Collection sanity check: this module exists."
