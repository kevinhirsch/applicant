# Issue #224 — PageSource contract parity / adapters/browser/page_source.py:PageSource Protocol
# The PageSource Protocol does not declare submit_account, yet PlaywrightPageSource and the
# fake both implement it and the prefill service calls it via getattr. GREEN: the fake and
# real source both expose submit_account (the implementation divergence is closed). @pending:
# the Protocol itself declares submit_account so the contract is enforced.

Feature: submit_account is part of the PageSource contract across implementations

  Scenario: The fake page source exposes a submit_account method
    Given the in-memory page source
    When its account-submit capability is inspected
    Then a submit_account method is present

  Scenario: The PageSource protocol declares submit_account
    Given the page-source port contract
    When the contract's declared members are inspected
    Then submit_account is one of the declared members
