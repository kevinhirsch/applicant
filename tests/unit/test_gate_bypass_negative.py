"""Negative tests: 3 enforcement layers that prevent bypass of the final-submit gate.

Layer 1 — MCP surface default-deny: POST /mcp/tools/call with a consequential tool
  name returns isError: True.
Layer 2 — Prefill boundary enforcement: ``ensure_action_allowed(FINAL_SUBMIT)``
  raises ``PrefillBoundaryViolation`` unless ``engine_submit_authorized=True``.
Layer 3 — Final approval gate: ``FinalApprovalService`` only proceeds via human
  decision — no auto-approve path exists.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from applicant.app.routers.mcp import _NATIVE_TOOL_SPECS, mount_mcp
from applicant.application.services.final_approval_service import FinalApprovalService
from applicant.core.errors import PrefillBoundaryViolation
from applicant.core.rules.prefill_boundary import StepKind, ensure_action_allowed


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """Parallel xdist safety — follows existing test convention."""
    return None


# ---------------------------------------------------------------------------
# Layer 1: MCP surface default-deny
# ---------------------------------------------------------------------------


class TestMCPConsequentialToolRefusal:
    """The MCP tool surface NEVER exposes consequential/submit tools and refuses
    them server-side."""

    @staticmethod
    def _build_app(*, gate_open: bool) -> FastAPI:
        container = MagicMock()
        container.storage = MagicMock()
        container.storage.campaigns.list.return_value = []
        container.storage.attributes.list.return_value = []
        container.storage.applications.list.return_value = []
        container.storage.pending_actions.list_open.return_value = []
        container.llm = MagicMock() if gate_open else None
        container.setup_service.is_setup_gate_open.return_value = gate_open

        app = FastAPI()
        app.state.container = container
        mount_mcp(app)
        return app

    def test_refuses_consequential_tool_by_name(self) -> None:
        """POST /mcp/tools/call with a consequential tool returns isError: True
        and the explicit refusal message."""
        app = self._build_app(gate_open=True)
        with TestClient(app) as client:
            resp = client.post(
                "/mcp/tools/call",
                json={"name": "submit_application"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["isError"] is True
        assert any(
            "Consequential actions stay behind human review and cannot be invoked here."
            in item.get("text", "")
            for item in body.get("content", [])
        )

    def test_native_specs_are_read_only(self) -> None:
        """_NATIVE_TOOL_SPECS only contains 5 read-only tools — no submit/finalize."""
        names = {t["name"] for t in _NATIVE_TOOL_SPECS}
        assert names == {
            "list_campaigns",
            "get_attributes",
            "get_applications",
            "get_pending_actions",
            "health",
        }, f"Unexpected tools in _NATIVE_TOOL_SPECS: {names}"


# ---------------------------------------------------------------------------
# Layer 2: Prefill boundary enforcement
# ---------------------------------------------------------------------------


class TestPrefillBoundaryEnforcement:
    """ensure_action_allowed enforces the prefill boundary — the agent's default
    state is NOT authorized to submit."""

    def test_final_submit_raises_without_auth(self) -> None:
        """Calling ensure_action_allowed(FINAL_SUBMIT) with the agent's default
        state (engine_submit_authorized=False) raises PrefillBoundaryViolation."""
        with pytest.raises(PrefillBoundaryViolation) as excinfo:
            ensure_action_allowed(StepKind.FINAL_SUBMIT)
        assert "Final submit requires explicit user authorization." in str(excinfo.value)

    def test_final_submit_allowed_with_explicit_auth(self) -> None:
        """Calling WITH engine_submit_authorized=True does NOT raise — proves
        this is the ONLY authorized path."""
        # Should not raise
        assert ensure_action_allowed(StepKind.FINAL_SUBMIT, engine_submit_authorized=True) is None


# ---------------------------------------------------------------------------
# Layer 3: Final approval gate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFinalApprovalGate:
    """The final approval gate ONLY proceeds via human decision."""

    def test_request_approval_returns_ref_handle(self) -> None:
        """request_approval only sends a notification and returns a ref handle
        — does NOT auto-submit."""
        orch = MagicMock()
        notif = MagicMock()
        notif.notify_decision.return_value = "handle-123"

        svc = FinalApprovalService(orchestrator=orch, notification_service=notif)
        ref = svc.request_approval("app-1", session_url="https://example.com/session")

        assert ref == "handle-123"
        notif.notify_decision.assert_called_once()
        # No auto-submit — orch.send should NOT have been called
        orch.send.assert_not_called()

    def test_await_decision_blocks_on_orchestrator_recv(self) -> None:
        """await_decision waits for a durable recv — it blocks until a human
        decision arrives."""
        orch = MagicMock()
        expected_payload = {"decision": "submitted_by_user"}
        orch.recv.return_value = expected_payload

        svc = FinalApprovalService(orchestrator=orch)
        result = svc.await_decision("wf-42", timeout=30.0)

        assert result == expected_payload
        orch.recv.assert_called_once_with("wf-42", "final_approval", timeout=30.0)

    def test_submit_decision_sends_through_orchestrator(self) -> None:
        """submit_decision delivers the human's decision via orchestrator.send
        — this is the ONLY delivery path."""
        orch = MagicMock()

        svc = FinalApprovalService(orchestrator=orch)
        svc.submit_decision("wf-42", "app-1", "submitted_by_user")

        orch.send.assert_called_once_with(
            "wf-42", "final_approval", {"decision": "submitted_by_user"}
        )

    def test_no_auto_approve_method_exists(self) -> None:
        """FinalApprovalService has NO method that auto-approves.

        The only public methods are request_approval, await_decision,
        submit_decision, acted, and escalate — none auto-approves."""
        svc = FinalApprovalService(orchestrator=MagicMock())
        public_methods = {
            name
            for name, value in type(svc).__dict__.items()
            if callable(value) and not name.startswith("_")
        }
        assert public_methods == {
            "request_approval",
            "await_decision",
            "submit_decision",
            "acted",
            "escalate",
        }, f"Unexpected methods found: {public_methods}"
        # None of these methods bypass human review
