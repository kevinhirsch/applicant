# Issue #465 — FR-UIKIT-1 — workspace/static/js/appkitChatHint.js
# One consistent above-composer guidance affordance.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Vendor the Chat Hint kit (above-composer guide tip)

  Scenario: F7 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "F7"
    Then its pre-migration baseline anchor is satisfied today


  Scenario: F7 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "F7"
    Then its post-migration kit target is satisfied
