Feature: The credential vault supports master-key rotation and a contained decrypt-failure
  # Issue #361 — adapters/credentials/pg_credential_store.py, ports/driven/credential_store.py
  # Requirement: The vault MUST support master-key rotation (re-encrypt all stored secrets
  # under a new key with no data loss; the old key no longer decrypts, the new key does) and
  # MUST surface a distinct, contained error on a decrypt/key-loss failure rather than a
  # silent empty credential.
  #
  # A repo-wide search for rotate/reencrypt over the secret-storage code returns 0 today,
  # so every probe is @pending at the credential-store seam. The first scenario shows the
  # current state honestly: a fresh box with the WRONG key already raises a contained
  # authentication error on unseal (no silent plaintext) — but there is no rotation path.

  @pending
  Scenario: Rotating the master key re-encrypts every stored secret
    Given a vault holding sealed credentials under the current master key
    When the master key is rotated to a new key
    Then every stored secret is re-encrypted so the new key decrypts and the old key no longer does

  @pending
  Scenario: A decrypt failure surfaces a distinct contained error, never a silent empty credential
    Given a sealed credential record and a vault opened with the wrong key
    When the record is retrieved through the credential store
    Then a distinct decrypt-failure event is surfaced rather than a silently empty credential
