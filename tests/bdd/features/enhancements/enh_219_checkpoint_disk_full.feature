# Issue #219 — adapters/orchestration/checkpoint_shim.py (_save)
# The shim writes checkpoints atomically (tmp file + os.replace) so a crash mid-write
# never leaves a half-written checkpoint — that is GREEN. But a full disk (ENOSPC)
# raises OSError that propagates uncaught from run_step; there is no ENOSPC-specific
# handling that surfaces a critical health event instead of an infinite retry → @pending.

  Feature: A full disk is surfaced, not silently retried forever

  Scenario: The checkpoint write is atomic and leaves no partial file
    Given a checkpoint orchestrator over a temp directory
    When a step result is checkpointed
    Then exactly one checkpoint file exists and it parses cleanly

  Scenario: A disk-full write surfaces a critical health signal instead of crashing the step
    Given a checkpoint orchestrator over a temp directory whose disk is full
    When a step tries to checkpoint its result
    Then the orchestrator raises a recognizable out-of-space health signal
