# Issue #486 — FR-UIKIT-2/6 — workspace/static/js/applicantCompare.js (compare; engine-backed, #297)
# Compare is engine-backed and reachable; its controls compose on the Elements kit.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the now-active Compare surface onto Elements

  Scenario: S17 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S17"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: S17 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S17"
    Then its post-migration kit target is satisfied
