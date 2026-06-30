# Issue #220 — adapters/orchestration/checkpoint_shim.py (_lock_for / run_step)
# The shim guards each load->mutate->save bracket with a per-workflow lock so two
# in-process callers (scheduler thread vs request handler) cannot read-modify-write
# over each other and drop a checkpoint — that locking IS GREEN. The residual gap is
# cross-process / external enforcement that only one tick ever advances a given
# workflow id at a time (no shared/file mutex) → @pending.

  Feature: Concurrent advances of one workflow do not drop checkpoint writes

  Scenario: Concurrent threads advancing one workflow each persist their step
    Given a checkpoint orchestrator over a temp directory
    When many threads checkpoint distinct steps of the same workflow at once
    Then every step result is durably recorded with none lost

  Scenario: The orchestrator exposes a distinct lock per workflow id
    Given a checkpoint orchestrator over a temp directory
    Then two different workflow ids resolve to two different locks
    And the same workflow id resolves to the same lock

  Scenario: Only one tick may advance a parked workflow at a time
    Given a checkpoint orchestrator over a temp directory
    Then it exposes a cross-process guard binding a workflow to a single advancing tick
