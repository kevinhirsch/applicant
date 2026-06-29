# Issue #204 — prefill account creation / application/services/prefill_service.py:_capture_credential
# When banking a freshly-created account credential fails, the bare `except: pass`
# silently loses the generated username/password — the account exists on the ATS but the
# vault has no record. GREEN: a successful capture banks the credential. @pending: a
# failed capture surfaces a recovery pending action / critical event instead of vanishing.

Feature: A freshly-created account credential is never silently lost

  Scenario: A successful capture banks the new account credential under the tenant
    Given a newly created account with a generated password
    When the engine banks the captured credential
    Then the credential is retrievable for future applications at that tenant

  @pending
  Scenario: A failed credential capture surfaces a recovery action rather than vanishing
    Given a credential vault that raises while banking a new account credential
    When the engine tries to bank the captured credential
    Then a recovery pending action records the lost credential for the operator
