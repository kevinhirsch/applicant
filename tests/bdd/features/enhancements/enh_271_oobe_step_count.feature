Feature: OOBE wizard step count matches the documented flow
  # Issue #271 — workspace/static/js/applicantOnboarding.js + README.md
  # The OOBE wizard defines three steps (welcome, connect a model, your profile); the
  # channels/fonts/sandbox renderers live in Settings. The three-step wizard is GREEN;
  # the README still describing a four-plus-step OOBE wizard is the gap.

  Scenario: The OOBE wizard defines three steps
    Given the onboarding wizard module
    When the wizard steps are counted
    Then the wizard defines exactly three steps

  Scenario: The README describes the three-step OOBE flow
    Given the README first-run setup section
    When the documented OOBE step count is read
    Then it matches the three-step wizard rather than claiming more
