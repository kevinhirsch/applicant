# Issue #486 — FR-UIKIT-2/6 — workspace/src/applicant_features.py (compare; present-but-disabled)
# Compare looks like the product while staying disabled (kit covers disabled).
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Compare surface onto Elements in its themed-but-disabled state

  Scenario: S17 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S17"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: S17 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S17"
    Then its post-migration kit target is satisfied
