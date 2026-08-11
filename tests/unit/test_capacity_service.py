import pytest
from unittest.mock import MagicMock

from applicant.application.services.capacity_service import (
    CapacityService,
    SANDBOX_QUEUE,
    LLM_QUEUE,
)
from applicant.core.state_machine import ApplicationState


# ---------------------------------------------------------------------------
# Module-level autouse fixture for xdist parallel safety.
# CapacityService has no module-level cache to clear, but the pattern is
# required so the suite stays safe when other modules add global state.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _parallel_safety_autouse():
    """Reset any module-level state before each test.

    This module has none to clear, but the fixture is required for
    consistent xdist-safety across the project.
    """
    yield


class TestInit:
    """CapacityService.__init__ creates orchestrator queues."""

    @pytest.mark.unit
    def test_creates_sandbox_queue_with_default_concurrency(self):
        orch = MagicMock()
        CapacityService(orch)
        orch.create_queue.assert_called_once_with(SANDBOX_QUEUE, concurrency=3)

    @pytest.mark.unit
    def test_clamps_sandbox_concurrency_to_at_least_one(self):
        orch = MagicMock()
        CapacityService(orch, sandbox_concurrency=0)
        orch.create_queue.assert_called_once_with(SANDBOX_QUEUE, concurrency=1)

    @pytest.mark.unit
    def test_uses_custom_sandbox_concurrency(self):
        orch = MagicMock()
        CapacityService(orch, sandbox_concurrency=5)
        orch.create_queue.assert_called_once_with(SANDBOX_QUEUE, concurrency=5)

    @pytest.mark.unit
    def test_creates_llm_queue_when_limits_given(self):
        orch = MagicMock()
        CapacityService(orch, llm_limit=10, llm_period=60.0)
        assert orch.create_queue.call_count == 2
        orch.create_queue.assert_any_call(SANDBOX_QUEUE, concurrency=3)
        orch.create_queue.assert_any_call(
            LLM_QUEUE, limiter_limit=10, limiter_period=60.0
        )

    @pytest.mark.unit
    def test_does_not_create_llm_queue_when_limits_are_none(self):
        orch = MagicMock()
        CapacityService(orch, llm_limit=None, llm_period=None)
        orch.create_queue.assert_called_once_with(SANDBOX_QUEUE, concurrency=3)


class TestAdmitSandbox:
    """admit_sandbox delegates to orchestrator.acquire and returns bool."""

    @pytest.mark.unit
    def test_returns_true_when_acquired(self):
        orch = MagicMock()
        orch.acquire.return_value = True
        svc = CapacityService(orch)
        assert svc.admit_sandbox("app-1") is True
        orch.acquire.assert_called_once_with(SANDBOX_QUEUE, "app-1")

    @pytest.mark.unit
    def test_returns_false_when_not_acquired(self):
        orch = MagicMock()
        orch.acquire.return_value = False
        svc = CapacityService(orch)
        assert svc.admit_sandbox("app-2") is False


class TestYieldForBlock:
    """yield_for_block releases the sandbox slot only for yielding states."""

    @pytest.mark.unit
    def test_returns_promoted_for_yielding_state(self):
        orch = MagicMock()
        orch.release.return_value = "app-42"
        svc = CapacityService(orch)
        result = svc.yield_for_block(
            "app-1", ApplicationState.BLOCKED_DETECTION
        )
        assert result == "app-42"
        orch.release.assert_called_once_with(SANDBOX_QUEUE, "app-1")

    @pytest.mark.unit
    def test_returns_promoted_for_awaiting_final_approval(self):
        orch = MagicMock()
        orch.release.return_value = "app-43"
        svc = CapacityService(orch)
        result = svc.yield_for_block(
            "app-1", ApplicationState.AWAITING_FINAL_APPROVAL
        )
        assert result == "app-43"

    @pytest.mark.unit
    def test_returns_none_for_non_yielding_state(self):
        orch = MagicMock()
        svc = CapacityService(orch)
        result = svc.yield_for_block(
            "app-1", ApplicationState.DIGESTED
        )
        assert result is None
        orch.release.assert_not_called()

    @pytest.mark.unit
    def test_returns_none_for_failed_state(self):
        orch = MagicMock()
        svc = CapacityService(orch)
        result = svc.yield_for_block(
            "app-1", ApplicationState.FAILED
        )
        assert result is None


