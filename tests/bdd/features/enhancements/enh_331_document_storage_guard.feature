Feature: Document module guards local storage and carries no stale work markers
  # Issue #331 — workspace/static/js/document.js (lines 121-128; TODO/FIXME/HACK markers)
  # Requirement: The document module's open/minimize-state localStorage writes MUST be
  # wrapped in try/catch so a full or unavailable storage does not throw an uncaught
  # error, and the module MUST NOT carry unresolved TODO/FIXME/HACK work markers.

  # GREEN — the largest JS module no longer carries any unresolved work markers.
  Scenario: The document module carries no unresolved work markers
    Given the document browser module
    When the module is scanned for work markers
    Then it contains no TODO, FIXME or HACK marker

  Scenario: Persisting the document visible-state is guarded against storage errors
    Given the document browser module
    When the visible-state persistence is inspected
    Then the localStorage writes are wrapped in a try block
