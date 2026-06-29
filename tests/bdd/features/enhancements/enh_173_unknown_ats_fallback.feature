# Issue #173 — Unknown ATS must not silently get the Workday page model
# (adapters/browser/ats.py resolve_ats) — FR-PREFILL-2.
# 1.0 commits to UNIVERSAL generic-driver coverage: a recognized vendor URL resolves
# to its dedicated adapter; an UNKNOWN ATS URL resolves to the vendor-agnostic GENERIC
# live-DOM driver (never the Workday fixed-page model). A strict resolver returns no
# adapter at all so the operator can still detect an unrecognized ATS.

Feature: An unknown ATS URL drives the generic live-DOM driver, not the Workday model

  Scenario: A known ATS URL resolves to its matching adapter
    Given the ATS registry
    When a Workday posting URL is resolved
    Then the Workday adapter is selected

  Scenario: An unknown ATS URL resolves to the generic live-DOM driver
    Given the ATS registry
    When a URL for an unsupported ATS is resolved
    Then the generic driver is selected and it does not impose the Workday page model

  Scenario: The strict resolver reports an unsupported ATS rather than defaulting
    Given the ATS registry
    When a URL for an unsupported ATS is resolved with strict matching
    Then no adapter is returned so the operator can be flagged
