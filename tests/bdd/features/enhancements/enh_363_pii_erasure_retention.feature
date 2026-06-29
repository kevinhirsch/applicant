Feature: Deleting a campaign purges its PII/materials/credentials, bounded by a retention policy
  # Issue #363 — agent_memory.py:145 (forget_memory), RUN_RETENTION (#11); no campaign-delete purge
  # Requirement: Deleting a campaign (or user) MUST purge all associated résumés, parsed PII,
  # EEO answers, generated materials, and credentials (verifiably absent afterward), and a
  # configurable retention policy MUST bound how long stored PII is kept.
  #
  # Today only agent-memory forget (memory line removal) and rolling agent-run pruning
  # (RUN_RETENTION) exist. The first two scenarios are GREEN regression coverage for those
  # narrow erasure primitives; the campaign-wide purge and the PII retention policy are
  # @pending.

  Scenario: Forgetting a curated memory line removes it from the store
    Given a memory store holding a curated line
    When that line is forgotten
    Then the line is no longer present in the store

  Scenario: Rolling run pruning bounds how many agent runs are retained
    Given the agent-run service retention bound
    When old runs are pruned for a campaign
    Then no more than the configured number of runs is retained

  @pending
  Scenario: Deleting a campaign purges its PII, materials, and credentials
    Given a campaign with stored PII, generated materials, and banked credentials
    When the campaign is deleted
    Then all its PII, materials, and credentials are verifiably absent from storage

  @pending
  Scenario: A retention policy prunes PII older than the configured window
    Given a configurable PII retention window
    When the retention sweep runs
    Then PII older than the window is pruned while in-window PII is retained
