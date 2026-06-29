Feature: manage_tokens does not return the raw API token string to the model
  # Issue #315 — workspace/src/tool_implementations.py:1335 (do_manage_tokens create)
  # Requirement: When the model creates an API token, the tool MUST NOT place the raw
  # token string in the model-visible result; the secret is delivered to the browser
  # over a separate secure channel and only a masked prefix is shown to the model.

  @pending
  Scenario: A created token is masked in the model-visible response
    Given the manage_tokens tool result for a freshly created token
    When the result is inspected for what reaches the model context
    Then the raw token string is masked rather than returned verbatim
