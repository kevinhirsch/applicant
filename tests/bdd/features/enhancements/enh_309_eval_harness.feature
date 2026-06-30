Feature: Browser-agent eval harness for the pre-fill planner
  # Issue #309 — research: docs/design/competitive-research.md
  # AgentLab + BrowserGym (Apache-2.0) as the A/B regression gate for the
  # plan-as-data planner: measure plan success rate / steps / cost per change, plus
  # an LLM-as-judge pass on generated-material quality. All @pending: no harness yet.

  Scenario: The planner is scored on a benchmark task set
    Given an eval harness wrapping the pre-fill planner
    When a benchmark task suite is run
    Then a success-rate, step-count, and cost metric is reported per run

  Scenario: A planner change is A/B gated against the baseline
    Given a baseline planner score and a candidate planner change
    When the harness compares candidate against baseline
    Then a regression in success rate fails the gate

  Scenario: Generated-material quality is judged by an LLM-as-judge pass
    Given a set of generated résumé/cover-letter materials
    When the LLM-as-judge evaluation runs
    Then each material receives a quality score against a rubric
