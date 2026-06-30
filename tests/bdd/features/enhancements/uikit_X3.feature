# Issue #468 — FR-UIKIT-7 — .github/workflows/ci.yml node --check + workspace/static/js/appkit*.js
# Plain ES modules, no build step, additive CSS within the #398 budget.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendored kit modules pass node --check with no bundler and respect the style.css budget

  Scenario: X3 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "X3"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: X3 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "X3"
    Then its post-migration kit target is satisfied
