Feature: webhook_token is stored encrypted/hashed, consistent with other credentials
  # Issue #356 — workspace/core/database.py:522 (webhook_token plain String) + src/secret_storage.py
  # Requirement: The webhook_token column MUST NOT persist a plaintext token — it is
  # stored encrypted (Fernet via secret_storage) or hashed, matching the other secret
  # columns, so a leaked DB file does not expose the live webhook tokens.

  Scenario: The secret-storage layer round-trips a secret without storing plaintext
    Given the workspace secret-storage encryption layer
    When a webhook token value is encrypted then decrypted
    Then the stored form is not the plaintext and it decrypts back to the original

  Scenario: The webhook_token column does not store plaintext
    Given the scheduled-task model column for the webhook token
    When the column type is inspected
    Then it is an encrypted (or hashed) column rather than a plain String
