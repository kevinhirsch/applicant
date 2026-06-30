Feature: Note mutations report failures instead of pretending to succeed
  # Issue #328 — workspace/static/js/notes.js (~16 .catch(() => {}) on note mutations)
  # Requirement: When a note archive/unarchive/delete/edit API call fails, the front-door
  # MUST surface an error to the user (toast/error banner) rather than swallowing the
  # rejection in an empty .catch(() => {}) that leaves the UI showing success.

  # GREEN — the single-card archive/unarchive/delete handlers already roll back and warn.
  Scenario: A failed single-card delete shows an error and restores the note
    Given the notes browser module
    When the single-card delete handler is inspected
    Then a failed delete shows an error message to the user

  Scenario: No note mutation discards its failure silently
    Given the notes browser module
    When the note mutation calls are scanned
    Then no note patch or delete call ends in an empty catch handler
