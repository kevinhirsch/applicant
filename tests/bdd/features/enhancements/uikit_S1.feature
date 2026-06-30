# Issue #470 — FR-UIKIT-2 — workspace/static/index.html, login.html, landing.html, modalManager.js, ui.js
# The shell sets the visual baseline every nested surface inherits.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the global shell (nav / sidebar / rail / modals / toasts) onto Foundation + Window + Notice

  Scenario: S1 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S1"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S1 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S1"
    Then its post-migration kit target is satisfied
