# Issue #461 — FR-UIKIT-1/3/5 — workspace/static/js/appkitWindow.js (reconcile modalManager.js/modalSnap.js/windowDrag.js)
# One window mechanism, not two; modal a11y preserved.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the Window kit (.ow-window) and reconcile it with windowDrag/modalManager

  Scenario: F3 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F3"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: F3 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F3"
    Then its post-migration kit target is satisfied
