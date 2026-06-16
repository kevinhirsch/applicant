Feature: Pending-actions portal lists and resolves live items
  # master spec §10 (Pending-actions portal) — FR-UI-3

  Scenario: Open pending actions are listed for the campaign
    Given a campaign with an open pending action
    When the pending-actions portal is queried
    Then the open action is listed

  Scenario: Resolving a pending action removes it from the portal
    Given a campaign with an open pending action
    When the action is resolved through the API
    Then the pending-actions portal lists no open items

  Scenario: Marking an application submitted records a manual outcome
    Given the LLM gate is open for outcomes
    When an application is marked submitted through the API
    Then a manual submitted outcome is recorded
