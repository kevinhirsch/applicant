# Issue #173 — Unknown ATS falls through to Workday (adapters/browser/ats.py resolve_ats) — FR-PREFILL-2
# GREEN: regression documenting the CURRENT behaviour — an unknown URL resolves to Workday.
# PENDING: the desired fix — an unsupported ATS should be reported as unsupported
#          (None / a sentinel) rather than silently applying the Workday page model.

Feature: An unknown ATS URL does not silently get the Workday page model

  Scenario: A known ATS URL resolves to its matching adapter
    Given the ATS registry
    When a Workday posting URL is resolved
    Then the Workday adapter is selected

  Scenario: Today an unknown ATS URL falls through to the Workday default
    Given the ATS registry
    When a URL for an unsupported ATS is resolved
    Then the current code returns the Workday adapter as a fallback

  @pending
  Scenario: An unsupported ATS is reported as unsupported rather than defaulted
    Given the ATS registry
    When a URL for an unsupported ATS is resolved with strict matching
    Then no adapter is returned so the operator can be flagged
