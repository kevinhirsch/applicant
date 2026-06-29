Feature: Self-improvement learning flywheel — induce, curate, reflect
  # Issue #306 — research: docs/design/competitive-research.md
  # AWM (induce reusable workflows from successful trajectories) + ACE (curate an
  # evolving playbook via generation→reflection→curation) + Reflexion (verbal
  # self-reflection in episodic memory). Gets measurably better at each ATS the
  # more it applies, with no fine-tuning. All @pending: the flywheel is not built.

  @pending
  Scenario: A successful pre-fill induces a reusable per-ATS workflow
    Given a completed successful pre-fill trajectory for an ATS
    When the workflow-induction step runs over the trajectory
    Then a parameterized, reusable workflow for that ATS is stored as a planner prior

  @pending
  Scenario: An induced workflow is injected as a prior on the next matching application
    Given a stored induced workflow for an ATS
    When a new application targets the same ATS
    Then the induced workflow is retrieved and offered to the planner before planning from scratch

  @pending
  Scenario: The curation loop refines the playbook with delta updates
    Given an existing playbook of curated strategies
    When a generation and reflection pass produces new insights
    Then the playbook is updated with structured incremental deltas, not wholesale rewrites

  @pending
  Scenario: A failed run produces a verbal self-reflection in episodic memory
    Given a pre-fill run that failed on an ATS step
    When the reflection step runs over the failure
    Then a verbal lesson is written to episodic memory and recalled on the next similar attempt
