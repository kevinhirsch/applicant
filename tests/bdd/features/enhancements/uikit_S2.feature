# Issue #471 — FR-UIKIT-2 — workspace/static/js/applicantOnboarding.js
# The blocking wizard renders as a kit modal; focus-trap preserved.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the OOBE onboarding wizard onto Window (modal) + Elements + Slots + Decision

  Scenario: S2 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S2"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S2 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S2"
    Then its post-migration kit target is satisfied
