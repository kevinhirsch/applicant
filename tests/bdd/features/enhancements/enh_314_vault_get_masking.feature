Feature: vault_get never returns plaintext passwords or TOTP secrets to the model
  # Issue #314 — workspace/src/tool_implementations.py:3974-4029 (do_vault_get)
  # Requirement: The vault_get tool MUST mask passwords and TOTP secrets from the
  # text returned to the model context (the browser/autofill path receives them out
  # of band), so a fabricated reason cannot exfiltrate the secret into chat.

  Scenario: A retrieval reason is required before any vault entry is read
    Given the vault_get tool with no reason supplied
    When the vault entry is requested
    Then the request is refused for a missing reason

  @pending
  Scenario: The password and TOTP secret are masked in the model-visible output
    Given a vault login entry with a password and a TOTP secret
    When the vault entry is rendered for the model context
    Then the plaintext password and TOTP secret are masked, not echoed verbatim
