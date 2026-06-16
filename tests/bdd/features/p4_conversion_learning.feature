Feature: Conversion is approval plus submission
  # master spec §10 ("Conversion is approval plus submission") — FR-LEARN-2/3/4/5, FR-LOG-4

  Scenario: A bare approval without submission is not yet a conversion
    Given a fresh learning model and an approved application
    When no submission outcome has been recorded
    Then the application is not counted as converted
    And the converting role signature stays empty

  Scenario: Approval plus a submission outcome marks the application converted
    Given a fresh learning model and an approved application
    When a submission outcome event is recorded for the application
    Then the application is counted as converted for the campaign
    And the converting role signature is updated for the next run

  Scenario: A one-tap mark-submitted (manual) outcome also closes the loop
    Given a fresh learning model and an approved application
    When a manual mark-submitted outcome event is recorded for the application
    Then the application is counted as converted for the campaign

  Scenario: Cross-referencing auto-applies a non-integral attribute
    Given an empty attribute store for a campaign
    When an input cross-references a non-integral attribute value
    Then the non-integral attribute is applied automatically

  Scenario: Cross-referencing holds an integral attribute at the confirmation gate
    Given an empty attribute store for a campaign
    When an input cross-references an integral attribute value without confirmation
    Then the integral attribute is not committed
    And the proposal requires user confirmation

  Scenario: A conversion shifts the next run's bias and survives a restart
    # FR-LEARN-2/5: closing the loop persists the learned signature per campaign.
    Given a stored campaign with an approved application and a submission outcome
    When the conversion loop is closed and the learning state persisted
    Then reloading the campaign learning state shows the converting-role signature
    And a bare approval in another campaign leaves that campaign's signature empty
