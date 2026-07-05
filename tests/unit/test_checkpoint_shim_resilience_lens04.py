"""Checkpoint-shim resilience regressions (lens 04, exhaustive2 audit #34/#36).

#34 — a workflow lease had no TTL and no steal path: a holder that never released it
(hard kill, OOM, `docker kill` mid-advance) stranded the lease forever, and the
workflow could never be claimed again. ``claim_workflow``/``lease`` now accepts a
``ttl_seconds`` and reclaims an expired lease instead of yielding ``False`` forever.

#36 — ``run_step`` ran ``fn`` exactly once: any raise propagated immediately with no
retry and no durable trace, conflating "transient blip" with "permanent failure" and
relying entirely on the outer tick loop to retry. ``run_step`` now retries a failing
step a bounded number of times before giving up, and checkpoints a failure record on
final exhaustion so the event leaves a trace instead of vanishing.
"""

from __future__ import annotations

import os
import time

from applicant.adapters.orchestration.checkpoint_shim import (
    DEFAULT_LEASE_TTL_SECONDS,
    CheckpointShimOrchestrator,
)


# ===========================================================================
# #34 — lease TTL + steal-on-expiry
# ===========================================================================
def _backdate(path, age_seconds: float) -> None:
    """Rewrite ``path``'s mtime to look ``age_seconds`` old (simulates a stale lease
    left by a holder that never released it)."""
    now = time.time()
    os.utime(path, (now - age_seconds, now - age_seconds))


def _simulate_stale_lease(orch: CheckpointShimOrchestrator, workflow_id: str, age_seconds: float):
    """Write a lease file directly to disk, bypassing ``claim_workflow`` entirely, to
    simulate what a hard-killed holder (OOM, `docker kill` mid-advance) leaves
    behind: a `.lease` file with no live process to ever release it.

    (Going through ``claim_workflow``'s own context manager and raising inside the
    ``with`` block does NOT simulate this: ``@contextlib.contextmanager``'s
    generator still runs its ``finally`` -- and therefore still releases the lease
    cleanly -- even when the ``with`` body raises. A real crash never reaches that
    `finally` at all, which is what direct file creation reproduces.)
    """
    lease_path = orch._lease_path(workflow_id)
    lease_path.parent.mkdir(parents=True, exist_ok=True)
    lease_path.write_bytes(b"99999")  # a pid that (almost certainly) isn't running
    _backdate(lease_path, age_seconds=age_seconds)
    return lease_path


def test_expired_lease_reclaim_after_simulated_crash(tmp_path):
    """A lease older than its TTL is reclaimed by a new claimant instead of being
    held forever (#34)."""
    ckdir = str(tmp_path / "ck")
    dead_holder = CheckpointShimOrchestrator(ckdir)
    lease_path = _simulate_stale_lease(dead_holder, "wf-2", age_seconds=DEFAULT_LEASE_TTL_SECONDS + 60)
    assert lease_path.exists()

    # A fresh process/instance over the same checkpoint dir must be able to steal
    # the expired lease rather than being told the workflow is unclaimable forever.
    new_holder = CheckpointShimOrchestrator(ckdir)
    with new_holder.claim_workflow("wf-2") as won:
        assert won is True, "an expired lease must be stealable, not held forever (#34)"


def test_unexpired_lease_is_not_stolen(tmp_path):
    """A lease still within its TTL is NOT reclaimed — stealing only kicks in once
    the holder is presumed dead."""
    ckdir = str(tmp_path / "ck")
    holder = CheckpointShimOrchestrator(ckdir)
    # Freshly "held" (age ~0s) -- well within a large TTL, i.e. a live holder.
    _simulate_stale_lease(holder, "wf-3", age_seconds=0.0)

    contender = CheckpointShimOrchestrator(ckdir)
    with contender.claim_workflow("wf-3", ttl_seconds=DEFAULT_LEASE_TTL_SECONDS) as won:
        assert won is False, "a live (unexpired) lease must not be stolen"


def test_lease_steal_respects_a_custom_short_ttl(tmp_path):
    """``ttl_seconds`` is a real, overridable parameter -- a short TTL reclaims a
    lease that only just went stale, without waiting out the (large) default."""
    ckdir = str(tmp_path / "ck")
    holder = CheckpointShimOrchestrator(ckdir)
    _simulate_stale_lease(holder, "wf-4", age_seconds=5.0)

    contender = CheckpointShimOrchestrator(ckdir)
    with contender.claim_workflow("wf-4", ttl_seconds=1.0) as won:
        assert won is True, "a short TTL should steal a lease older than it"


def test_normal_release_still_frees_the_lease_immediately(tmp_path):
    """Anti-regression: the ordinary clean-exit release path (no crash, no TTL
    involved) still works exactly as before -- the happy path is unchanged."""
    ckdir = str(tmp_path / "ck")
    orch = CheckpointShimOrchestrator(ckdir)
    with orch.claim_workflow("wf-5") as won:
        assert won is True
    # Released cleanly -- immediately re-claimable with no need to wait/steal.
    with orch.claim_workflow("wf-5") as won_again:
        assert won_again is True


def test_concurrent_in_process_claim_is_still_exclusive(tmp_path):
    """Anti-regression: two in-process claimants on the same live workflow still
    can't both win (the in-process lock path is untouched by the TTL/steal change)."""
    ckdir = str(tmp_path / "ck")
    orch = CheckpointShimOrchestrator(ckdir)
    with orch.claim_workflow("wf-6") as won_outer:
        assert won_outer is True
        with orch.claim_workflow("wf-6") as won_inner:
            assert won_inner is False


