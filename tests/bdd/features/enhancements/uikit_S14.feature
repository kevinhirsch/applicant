# Issue #483 — FR-UIKIT-2 — workspace/static/js/settings.js
# Settings controls adopt Elements; step panels adopt kit chrome.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Settings surface onto Elements + Window (reusing mountSettingsStep)

  Scenario: S14 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S14"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S14 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S14"
    Then its post-migration kit target is satisfied
