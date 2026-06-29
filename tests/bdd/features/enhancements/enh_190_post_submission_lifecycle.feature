# Issue #190 — No post-submission lifecycle (core/state_machine.py, core/entities/outcome_event.py) — FR-LOG-4/FR-LEARN-2
# GREEN: regression confirming the CURRENT shape — submitted/finished are terminal with
#        zero outgoing transitions, and OutcomeEvent only carries a "submitted" outcome.
# PENDING: post-submission outcomes (rejected / interview_invited / ghosted / offer)
#          and a lifecycle that continues past submit.

Feature: Application lifecycle continues past submit with real outcome types

  Scenario: Submitted and finished states are terminal today
    Given the application state machine
    When the outgoing transitions of the submitted and finished states are inspected
    Then each is terminal with no outgoing transitions

  Scenario: A recorded submission carries the submitted outcome type
    Given an application that has been recorded as submitted
    When its outcome events are listed
    Then a submitted outcome event is present

  @pending
  Scenario: A post-submission rejection outcome can be recorded
    Given an application that has been recorded as submitted
    When a rejection outcome is recorded against it
    Then the rejected outcome type is a recognized post-submission outcome

  @pending
  Scenario: Interview, ghosted, and offer are recognized post-submission outcomes
    Given the catalogue of post-submission outcome types
    When the recognized outcomes are enumerated
    Then interview, ghosted, and offer are all recognized
