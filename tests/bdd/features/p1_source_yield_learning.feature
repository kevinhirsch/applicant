Feature: Source-yield learning with an exploration budget
  # master spec §10 (Source-yield learning with exploration) — FR-DISC-5, FR-LEARN-6

  Scenario: High-yielding sources are favored after a run
    Given a fresh learning model for a campaign
    When source yields from a run are recorded
    Then the higher-yielding source ranks above the lower-yielding one

  Scenario: The exploration budget reserves effort for unseen sources
    Given a learning model that has only ever seen one source
    When the exploit and explore sets are computed over several sources
    Then at least one unseen source is reserved for exploration
