Feature: Email toolbar launcher is reachable for feature gating
  # Issue #260 — workspace/src/applicant_features.py + workspace/static/index.html
  # The email section references the nav id tool-email-btn for progressive activation, but
  # that element does not exist in the page, so the gating code silently skips it. The map
  # referencing the id is GREEN; the missing DOM element is the gap.

  Scenario: The email section references the email toolbar launcher
    Given the workspace Applicant section map
    When the email section nav ids are read
    Then the email toolbar launcher id is among them

  Scenario: The email toolbar launcher element exists in the page
    Given the front-door page markup
    When the email toolbar launcher element is looked up
    Then the email toolbar launcher element is present so it can be ungreyed
