# Issue #459 — FR-UIKIT-1/4 — workspace/static/style.css + js/appkitGlass.js + css/kit-themes.css
# The glass/token/theme/slots foundation the other kits render against.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the kit Foundation (glass + tokens + house themes + slots) into the front door

  Scenario: F1 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F1"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: F1 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F1"
    Then its post-migration kit target is satisfied