# ===========================================================================
# #36 — bounded retry + checkpoint-on-failure in run_step
# ===========================================================================
def test_transient_step_failure_is_retried_and_eventually_succeeds(tmp_path):
    """A step that fails a couple of times then succeeds is retried in-process
    instead of immediately propagating the first transient error, when a workflow
    opts into bounded retry (#36)."""
    orch = CheckpointShimOrchestrator(
        str(tmp_path / "ck"), step_retry_attempts=3, step_retry_backoff_seconds=0
    )
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("transient blip")
        return {"ok": True}

    result = orch.run_step("wf", "material", flaky)
    assert result == {"ok": True}
    assert calls["n"] == 3
    assert orch.step_result("wf", "material") == {"ok": True}
    assert "material" in orch.completed_steps("wf")


def test_retry_is_bounded_not_infinite(tmp_path):
    """A permanently-failing step exhausts a BOUNDED number of attempts and then
    re-raises -- retry is not unlimited (#36)."""
    orch = CheckpointShimOrchestrator(
        str(tmp_path / "ck"), step_retry_attempts=3, step_retry_backoff_seconds=0
    )
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise RuntimeError("permanent failure")

    try:
        orch.run_step("wf", "submit", always_fails)
        raised = False
    except RuntimeError:
        raised = True

    assert raised, "a permanent failure must still raise after retries are exhausted"
    assert calls["n"] == 3, "must attempt exactly the bounded number of times, not once and not forever"
    assert "submit" not in orch.completed_steps("wf")


def test_exhausted_retries_checkpoint_a_failure_record(tmp_path):
    """When every retry attempt fails, the failure is durably checkpointed (#36) so
    it leaves a trace instead of vanishing with the exception."""
    orch = CheckpointShimOrchestrator(
        str(tmp_path / "ck"), step_retry_attempts=2, step_retry_backoff_seconds=0
    )

    def always_fails():
        raise ValueError("boom")

    try:
        orch.run_step("wf", "prefill", always_fails)
    except ValueError:
        pass

    failure = orch.step_failure("wf", "prefill")
    assert failure is not None, "a checkpoint-on-failure record must be persisted (#36)"
    assert failure["attempts"] == 2
    assert failure["error_type"] == "ValueError"
    assert "boom" in failure["error"]

    # The record survives a "restart" (fresh instance over the same directory).
    fresh = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    assert fresh.step_failure("wf", "prefill") is not None


def test_failed_step_does_not_discard_other_steps_committed_progress(tmp_path):
    """A step that ultimately fails must not erase already-checkpointed progress
    from earlier, successful steps in the SAME workflow (#36's "loses progress")."""
    orch = CheckpointShimOrchestrator(
        str(tmp_path / "ck"), step_retry_attempts=2, step_retry_backoff_seconds=0
    )
    orch.run_step("wf", "prefill", lambda: {"filled": True})

    def always_fails():
        raise RuntimeError("downstream outage")

    try:
        orch.run_step("wf", "material", always_fails)
    except RuntimeError:
        pass

    # The earlier, already-committed step is untouched.
    assert orch.step_result("wf", "prefill") == {"filled": True}
    assert "prefill" in orch.completed_steps("wf")
    assert "material" not in orch.completed_steps("wf")


def test_success_after_a_prior_failure_clears_the_failure_record(tmp_path):
    """Once a step that previously exhausted its retries goes on to succeed on a
    later call, the stale failure record is cleared (introspection reflects the
    current, successful state -- not a ghost of the earlier failure)."""
    orch = CheckpointShimOrchestrator(
        str(tmp_path / "ck"), step_retry_attempts=1, step_retry_backoff_seconds=0
    )

    def always_fails():
        raise RuntimeError("still down")

    try:
        orch.run_step("wf", "material", always_fails)
    except RuntimeError:
        pass
    assert orch.step_failure("wf", "material") is not None

    result = orch.run_step("wf", "material", lambda: {"ok": True})
    assert result == {"ok": True}
    assert orch.step_failure("wf", "material") is None


def test_default_retry_policy_still_fails_on_first_attempt_but_checkpoints_it(tmp_path):
    """Anti-regression: with NO retry configuration (the out-of-the-box default),
    a failing step still runs ``fn`` exactly once and propagates immediately --
    identical to the pre-fix behavior relied on elsewhere (e.g. the durable-workflow
    integration test's kill-mid-step simulation). The only observable addition is
    that the single failure is now checkpointed (#36), not that it retries."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("dies immediately, like a real process kill would")

    try:
        orch.run_step("wf", "submit", boom)
        raised = False
    except RuntimeError:
        raised = True

    assert raised
    assert calls["n"] == 1, "default policy must not retry -- exactly one attempt, as before"
    failure = orch.step_failure("wf", "submit")
    assert failure is not None and failure["attempts"] == 1


def test_immediate_success_matches_prior_behavior_unchanged(tmp_path):
    """Anti-regression / happy-path: a step that succeeds on the first try behaves
    exactly as before -- ``fn`` runs exactly once, result is checkpointed."""
    orch = CheckpointShimOrchestrator(str(tmp_path / "ck"))
    calls = {"n": 0}

    def works():
        calls["n"] += 1
        return {"done": True}

    result = orch.run_step("wf", "teardown", works)
    assert result == {"done": True}
    assert calls["n"] == 1
    assert orch.step_failure("wf", "teardown") is None
