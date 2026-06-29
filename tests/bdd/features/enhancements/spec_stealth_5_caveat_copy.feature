Feature: Anti-detection is presented with an honest best-effort caveat
  # FR-STEALTH-5 — adapter: src/applicant/adapters/browser/stealth.py (STEALTH_CAVEAT/EGRESS_CAVEAT)
  # Requirement: The product MUST carry plain-language caveat copy stating anti-detection
  # is best-effort (never a guarantee) and that residential classification cannot be proven.

  Scenario: The anti-detection caveat copy is present and honest
    Given the stealth caveat copy
    When the caveat copy is read
    Then it states anti-detection is best-effort and never a guarantee

  Scenario: The egress caveat copy is present and honest
    Given the egress caveat copy
    When the egress caveat copy is read
    Then it states residential classification is best-effort and cannot be fully proven
