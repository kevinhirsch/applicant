Feature: Plan-as-data execution — typed-DSL planner over a semantic DOM
  # Issue #305 (epic) — design: docs/design/plan-as-data.md
  # Plan-once: the model emits a typed op-list over a semantic-DOM snapshot; the
  # camoufox/Playwright harness executes each op through the EXISTING guarded
  # actions. Safety holds by construction (fill/select resolve by attribute id,
  # consequential ops stay behind the stop-boundary, the scrape lane is network-less).
  # All scenarios are @pending: the planner does not exist yet (TDD red).

  @pending
  Scenario: A typed plan is validated before any browser action runs
    Given a planner that emits a typed operation list over a semantic-DOM snapshot
    When the plan is validated against the plan-as-data schema
    Then only typed operations from the allowed op-set are accepted
    And any op referencing an unknown attribute id is rejected before execution

  @pending
  Scenario: Fill operations resolve values by attribute id so the fabrication guard holds
    Given a typed plan whose fill ops reference attributes by id
    When the harness resolves each fill value from the attribute cloud
    Then every filled value traces back to a stored attribute, never an LLM free-text

  @pending
  Scenario: Consequential operations stay behind the stop-boundary
    Given a typed plan that includes a final-submit operation
    When the harness executes the plan up to the stop-boundary
    Then the final submit is withheld for human review and not auto-authorized

  @pending
  Scenario: The discovery/scrape lane is read-only and network-less
    Given a read-only scrape plan over a semantic-DOM snapshot
    When the read-only JS lane runs
    Then it can extract data but cannot issue network requests or mutate the page

  @pending
  Scenario: A unified PlannerPort drives all surfaces
    Given the engine exposes a PlannerPort driving port
    When a surface requests a plan
    Then the same typed-DSL contract is used across pre-fill, scrape, and the whole-application flow
