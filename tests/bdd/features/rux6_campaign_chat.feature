Feature: RUX-6 campaign chat takes gated, transparent, reversible actions
  # docs/APPLICANT-BACKLOG.md §EPIC REVIEW-UX — RUX-6
  # The "Ask anything to start a new chat" box talks to the campaign agent, which can
  # take actions (edit criteria, re-score, draft, discard) — but every side-effect routes
  # through the existing gates, is transparent + reversible, and NEVER auto-submits.

  Scenario: The chat can adjust a non-integral criterion directly
    Given a campaign chat with criteria and digest tools wired
    When the assistant edits the key skills through the chat tool
    Then the criteria service records the edit

  Scenario: An integral criteria change is held for the user's confirmation
    Given a campaign chat with criteria and digest tools wired
    When the assistant tries to change the salary floor through the chat tool
    Then the criteria service is not touched and the reply asks for confirmation

  Scenario: The chat can re-score without submitting anything
    Given a campaign chat with criteria and digest tools wired
    When the assistant re-scores through the chat tool
    Then the digest is rebuilt and nothing is submitted

  Scenario: Discarding a role requires a reason
    Given a campaign chat with criteria and digest tools wired
    When the assistant tries to discard a role with no reason
    Then no role is discarded and the assistant asks why

  Scenario: A discard with a reason archives the role reversibly
    Given a campaign chat with criteria and digest tools wired
    When the assistant discards a role with a reason
    Then the role is declined with that reason for learning

  Scenario: The campaign chat never offers a way to submit an application
    Given a campaign chat with criteria and digest tools wired
    Then no offered tool can submit an application
