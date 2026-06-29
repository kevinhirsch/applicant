Feature: Visible labels in the Applicant forms associate to their control
  # Issue #388 — workspace/static/index.html:429-446,473-478,513-518 (tone:527 GREEN)
  # Requirement: Every visible label in the Applicant forms MUST associate to its control via for and id.

  Scenario: The Tone label is wired to its control
    Given the front-door page markup
    When the Tone control label is inspected
    Then it associates to its slider via a for attribute that matches the control id

  @pending
  Scenario: Every visible label associates to a real control
    Given the front-door page markup
    When the visible labels are compared to their for-associations
    Then every visible label points at a control id rather than sitting orphaned
