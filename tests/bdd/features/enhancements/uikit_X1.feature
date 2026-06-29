# Issue #466 — FR-UIKIT-4 — .github/workflows/ci.yml denylist + workspace/static/js/appkit*.js
# Shipped artifacts carry no upstream codename; appkit* modules present.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: White-label the vendored kit — rename upstream codenamed modules to appkit*, keep the CI denylist green

  Scenario: X1 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "X1"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: X1 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "X1"
    Then its post-migration kit target is satisfied
