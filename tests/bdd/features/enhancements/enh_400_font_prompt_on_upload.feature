Feature: Uploading a résumé prompts to install any missing fonts
  # Issue #400 — workspace/static/js/applicantOnboarding.js (_renderBaseResume) / FR-FONT-1
  # Requirement: On base-résumé upload the front-door MUST detect required fonts and, when
  # any are missing, surface an inline install prompt in the upload step (not buried in
  # Settings), confirming once installed.

  Scenario: A résumé with missing fonts surfaces an inline install prompt on upload
    Given the résumé upload step in the front-door onboarding
    When a résumé whose fonts are not installed is uploaded
    Then the upload step prompts inline to install the missing fonts
