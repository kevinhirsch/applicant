Feature: A per-tenant browser profile is reused across sessions
  # FR-STEALTH-3 — adapter: src/applicant/adapters/browser/stealth.py (ProfileStore)
  # Requirement: The profile store MUST return a stable per-tenant profile across
  # sessions and increment its visit count so a returning tenant is recognizable.

  Scenario: The same tenant gets a stable, visit-incrementing profile
    Given a per-tenant browser profile store
    When the same tenant is requested twice
    Then the same profile directory is returned both times
    And the visit count increments so the tenant looks like a returning visitor
