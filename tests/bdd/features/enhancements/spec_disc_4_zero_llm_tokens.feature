Feature: Structured discovery uses zero LLM tokens
  # FR-DISC-4 — service: src/applicant/application/services/discovery_service.py
  # Requirement: The structured discovery path MUST aggregate and dedup postings without
  # consuming any LLM tokens — the service has no LLM dependency and never calls one.

  Scenario: Running discovery never invokes an LLM
    Given a discovery service over a recording source with an LLM spy wired into storage
    When discovery runs for the campaign
    Then postings are returned from the structured source
    And the LLM spy was never called
