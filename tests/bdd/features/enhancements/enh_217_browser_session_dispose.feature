# Issue #217 — browser session lifecycle / adapters/browser/patchright_browser.py:_sessions
# _sessions grows with every open() and is never evicted; there is no close()/dispose() on
# the adapter, so defunct sessions (CDP websockets, page refs) leak per application. GREEN:
# opening a session registers it and it is usable. @pending: a close()/dispose() evicts the
# session so the map does not grow unbounded.

Feature: Browser sessions are disposed so the adapter does not leak

  Scenario: Opening a session registers it for the application
    Given a browser adapter with one opened application session
    When the application's session is looked up
    Then the session is found

  @pending
  Scenario: Closing a session evicts it from the adapter
    Given a browser adapter with one opened application session
    When the application's session is closed
    Then the session is no longer retained by the adapter
