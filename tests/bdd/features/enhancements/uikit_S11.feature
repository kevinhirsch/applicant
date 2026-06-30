# Issue #480 — FR-UIKIT-2 — workspace/static/js/applicantUpdate.js
# Operator controls via Elements; confirmable ops via the Decision kit.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Run controls / ops / Update surface onto Decision + Elements

  Scenario: S11 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S11"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S11 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S11"
    Then its post-migration kit target is satisfied
