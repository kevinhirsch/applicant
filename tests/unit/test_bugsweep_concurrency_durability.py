"""Concurrency + durability bug-sweep regression tests (bugfix-sweep-2).

Each test cites the audited issue ID it locks down.
"""

from __future__ import annotations

import threading

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator


# --- CONC-1: shim checkpoint store must not lose concurrent writes -----------
def test_conc1_concurrent_run_step_all_persisted(tmp_path):
    """CONC-1: N concurrent ``run_step`` on one workflow all persist (no dropped
    checkpoints under the per-workflow lock)."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    n = 50
    barrier = threading.Barrier(n)

    def do(i: int) -> None:
        barrier.wait()  # maximize contention on the same workflow file
        orch.run_step("wf", f"s{i}", lambda i=i: i)

    threads = [threading.Thread(target=do, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    completed = orch.completed_steps("wf")
    assert len(completed) == n
    assert set(completed) == {f"s{i}" for i in range(n)}


def test_conc1_concurrent_send_all_delivered(tmp_path):
    """CONC-1: N concurrent ``send`` to one topic all land in the durable mailbox."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    n = 50
    barrier = threading.Barrier(n)

    def do(i: int) -> None:
        barrier.wait()
        orch.send("wf", "approval", {"i": i})

    threads = [threading.Thread(target=do, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    received = []
    while True:
        msg = orch.recv("wf", "approval")
        if msg is None:
            break
        received.append(msg["i"])
    assert sorted(received) == list(range(n))


# --- DUR-1: durable queues survive a restart (no slot re-grant) -------------
def test_dur1_concurrency_slot_survives_restart(tmp_path):
    """DUR-1: a held slot at capacity is NOT re-granted by a fresh orchestrator over
    the same checkpoint dir (no slot leak / cap breach)."""
    ckdir = str(tmp_path / "ck")
    orch = CheckpointShimOrchestrator(ckdir)
    orch.create_queue("sandbox", concurrency=1)
    assert orch.acquire("sandbox", "app-1") is True  # holds the only slot
    assert orch.acquire("sandbox", "app-2") is False  # cap reached -> waits

    # "Restart": brand-new orchestrator over the same dir.
    fresh = CheckpointShimOrchestrator(ckdir)
    # The slot is still held by app-1, so a new work id must NOT be admitted.
    assert fresh.acquire("sandbox", "app-3") is False
    state = fresh.queue_state("sandbox")
    assert state["active"] == ["app-1"]
    assert "app-3" in state["waiting"]


# --- DUR-2: terminal checkpoints are cleared / not re-driven ----------------
def test_dur2_clear_removes_checkpoint(tmp_path):
    """DUR-2: ``clear`` removes a completed workflow's checkpoint so it is not
    re-driven on the next startup."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    orch.run_step("wf-done", "prefill", lambda: {"state": "X"})
    assert "wf-done" in orch.recover_pending()
    orch.clear("wf-done")
    assert "wf-done" not in orch.recover_pending()


def test_dur2_recover_pending_skips_terminal_checkpoint(tmp_path):
    """DUR-2: a checkpoint that reached the terminal ``teardown`` step is excluded
    from ``recover_pending`` even if ``clear`` never ran (defense-in-depth)."""
    ckdir = str(tmp_path / "ck")
    orch = CheckpointShimOrchestrator(ckdir)
    # An in-flight (interrupted) workflow + a terminal one.
    orch.run_step("wf-inflight", "prefill", lambda: {"state": "AWAITING_FINAL_APPROVAL"})
    orch.run_step("wf-terminal", "prefill", lambda: {"state": "AWAITING_FINAL_APPROVAL"})
    orch.run_step("wf-terminal", "teardown", lambda: {"torn_down": True})

    # Fresh orchestrator (restart) must re-drive only the interrupted one.
    fresh = CheckpointShimOrchestrator(ckdir)
    pending = fresh.recover_pending()
    assert "wf-inflight" in pending
    assert "wf-terminal" not in pending
