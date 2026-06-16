Feature: Zero-CLI out-of-box setup with an LLM gate
  # master spec §10 (FR-OOBE-1, FR-UI-5)

  Scenario: Automated work is blocked until the LLM is configured
    Given a freshly booted Applicant instance
    When I request a gated route before configuring the LLM
    Then the gate returns 409
    When I configure the LLM through the UI settings endpoint
    Then the gated route is reachable
    And no command line was required

  Scenario: Automated work cannot begin until LLM configured and onboarding complete
    # master spec FR-ONBOARD-2, FR-OOBE-3 (NFR-ZEROCLI-1)
    Given a freshly booted Applicant instance
    Then automated work may not begin
    When I configure the LLM through the UI settings endpoint
    Then automated work may not begin
    When I configure notification channels through the UI
    Then automated work may not begin
    When I complete the Workday-ready onboarding intake through the UI
    Then automated work may begin
    And no command line was required
