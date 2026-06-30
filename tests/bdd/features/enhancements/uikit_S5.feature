# Issue #474 — FR-UIKIT-2 — workspace/static/index.html (search-criteria block)
# Bare labels/inputs migrate to associated-label Elements fields.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the criteria editor onto Elements + Gadget

  Scenario: S5 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S5"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S5 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S5"
    Then its post-migration kit target is satisfied
