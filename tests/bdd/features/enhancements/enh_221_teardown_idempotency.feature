# Issue #221 — application/workflows/application_pipeline.py (teardown step)
# The teardown step is checkpointed, so on resume a completed teardown returns its
# checkpointed result WITHOUT re-running the body — that idempotency-via-checkpoint
# IS GREEN. The residual gap: a crash BETWEEN ctx.teardown() succeeding and the
# checkpoint write means recovery re-runs teardown against an already-destroyed
# sandbox; there is no documented at-least-once / idempotent-by-contract guarantee
# on the teardown callback → @pending.

  Feature: Teardown is not re-executed against an already-released sandbox

  Scenario: A checkpointed teardown step does not run its body again on resume
    Given a checkpoint orchestrator over a temp directory
    And a workflow whose teardown step has run once and been checkpointed
    When the same teardown step is driven again over the same directory
    Then the teardown body does not run a second time

  Scenario: A workflow that reached teardown is not re-driven on recovery
    Given a checkpoint orchestrator over a temp directory
    And a workflow that ran through to its terminal teardown step
    When pending-workflow recovery runs
    Then the completed workflow is not listed for re-drive

  Scenario: A crash between teardown and its checkpoint cannot double-release the sandbox
    Given a pipeline whose teardown succeeded but crashed before checkpointing
    When the workflow is recovered and teardown is re-driven
    Then the second teardown is a contract-guaranteed no-op
