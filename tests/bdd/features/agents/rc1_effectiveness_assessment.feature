# EPIC AGENTS / RC1 — Effectiveness assessment (signals + cadence)
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Reflection Coach effectiveness assessment

  @pending
  Scenario: A daily evaluation runs once per campaign per day
    Given a campaign has been active for at least one day
    When the scheduler's daily tick fires
    Then the Reflection Coach produces one scored effectiveness assessment for that campaign
    And re-ticking the same day does not produce a second assessment

  @pending
  Scenario: An event-driven trigger fires an out-of-cadence evaluation
    Given a rejection, a response-rate/velocity stall, N applications sent, or a fit-score trend
      shift occurs
    When that event is detected
    Then the Reflection Coach evaluates immediately, independent of the daily cadence

  @pending
  Scenario: The assessment covers every required signal
    Given an effectiveness assessment runs
    Then it includes response/interview rate, velocity and time-in-stage, fit-score trend with
      user approve/discard/edit feedback, and funnel progress against the deadline
    And the result is recorded in the audit trail
