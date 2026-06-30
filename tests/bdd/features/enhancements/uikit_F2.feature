# Issue #460 — FR-UIKIT-1 — workspace/static/js/appkitElements.js
# One atomic-control vocabulary to replace bespoke .cal-btn sizing.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the atomic Elements kit (.ow-btn/field/check/radio/switch/select/slider)

  Scenario: F2 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F2"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: F2 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F2"
    Then its post-migration kit target is satisfied
