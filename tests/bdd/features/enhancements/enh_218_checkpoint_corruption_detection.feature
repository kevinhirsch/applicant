# Issue #218 — adapters/orchestration/checkpoint_shim.py
# The shim persists JSON checkpoints with no integrity check. Mangled JSON is caught
# and treated as "no checkpoint" so the step safely re-executes — that defensive path
# IS GREEN. But there is no checksum / version marker / schema validation, so a
# truncated-but-still-parseable dict (disk full mid-write) is trusted as if complete;
# corruption is indistinguishable from absence → @pending.

  Feature: A corrupted checkpoint does not masquerade as completed work

  Scenario: Unparseable checkpoint JSON is treated as no checkpoint and the step reruns
    Given a checkpoint orchestrator over a temp directory
    And a workflow whose only step has already been checkpointed
    When the on-disk checkpoint file is overwritten with mangled bytes
    And the step is run again
    Then the step body executes again rather than returning stale data

  Scenario: A clean checkpoint round-trips and skips re-execution on resume
    Given a checkpoint orchestrator over a temp directory
    And a workflow whose only step has already been checkpointed
    When the step is run again over the same directory
    Then the checkpointed result is returned without re-running the body

  @pending
  Scenario: A truncated-but-parseable checkpoint is rejected as corrupt
    Given a checkpoint orchestrator over a temp directory
    When a checkpoint file is left structurally valid but missing its integrity marker
    Then loading it is flagged as corrupt rather than trusted as complete