class TestReleaseSandbox:
    """release_sandbox delegates to orchestrator.release."""

    @pytest.mark.unit
    def test_returns_promoted_application_id(self):
        orch = MagicMock()
        orch.release.return_value = "app-99"
        svc = CapacityService(orch)
        result = svc.release_sandbox("app-1")
        assert result == "app-99"
        orch.release.assert_called_once_with(SANDBOX_QUEUE, "app-1")

    @pytest.mark.unit
    def test_returns_none_when_no_waiter(self):
        orch = MagicMock()
        orch.release.return_value = None
        svc = CapacityService(orch)
        result = svc.release_sandbox("app-1")
        assert result is None


class TestSandboxQueueState:
    """sandbox_queue_state introspection with and without queue_state."""

    @pytest.mark.unit
    def test_returns_active_waiting_supported_when_queue_state_present(self):
        orch = MagicMock()
        orch.queue_state.return_value = {
            "active": ["app-1", "app-2"],
            "waiting": ["app-3"],
        }
        svc = CapacityService(orch)
        result = svc.sandbox_queue_state()
        assert result == {
            "active": ["app-1", "app-2"],
            "waiting": ["app-3"],
            "supported": True,
        }
        orch.queue_state.assert_called_once_with(SANDBOX_QUEUE)

    @pytest.mark.unit
    def test_defends_missing_keys_in_queue_state_result(self):
        orch = MagicMock()
        orch.queue_state.return_value = {}  # empty — keys may be missing
        svc = CapacityService(orch)
        result = svc.sandbox_queue_state()
        assert result == {
            "active": [],
            "waiting": [],
            "supported": True,
        }

    @pytest.mark.unit
    def test_returns_unsupported_when_queue_state_not_implemented(self):
        # Use a spec that does NOT include queue_state, so getattr
        # with a default returns None instead of an auto-created child mock.
        orch = MagicMock(spec=["create_queue", "acquire", "release"])
        svc = CapacityService(orch)
        result = svc.sandbox_queue_state()
        assert result == {"active": [], "waiting": [], "supported": False}


class TestLLM:
    """admit_llm and release_llm on the LLM rate-limit queue."""

    @pytest.mark.unit
    def test_admit_llm_returns_true_when_acquired(self):
        orch = MagicMock()
        orch.acquire.return_value = True
        svc = CapacityService(orch, llm_limit=10, llm_period=60.0)
        assert svc.admit_llm("call-1") is True
        orch.acquire.assert_any_call(LLM_QUEUE, "call-1")

    @pytest.mark.unit
    def test_admit_llm_returns_false_when_not_acquired(self):
        orch = MagicMock()
        orch.acquire.return_value = False
        svc = CapacityService(orch, llm_limit=10, llm_period=60.0)
        assert svc.admit_llm("call-2") is False

    @pytest.mark.unit
    def test_release_llm_returns_promoted(self):
        orch = MagicMock()
        orch.release.return_value = "call-42"
        svc = CapacityService(orch, llm_limit=10, llm_period=60.0)
        result = svc.release_llm("call-1")
        assert result == "call-42"
        orch.release.assert_called_once_with(LLM_QUEUE, "call-1")

    @pytest.mark.unit
    def test_release_llm_returns_none_when_no_waiter(self):
        orch = MagicMock()
        orch.release.return_value = None
        svc = CapacityService(orch, llm_limit=10, llm_period=60.0)
        result = svc.release_llm("call-1")
        assert result is None
