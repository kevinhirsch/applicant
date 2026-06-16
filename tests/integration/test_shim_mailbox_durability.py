"""Durable mailbox on the file-backed shim (FR-DUR-1/3).

The shim is the DEFAULT orchestration backend. A final-approval decision sent via
``send`` BEFORE a restart must NOT be lost: a fresh orchestrator over the same
checkpoint directory (modelling a process restart) must be able to ``recv`` it.

Before the fix the mailbox was an in-process dict, so a decision sent before a
restart was gone and ``recv`` after restart returned ``None`` — the "mid-step crash
resumption" MUST was not met for the approval gate. This proves cross-restart
durability of the mailbox.
"""

from __future__ import annotations

import pytest

from applicant.adapters.orchestration.checkpoint_shim import CheckpointShimOrchestrator


@pytest.mark.integration
def test_mailbox_survives_restart(tmp_path):
    """FR-DUR-1/3: a decision sent before a restart is delivered after it."""
    ckpt = str(tmp_path / "ck")
    wf_id = "application:abc"
    topic = "final_approval"

    # send on one instance ...
    orch1 = CheckpointShimOrchestrator(ckpt)
    orch1.send(wf_id, topic, {"decision": "finished_by_engine"})

    # ... then a BRAND-NEW instance over the SAME dir (process restart) recvs it.
    orch2 = CheckpointShimOrchestrator(ckpt)
    payload = orch2.recv(wf_id, topic)
    assert payload == {"decision": "finished_by_engine"}


@pytest.mark.integration
def test_mailbox_recv_is_exactly_once_across_restart(tmp_path):
    """A delivered decision is popped durably — a later recv (even fresh) sees None."""
    ckpt = str(tmp_path / "ck2")
    wf_id = "application:xyz"
    topic = "final_approval"

    CheckpointShimOrchestrator(ckpt).send(wf_id, topic, {"decision": "submitted_by_user"})
    assert CheckpointShimOrchestrator(ckpt).recv(wf_id, topic) == {
        "decision": "submitted_by_user"
    }
    # Already consumed and persisted-popped: a fresh instance gets nothing.
    assert CheckpointShimOrchestrator(ckpt).recv(wf_id, topic) is None


@pytest.mark.integration
def test_mailbox_does_not_clobber_step_checkpoints(tmp_path):
    """Persisting the mailbox must not wipe checkpointed step results (same file)."""
    ckpt = str(tmp_path / "ck3")
    wf_id = "application:keep"
    orch = CheckpointShimOrchestrator(ckpt)
    orch.run_step(wf_id, "prefill", lambda: {"state": "AWAITING_FINAL_APPROVAL"})
    orch.send(wf_id, "final_approval", {"decision": "finished_by_engine"})

    fresh = CheckpointShimOrchestrator(ckpt)
    assert fresh.completed_steps(wf_id) == ["prefill"]
    assert fresh.recv(wf_id, "final_approval") == {"decision": "finished_by_engine"}
    # Popping the mailbox left the step checkpoint intact.
    assert CheckpointShimOrchestrator(ckpt).completed_steps(wf_id) == ["prefill"]
