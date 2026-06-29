# Issue #477 — FR-UIKIT-2 — workspace/static/js/applicantMind.js
# Memories/playbooks are gadget cards; curation approvals are decisions.
# Part of the FR-UIKIT component-kit migration (epic #458). See docs/spec/ui-kit-migration.md.

Feature: Map the Mind surface (remembers / playbooks / curation) onto Gadget + Decision

  Scenario: S8 baseline — the pre-migration anchor holds today
    Given the UI-kit migration item "S8"
    Then its pre-migration baseline anchor is satisfied today

  @pending
  Scenario: S8 target — the surface is migrated onto the vendored kit
    Given the UI-kit migration item "S8"
    Then its post-migration kit target is satisfied
