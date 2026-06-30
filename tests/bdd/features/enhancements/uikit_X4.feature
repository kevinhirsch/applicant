# Issue #469 — FR-UIKIT-8 — workspace/static/js/settings.js + css/kit-themes.css
# Theme selection reachable in Settings, reusing mountSettingsStep.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Expose the kit house themes (theme-frosted / glass-full) in Settings via mountSettingsStep

  Scenario: X4 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "X4"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: X4 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "X4"
    Then its post-migration kit target is satisfied
