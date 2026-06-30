# Issue #171 — Greenhouse/Lever ATS adapters filled with real field maps (adapters/browser/ats.py) — FR-PREFILL-2 / NFR-EXT-1
# GREEN: the abstraction IS extensible — Greenhouse and Lever exist, resolve by URL,
#        and walk a page list with the boundary pages flagged.
# GREEN: both adapters now expose comprehensive ~20+ field maps covering personal info,
#        resume/cover-letter uploads, links, work authorisation, education, screening
#        questions, and EEO disclosures — matching Workday's field-model breadth.

Feature: Greenhouse and Lever ATS adapters model the same breadth of real application fields as Workday

  Scenario: Greenhouse and Lever resolve from their URLs without a core change
    Given the ATS registry
    When a Greenhouse posting URL and a Lever posting URL are resolved
    Then each resolves to its own dedicated adapter
    And both flows end on a final-submit page

  Scenario: The adapters model comprehensive real application field sets
    Given the ATS registry
    When the Greenhouse and Lever flows are walked
    Then Greenhouse exposes at least 20 distinct application fields covering personal info, resume, links, work authorisation, education, screening questions, and EEO disclosures
    And Lever exposes at least 20 distinct application fields covering the same breadth as Greenhouse and Workday

  Scenario: Greenhouse models the full real application form, not a proof-of-concept shape
    Given the ATS registry
    When the Greenhouse flow is walked for field-modeling parity with Workday
    Then it models the same breadth of real application fields as Workday

  Scenario: A major ATS beyond the three shipped ones has its own adapter
    Given the ATS registry
    When an iCIMS posting URL is resolved
    Then a dedicated iCIMS adapter handles it
