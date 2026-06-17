Feature: Channel setup gates automated work in the OOBE wizard
  # master spec §10 — FR-NOTIF-1, FR-OOBE-2/3

  Scenario: Configuring Discord and email completes the channel gate
    Given the LLM gate has been opened through the wizard
    When Discord and email channels are configured through the API
    Then the wizard reports the channels step complete
    And the configured notifier reports Discord and email channels

  Scenario: Automated work stays gated on onboarding regardless of channels
    # Channels are OPTIONAL now (they moved to Settings); onboarding still gates work.
    Given the LLM gate has been opened through the wizard
    Then automated work is not yet allowed
    When Discord and email channels are configured through the API
    Then automated work is still gated on remaining setup
