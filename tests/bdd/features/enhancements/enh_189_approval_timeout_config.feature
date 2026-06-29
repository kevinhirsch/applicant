# Issue #189 — adapters/orchestration/dbos_orchestrator.py (_INDEFINITE_WAIT_SECONDS)
# The final-approval recv gate is plumbed with an overridable timeout on the pipeline
# context (PipelineContext.approval_timeout flows into orchestrator.recv) — that seam
# IS GREEN. But the DBOS "wait forever" value is a hardcoded module constant (~10y)
# with no Settings field to tune it per deployment → @pending.

  Feature: The final-approval wait timeout is configurable, not magic

  Scenario: The pipeline passes an overridable approval-wait timeout to the gate
    Given a durable pipeline context with a custom approval-wait timeout
    Then the orchestration recv gate receives that timeout value

  Scenario: An absent context timeout falls through as an indefinite wait
    Given a durable pipeline context with no approval-wait timeout set
    Then the recv gate is asked to wait indefinitely

  @pending
  Scenario: The indefinite-wait duration is tunable through settings
    Given the engine settings
    Then an approval-wait timeout setting can be configured
