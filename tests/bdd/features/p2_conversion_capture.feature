Feature: Conversion is approval plus submission (auto-detected or marked)
  # master spec §10 — Conversion = approval taste + final submission; learn real
  # conversion (FR-LOG-1/2/4, FR-LEARN-2). One-click live session (FR-SANDBOX-2).

  Scenario: The engine auto-detects the final submission from the confirmation page
    Given an application awaiting final approval in a controlled sandbox session
    When the user submits and the ATS shows a confirmation page
    Then the engine auto-detects the submission
    And a submitted outcome event is recorded for conversion learning
    And the application detail and per-page screenshots are logged

  Scenario: When auto-detection cannot confirm, the user marks it submitted
    Given an application in emergency data-handoff
    When the user taps mark-submitted
    Then a submitted outcome event is recorded for conversion learning
    And the application is logged as submitted by the user
