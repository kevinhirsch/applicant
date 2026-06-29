# Issue #463 — FR-UIKIT-1 — workspace/static/js/appkitGadget.js + appkitGadgetRail.js
# One focusable widget-card primitive for the card-collection surfaces.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the Gadget kit (.og-card + gadget rail)

  Scenario: F5 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F5"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: F5 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F5"
    Then its post-migration kit target is satisfied
