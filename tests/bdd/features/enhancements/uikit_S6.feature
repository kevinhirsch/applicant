# Issue #475 — FR-UIKIT-2 — workspace/static/index.html (attribute block)
# Attribute fields/switches adopt Elements; groups become gadget cards.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the attribute-cloud editor onto Elements + Gadget

  Scenario: S6 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S6"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S6 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S6"
    Then its post-migration kit target is satisfied
