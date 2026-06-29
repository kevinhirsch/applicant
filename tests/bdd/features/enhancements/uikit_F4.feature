# Issue #462 — FR-UIKIT-1/3 — workspace/static/js/appkitNotice.js (re-back ui.js showToast)
# One notification mechanism; showToast keeps its signature.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the Notice kit (.on-card) and re-back ui.js showToast through it

  Scenario: F4 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F4"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: F4 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F4"
    Then its post-migration kit target is satisfied
