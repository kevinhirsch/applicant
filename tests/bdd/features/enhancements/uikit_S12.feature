# Issue #481 — FR-UIKIT-2 — workspace/static/js/applicantRemote.js
# Responsive kit window (no 480px cap) + Decision risk-variant authorize.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Live remote view / takeover onto Window + Decision

  Scenario: S12 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S12"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S12 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S12"
    Then its post-migration kit target is satisfied
