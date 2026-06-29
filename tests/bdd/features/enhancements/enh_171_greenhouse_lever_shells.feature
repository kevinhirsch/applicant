# Issue #171 — Greenhouse/Lever ATS adapters are shells (adapters/browser/ats.py) — FR-PREFILL-2 / NFR-EXT-1
# GREEN: the abstraction IS extensible — Greenhouse and Lever exist, resolve by URL,
#        and walk a page list with the boundary pages flagged.
# PENDING: they model only a handful of fields vs Workday's full flow, and major ATSes
#          (iCIMS, Taleo, SuccessFactors, BambooHR, Ashby) have no adapter at all.

Feature: Greenhouse and Lever ATS adapters resolve but model far fewer fields than Workday

  Scenario: Greenhouse and Lever resolve from their URLs without a core change
    Given the ATS registry
    When a Greenhouse posting URL and a Lever posting URL are resolved
    Then each resolves to its own dedicated adapter
    And both flows end on a final-submit page

  Scenario: The shell adapters model only a few fields each
    Given the ATS registry
    When the Greenhouse and Lever flows are walked
    Then Greenhouse exposes at most a handful of fields
    And Lever exposes fewer fields than the full Workday flow

  @pending
  Scenario: Greenhouse models the full real application form, not a proof-of-concept shape
    Given the ATS registry
    When the Greenhouse flow is walked for field-modeling parity with Workday
    Then it models the same breadth of real application fields as Workday

  @pending
  Scenario: A major ATS beyond the three shipped ones has its own adapter
    Given the ATS registry
    When an iCIMS posting URL is resolved
    Then a dedicated iCIMS adapter handles it
