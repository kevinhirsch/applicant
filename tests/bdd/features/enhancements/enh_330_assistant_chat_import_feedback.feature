Feature: Assistant surfaces a broken applicant-chat module load
  # Issue #330 — workspace/static/js/assistant.js (line 466; presets at 281, 282)
  # Requirement: When the assistant lazily imports ./applicantChat.js and that import
  # fails, the front-door MUST show the user an error (e.g. "Applicant chat unavailable —
  # please reload") rather than silently swallowing the failure in an empty
  # .catch(() => {}) that leaves the section blank with no feedback.

  # GREEN — the presets fetch degrades to a safe default so the panel still renders.
  Scenario: A failed presets fetch degrades to an empty default
    Given the assistant browser module
    When the presets fetch fallback is inspected
    Then the fetch failure falls back to an empty value rather than throwing

  @pending
  Scenario: A failed applicant-chat import shows the user an error
    Given the assistant browser module
    When the applicant-chat dynamic import is inspected
    Then its failure handler shows an error instead of being empty
