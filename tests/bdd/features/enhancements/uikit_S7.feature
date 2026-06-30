# Issue #476 — FR-UIKIT-2 — workspace/static/js/applicantChat.js
# Above-composer guidance via the Chat Hint kit; Elements controls.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Chat / assistant surface onto Chat Hint + Elements

  Scenario: S7 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S7"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S7 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S7"
    Then its post-migration kit target is satisfied
