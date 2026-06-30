# Issue #473 — FR-UIKIT-2 — workspace/static/js/documentLibrary.js
# Redline approve/decline renders through the Decision kit.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Documents / resume redline review onto Window + Elements + Decision

  Scenario: S4 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S4"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S4 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S4"
    Then its post-migration kit target is satisfied
