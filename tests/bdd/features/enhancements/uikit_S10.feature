# Issue #479 — FR-UIKIT-2 — workspace/static/js/applicantActivity.js, applicantDebug.js
# Observability panels are gadget cards; the viewer is a kit window.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Activity + Debug surface onto Gadget + Window

  Scenario: S10 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S10"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S10 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S10"
    Then its post-migration kit target is satisfied
