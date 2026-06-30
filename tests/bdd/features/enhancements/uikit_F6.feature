# Issue #464 — FR-UIKIT-1 — workspace/static/js/appkitDecision.js
# Standardize approve/decline/confirm incl. the destructive variant.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the Decision kit (.odec-* prompt -> options -> confirm, risk variant)

  Scenario: F6 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F6"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: F6 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F6"
    Then its post-migration kit target is satisfied
