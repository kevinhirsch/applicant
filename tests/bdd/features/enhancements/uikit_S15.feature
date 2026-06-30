# Issue #484 — FR-UIKIT-2 — workspace/static/js/applicantModelLadder.js, modelPicker.js
# Ladder tiers as drag-to-rank gadget cards; Elements endpoint form.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Connect-a-model / model ladder onto Elements + Gadget

  Scenario: S15 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S15"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S15 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S15"
    Then its post-migration kit target is satisfied
