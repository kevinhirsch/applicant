# Issue #478 — FR-UIKIT-2/9 — workspace/static/js/emailLibrary.js (in-app panel only; FR-DIG-2)
# In-app digest panel adopts the kit; the email artifact is untouched.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the in-app Email / digest panel onto Notice + Gadget (the digest email stays exempt)

  Scenario: S9 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S9"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S9 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S9"
    Then its post-migration kit target is satisfied
