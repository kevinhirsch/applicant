Feature: A failed conversion never breaks a submission but is lost without a log
  # Issue #240 — submission_service.py: _close_conversion_loop swallows all exceptions
# _close_conversion_loop wraps record_and_persist_conversion in a bare try/except: pass.
# If no AdvancedLearningService is wired, or the storage call fails, the conversion is
# lost with no log, no retry, no dead-letter. GREEN: a learning failure genuinely never
# breaks a recorded submission (the OutcomeEvent is still produced). PENDING: when a
# conversion happens with no learning service available it should at minimum log a
# warning instead of vanishing silently.

  Scenario: A learning failure never breaks a recorded submission
    Given a submission service whose conversion learning always raises
    When an approved application is submitted
    Then the submission is still recorded with an outcome event

  @pending
  Scenario: A conversion with no learning service available is logged
    Given a submission service wired with no conversion learning
    When an approved application is submitted
    Then a warning is logged that the conversion could not be recorded
