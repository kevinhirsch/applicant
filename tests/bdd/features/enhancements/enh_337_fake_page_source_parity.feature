# Issue #337 — FakePageSource != PlaywrightPageSource / adapters/browser/page_source.py
#   FakePageSource.enter_application (no-op None), log_in (always True), is_account_gate
#   (create-only), offers_google_signin (always False).
# Requirement: The in-memory FakePageSource MUST approximate PlaywrightPageSource's
#   decision branches closely enough that the pre-fill loop's apply-click, login-failure,
#   sign-in-only gate, and Google-OAuth paths are all exercised in the hermetic lane.
# Related existing issues: #213 (sign-in-only gate not detected by the fake),
#   #224 (PageSource Protocol missing submit_account — fake/real contract divergence).
# GREEN: the divergences exist today and are observable on the fake (regression guard).
# PENDING: the fake reaches parity so the real decision branches become testable.

Feature: The fake page source approximates the real driver's decision branches

  Scenario: The fake's apply-entry is a no-op while the real driver clicks Apply
    Given the in-memory fake page source on an application flow
    When the engine enters the application
    Then the fake takes no apply action today

  Scenario: The fake's login always succeeds while the real driver can fail
    Given the in-memory fake page source on an application flow
    When the engine logs in with any credential on the fake
    Then the fake always reports success today

  @pending
  Scenario: The fake exercises the apply-button click path
    Given a fake page source modelling a posting that needs an Apply click
    When the engine enters the application
    Then the fake reports it clicked into the application flow

  @pending
  Scenario: The fake can model a login failure
    Given a fake page source modelling an account gate with a wrong password
    When the engine logs in with the wrong credential on the fake
    Then the fake reports the login failed

  @pending
  Scenario: The fake detects a sign-in-only page as an account gate
    Given a fake page source modelling a sign-in-only step with no account creation
    When the engine checks whether the fake page is an account gate
    Then the sign-in-only page is recognised as a gate

  @pending
  Scenario: The fake can model an offered Google sign-in
    Given a fake page source modelling a gate offering Google sign-in
    When the engine checks whether the fake offers Google sign-in
    Then the fake reports a Google sign-in option is offered
