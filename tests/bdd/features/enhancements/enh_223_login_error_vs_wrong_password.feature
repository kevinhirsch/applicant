# Issue #223 — login error classification / application/services/prefill_service.py:_try_log_in
# A browser crash / network timeout / CDP disconnect during login returns False — identical
# to "wrong password" — so the engine proceeds to Google OAuth, account creation, then a
# human handoff on a possibly-DEAD browser. GREEN: a failed login returns False and the flow
# degrades to the hand-off. @pending: a transient browser error is distinguished from an
# auth failure and surfaced as a diagnostic.

Feature: A browser crash during login is distinguished from a wrong password

  Scenario: A login that fails cleanly falls back to the hand-off
    Given a browser whose login attempt reports failure
    When the engine tries to log in with a stored credential
    Then the login is reported as unsuccessful and the flow hands off

  @pending
  Scenario: A browser crash during login surfaces a diagnostic, not a silent false
    Given a browser whose login attempt crashes the session
    When the engine tries to log in with a stored credential
    Then the transient browser error is surfaced as a diagnostic distinct from auth failure
