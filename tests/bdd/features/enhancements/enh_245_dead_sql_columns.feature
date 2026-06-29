# Issue #245 — adapters/storage/models.py (JobPostingModel.normalized,
# GeneratedMaterialModel.redline_state)
# RevisionSessionModel.redline_state IS alive — it maps to RevisionSession.redline_state
# (GREEN). But JobPostingModel.normalized has no field on the JobPosting entity, and
# GeneratedMaterialModel.redline_state has no field on the GeneratedDocument entity;
# both are never read or written by the repository — dead weight in every DB → @pending.

  Feature: SQL models carry no dead columns absent from their entities

  Scenario: The revision-session redline state maps to a live entity field
    Given the domain entities
    Then the revision-session entity has a redline-state field

  Scenario: The live entities omit the dead columns
    Given the domain entities
    Then the job-posting entity has no normalized field
    And the generated-document entity has no redline-state field

  @pending
  Scenario: The job-posting model drops its dead normalized column
    Given the SQL models
    Then the job-posting model no longer declares a normalized column

  @pending
  Scenario: The generated-material model drops its dead redline-state column
    Given the SQL models
    Then the generated-material model no longer declares a redline-state column
