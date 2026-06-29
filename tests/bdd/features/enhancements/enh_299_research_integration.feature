# Issue #299 — Research integration — company/role deep research before applications
# The deep-research proxy is mounted with a JS consumer (#259) and a per-campaign budget,
# and the engine has a research router (GREEN): an operator can trigger a manual research
# brief from a digest row. The feature wants research woven into the PIPELINE: auto
# company research before cover-letter generation, results attached to applications, and a
# research-quality learning loop. Those automatic-feed seams are absent, so they are @pending.

Feature: Research feeds the application pipeline

  Scenario: Manual research runs are reachable with a per-campaign budget
    Given the front-door application
    When the mounted routes are inspected
    Then the research run and budget paths are present under the research prefix

  @pending
  Scenario: Company research runs automatically before cover-letter generation
    Given an application about to generate a cover letter
    When the material-generation pipeline runs
    Then it first performs company research and enriches the generation context

  @pending
  Scenario: Research results are attached to the application for audit
    Given a completed research run for an application
    When the application record is read
    Then the research findings are stored as application-attached notes
