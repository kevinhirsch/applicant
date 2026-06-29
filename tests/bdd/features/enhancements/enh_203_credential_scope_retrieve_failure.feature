# Issue #203 — prefill credential lookup / application/services/prefill_service.py:_lookup_credential
# Per-scope vault.retrieve() exceptions are swallowed and the engine skips to the next
# scope; if a transient error affects ALL scopes, login is skipped silently and the user
# is dumped into a manual handoff with no diagnostic. GREEN: a single bad scope still lets
# a good scope win. @pending: an all-scopes failure surfaces a diagnostic event.

Feature: A failing credential vault is surfaced rather than silently skipped

  Scenario: A failing scope does not stop a later working scope from resolving
    Given a credential vault that fails the first scope but holds a shared credential
    When the engine looks up a shared credential across scopes
    Then the working scope's credential is still returned

  @pending
  Scenario: An all-scopes vault failure raises a diagnostic instead of looking empty
    Given a credential vault that raises for every scope
    When the engine looks up a stored credential across scopes
    Then a diagnostic event records that every credential scope failed
