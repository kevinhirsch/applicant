Feature: Chat stream JSON parsing tolerates malformed chunks
  # Issue #327 — workspace/static/js/chat.js (lines 1332, 4263)
  # Requirement: The front-door chat MUST wrap every JSON.parse of an SSE stream chunk
  # in a try/catch so a single malformed chunk is skipped rather than crashing the
  # streaming handler, and stream-related fetch failures MUST NOT be silently discarded
  # by empty .catch(() => {}) blocks.

  # GREEN — the two cited bare JSON.parse calls on stream chunk data are now guarded.
  Scenario: The SSE chunk parse is wrapped in a try block
    Given the chat browser module
    When the stream chunk JSON parsing is inspected
    Then every parse of a stream chunk sits inside a try block

  # GREEN — stream errors are surfaced rather than swallowed at the parse seam.
  Scenario: A failed stream chunk parse logs the error and continues
    Given the chat browser module
    When the chunk parse failure handling is inspected
    Then the parse failure is logged instead of crashing the handler

  @pending
  Scenario: No fetch in the chat module silently discards its error
    Given the chat browser module
    When the module is scanned for empty catch handlers
    Then no empty arrow catch or empty bare catch block remains
