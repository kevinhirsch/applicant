# Issue #467 — FR-UIKIT-5 — workspace/static/js/appkitWindow.js (focus trap / Escape / dialog ARIA)
# Re-skinning must not drop focus-trap/Escape/ARIA/reduced-motion.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Kit components preserve the a11y affordances won in #379-#394

  Scenario: X2 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "X2"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: X2 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "X2"
    Then its post-migration kit target is satisfied
