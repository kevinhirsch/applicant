# Issue #472 — FR-UIKIT-2 — workspace/static/js/applicantPortal.js
# Items are gadget cards; notifications notice cards; actions decisions.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Pending-Actions Portal + notification center onto Gadget + Notice + Decision

  Scenario: S3 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S3"
    Then its pre-migration baseline anchor is satisfied today

  Scenario: S3 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S3"
    Then its post-migration kit target is satisfied
