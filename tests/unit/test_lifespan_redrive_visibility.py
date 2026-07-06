"""DISC-12 — redrive failures must not be invisible.

``_redrive_pending`` (``app/lifespan.py``) re-drives every recovered pending
durable workflow on boot (FR-DUR-1). Previously a per-workflow redrive failure
was swallowed at ``log.info`` level with no aggregate signal, so a whole batch
of failed redrives could go unnoticed in both logs and ``/healthz``. This
verifies:

  * a per-workflow redrive failure is logged at WARNING (a genuine anomaly,
    not routine info), and
  * the function emits one batch-level summary log (``redrive_failed_batch``,
    WARNING) carrying both the failed and redriven counts, and
  * that summary is also surfaced onto the process's boot-health snapshot
    (the existing ``BootHealth`` mechanism, #48) so a failed-redrive batch is
    visible on ``/healthz`` too, and
  * none of this changes the best-effort contract: one failing workflow does
    not abort the batch, and the function still returns the redriven count.
"""

from __future__ import annotations

import applicant.app.lifespan as lifespan_mod
from applicant.observability.logging import configure_logging, recent_logs


class _FakeOrchestrator:
    def __init__(self, workflow_ids: list[str]) -> None:
        self._workflow_ids = workflow_ids

    def recover_pending(self) -> list[str]:
        return self._workflow_ids


class _FakeAgentLoop:
    """Redrives every workflow except the ones named in ``fail_on``."""

    def __init__(self, fail_on: set[str]) -> None:
        self._fail_on = fail_on

    def redrive_recovered(self, wf_id: str) -> None:
        if wf_id in self._fail_on:
            raise RuntimeError(f"workflow {wf_id} already running")


class _FakeContainer:
    def __init__(self, orchestrator: _FakeOrchestrator, agent_loop: _FakeAgentLoop) -> None:
        self.orchestrator = orchestrator
        self.agent_loop = agent_loop


def test_redrive_failure_logged_as_warning_with_aggregate_batch_summary(monkeypatch):
    configure_logging()

    # Isolate the process-lived BootHealth singleton so this test's failure
    # signal cannot leak into (or be polluted by) other tests in the run.
    fresh_boot_health = lifespan_mod.BootHealth()
    monkeypatch.setattr(lifespan_mod, "_boot_health", fresh_boot_health)

    workflow_ids = ["wf-good-1", "wf-bad", "wf-good-2"]
    container = _FakeContainer(
        orchestrator=_FakeOrchestrator(workflow_ids),
        agent_loop=_FakeAgentLoop(fail_on={"wf-bad"}),
    )

    redriven = lifespan_mod._redrive_pending(container)

    # Contract preserved: one failure does not abort the batch, and the
    # function still returns the count of successfully redriven workflows.
    assert redriven == 2

    events = recent_logs(limit=200)

    skipped = [e for e in events if e.get("event") == "redrive_skipped"]
    assert skipped, "expected a per-failure redrive_skipped log event"
    assert skipped[-1]["workflow_id"] == "wf-bad"
    assert skipped[-1]["level"] == "warning", "a redrive failure is a genuine anomaly, not info"

    batch = [e for e in events if e.get("event") == "redrive_failed_batch"]
    assert batch, "expected a single aggregate batch-summary log"
    assert batch[-1]["level"] == "warning"
    assert batch[-1]["failed"] == 1
    assert batch[-1]["redriven"] == 2

    # The aggregate failure is also visible on the boot-health snapshot used by
    # /healthz (existing mechanism, not new infra).
    snapshot = fresh_boot_health.snapshot()
    assert snapshot["degraded"] is True
    assert "durable_recovery_redrives" in snapshot["failed_steps"]


def test_all_successful_redrives_emit_no_batch_failure_signal(monkeypatch):
    configure_logging()

    fresh_boot_health = lifespan_mod.BootHealth()
    monkeypatch.setattr(lifespan_mod, "_boot_health", fresh_boot_health)

    workflow_ids = ["wf-good-1", "wf-good-2"]
    container = _FakeContainer(
        orchestrator=_FakeOrchestrator(workflow_ids),
        agent_loop=_FakeAgentLoop(fail_on=set()),
    )

    # recent_logs() is a process-wide ring buffer shared across the whole suite,
    # so a sibling test's redrive_failed_batch can linger in it — count the
    # baseline first and assert THIS call added none of its own.
    failures_before = len(
        [e for e in recent_logs(limit=500) if e.get("event") == "redrive_failed_batch"]
    )

    redriven = lifespan_mod._redrive_pending(container)

    assert redriven == 2

    failures_after = [
        e for e in recent_logs(limit=500) if e.get("event") == "redrive_failed_batch"
    ]
    assert len(failures_after) == failures_before

    snapshot = fresh_boot_health.snapshot()
    assert snapshot["degraded"] is False
    assert "durable_recovery_redrives" not in snapshot["steps"]
