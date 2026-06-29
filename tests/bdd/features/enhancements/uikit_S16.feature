# Issue #485 — FR-UIKIT-2 — workspace/static/js/researchSynapse.js
# Findings/sources render as gadget cards.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Research surface onto the Gadget kit

  Scenario: S16 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S16"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S16 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S16"
    Then its post-migration kit target is satisfied
