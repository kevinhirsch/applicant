Feature: Onboarding intake sections are validated at the API boundary
  # Issue #318 — src/applicant/app/routers/onboarding.py:83-118 (SaveSectionIn)
  # Requirement: The onboarding save-section endpoint MUST reject structurally invalid
  # intake at the API boundary — an unknown section name is refused, and each section's
  # payload is validated against a typed schema rather than an untyped free-form dict.

  Scenario: An unknown section name is rejected at the boundary
    Given the onboarding save-section endpoint
    When a section whose name is not a known intake section is submitted
    Then the unknown section is rejected before it reaches the service

  Scenario: A section payload is validated against a typed schema
    Given the onboarding save-section request model
    When the request body is inspected for a typed per-section payload schema
    Then the payload is a typed model, not a free-form dict
