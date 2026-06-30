# Issue #344 — scoring_service.py:185-187 (no-criteria neutral default 0.75)
# Requirement: With no search criteria set a posting MUST score the documented neutral
# 0.75 (so onboarding shows everything); and discovery MUST require at least one
# criterion before it runs, so an unconfigured campaign cannot flood the digest.
Feature: Cold-start viability gate

  # GREEN — what ships today: no criteria => neutral 0.75 and the posting passes the gate.
  Scenario: A posting with no criteria is scored neutral so nothing is dropped
    Given a scoring service with no model configured
    And a campaign with no search criteria set
    When a posting is scored
    Then it receives the documented neutral score of seventy-five out of one hundred
    And the posting is considered viable

  # GREEN — the neutral rationale is plain-language, not jargon.
  Scenario: The neutral score explains itself in plain language
    Given a scoring service with no model configured
    And a campaign with no search criteria set
    When a posting is scored
    Then the rationale explains that no criteria are set yet

  # PENDING — the residual gap: discovery must refuse to run with zero criteria.
  Scenario: Discovery refuses to run until at least one criterion is set
    Given a campaign with no search criteria set
    When discovery is asked to run for that campaign
    Then it declines to run until at least one criterion is configured
