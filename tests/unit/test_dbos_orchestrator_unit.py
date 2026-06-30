"""Hermetic unit tests for the DBOS orchestrator adapter (FR-DUR-1/2/3).

DBOS needs a live Postgres, so the real runtime is integration-gated. Here we
monkeypatch a STUB ``dbos`` module into ``sys.modules`` to assert the adapter
uses the supported API correctly:

* registration (``@DBOS.workflow`` / ``Queue`` / ``@DBOS.scheduled``) happens
  BEFORE ``DBOS.launch()`` (the single launch transition);
* ``run_step`` is invoked with ``(options, func)`` and a key that is DISTINCT per
  ``workflow_id`` (so concurrent apps with fixed step names do not collide);
* ``recover_pending`` does NOT call the nonexistent
  ``recover_pending_workflows()`` and returns ``[]``;
* ``recv(timeout=None)`` waits effectively forever (no 60s substitution).
"""

from __future__ import annotations

import sys
import types

import pytest


class _StubHandle:
    def __init__(self, result):
        self._result = result

    def get_result(self):
        return self._result


class _StubQueue:
    instances: list = []

    def __init__(self, name, *, concurrency=None, limiter=None):
        self.name = name
        self.concurrency = concurrency
        self.limiter = limiter
        _StubQueue.instances.append(self)


class _StubSetWorkflowID:
    def __init__(self, workflow_id):
        self.workflow_id = workflow_id

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _StubDBOS:
    """Records the ordering of registration vs launch + run_step/recv calls."""

    events: list = []
    run_step_calls: list = []
    recv_calls: list = []
    launched = False

    def __init__(self, *, config=None):
        type(self).events.append(("construct", config))

    @classmethod
    def workflow(cls, *, name=None):
        cls.events.append(("register_workflow", name))

        def deco(fn):
            return fn

        return deco

    @classmethod
    def scheduled(cls, cron):
        cls.events.append(("register_scheduled", cron))

        def deco(fn):
            return fn

        return deco

    @classmethod
    def launch(cls):
        cls.events.append(("launch", None))
        cls.launched = True

    @classmethod
    def run_step(cls, options, fn):
        cls.run_step_calls.append((options, fn))
        return fn()

    @classmethod
    def start_workflow(cls, shim, workflow_id, *args, **kwargs):
        return _StubHandle(shim(workflow_id, *args, **kwargs))

    @classmethod
    def send(cls, workflow_id, payload, topic=None):
        cls.events.append(("send", workflow_id, topic))

    @classmethod
    def recv(cls, topic=None, timeout_seconds=None):
        cls.recv_calls.append((topic, timeout_seconds))
        return {"recv": topic}


@pytest.fixture
def stub_dbos(monkeypatch):
    _StubDBOS.events = []
    _StubDBOS.run_step_calls = []
    _StubDBOS.recv_calls = []
    _StubDBOS.launched = False
    _StubQueue.instances = []
    module = types.ModuleType("dbos")
    module.DBOS = _StubDBOS
    module.DBOSConfig = dict
    module.Queue = _StubQueue
    module.SetWorkflowID = _StubSetWorkflowID
    monkeypatch.setitem(sys.modules, "dbos", module)
    return module


def _orch():
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    return DbosOrchestrator("postgresql://localhost/test")


def test_registration_happens_before_launch(stub_dbos):
    orch = _orch()
    orch.register_workflow("wf_a", lambda o, wid: None)
    orch.create_queue("sandbox", concurrency=2)
    orch.schedule("tick", "* * * * *", lambda st, at: None)
    # Nothing has launched yet (configure-only).
    assert _StubDBOS.launched is False
    assert not any(e[0] == "launch" for e in _StubDBOS.events)

    # An execution call triggers the single launch — AFTER all registration.
    orch.start_workflow("wf_a", "wf-1")
    events = [e[0] for e in _StubDBOS.events]
    launch_idx = events.index("launch")
    assert "register_workflow" in events[:launch_idx]
    assert "register_scheduled" in events[:launch_idx]
    # The Queue was constructed before launch too.
    assert _StubQueue.instances and _StubQueue.instances[0].name == "sandbox"
    # Exactly one launch.
    assert events.count("launch") == 1


def test_run_step_uses_options_and_distinct_keys_per_workflow(stub_dbos):
    orch = _orch()
    orch.register_workflow("wf", lambda o, wid: None)
    orch._ensure_launched()

    orch.run_step("wf-1", "prefill", lambda: 1)
    orch.run_step("wf-2", "prefill", lambda: 2)

    calls = _StubDBOS.run_step_calls
    # Invoked with (options, func): options is a dict, second arg is callable.
    assert all(isinstance(opts, dict) and callable(fn) for opts, fn in calls)
    keys = [opts["name"] for opts, _ in calls]
    # Same step name "prefill" across two workflows must NOT collide.
    assert keys[0] != keys[1]
    assert keys[0].startswith("wf-1:") and keys[1].startswith("wf-2:")


def test_recover_pending_does_not_call_nonexistent_api(stub_dbos):
    orch = _orch()
    # The stub deliberately lacks recover_pending_workflows; calling it would raise.
    assert not hasattr(_StubDBOS, "recover_pending_workflows")
    assert orch.recover_pending() == []
    assert _StubDBOS.launched is True  # recovery is implicit at launch


def test_recv_none_timeout_waits_indefinitely(stub_dbos):
    from applicant.adapters.orchestration.dbos_orchestrator import (
        _INDEFINITE_WAIT_SECONDS,
        DbosOrchestrator,
    )

    # The approval gate timeout is configurable (FR-DUR-3): 0 ⇒ wait indefinitely.
    # Build the orchestrator in that mode to exercise the indefinite-wait branch.
    orch = DbosOrchestrator("postgresql://localhost/test", approval_timeout_seconds=0.0)
    orch.register_workflow("gated", lambda o, wid: None)
    orch._ensure_launched()
    orch.recv("wf-1", "approval", timeout=None)
    topic, timeout_seconds = _StubDBOS.recv_calls[0]
    assert topic == "approval"
    # NOT the old 60s substitution.
    assert timeout_seconds == _INDEFINITE_WAIT_SECONDS
    assert timeout_seconds > 60.0


def test_recv_none_timeout_uses_configured_default(stub_dbos):
    # With a finite configured timeout (FR-DUR-3 default 30 days), recv(None) waits
    # that long — a timeout yields/re-parks (never auto-submits), so it is safe.
    from applicant.adapters.orchestration.dbos_orchestrator import DbosOrchestrator

    orch = DbosOrchestrator("postgresql://localhost/test", approval_timeout_seconds=2_592_000.0)
    orch.register_workflow("gated", lambda o, wid: None)
    orch._ensure_launched()
    orch.recv("wf-1", "approval", timeout=None)
    _topic, timeout_seconds = _StubDBOS.recv_calls[0]
    assert timeout_seconds == 2_592_000.0
    # Still far longer than the old premature 60s substitution.
    assert timeout_seconds > 60.0


def test_recv_explicit_timeout_passed_through(stub_dbos):
    orch = _orch()
    orch.register_workflow("gated", lambda o, wid: None)
    orch._ensure_launched()
    orch.recv("wf-1", "approval", timeout=10.0)
    assert _StubDBOS.recv_calls[0][1] == 10.0
