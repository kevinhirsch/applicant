# Issue #213 — account-gate parity / adapters/browser/page_source.py:FakePageSource.is_account_gate
# The fake's is_account_gate() only checks has_account_create, so a sign-in page WITHOUT
# account creation is classified "not a gate" in tests while the real browser correctly
# identifies it as a gate. The prefill loop diverges fake-vs-real. GREEN: an account-create
# page IS a gate in the fake. @pending: a sign-in-only page is a gate too.

Feature: The fake account-gate check matches a sign-in-only page like the real browser

  Scenario: An account-creation page is recognised as a gate
    Given a fake page modelling an account-creation step
    When the engine checks whether the page is an account gate
    Then the page is recognised as a gate

  @pending
  Scenario: A sign-in-only page is recognised as a gate
    Given a fake page modelling a sign-in step with no account creation
    When the engine checks whether the page is an account gate
    Then the page is recognised as a gate
