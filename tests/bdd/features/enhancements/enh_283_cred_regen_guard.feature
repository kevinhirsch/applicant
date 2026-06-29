Feature: The installer will not regenerate credentials against an initialized database
  # Issue #283 — scripts/install.sh (credential generation / .env persistence)
  # Credential generation is guarded only by the absence of .env. If an operator deletes
  # .env and re-runs install, a new random Postgres password is minted while the data volume
  # still carries the OLD password, so the app fails to authenticate. The installer must
  # detect an already-initialized Postgres volume and refuse to regenerate credentials.
  # The guard now inspects `docker volume ls` for the project's pgdata volume and refuses to
  # mint new credentials when it exists (explicit APPLICANT_FORCE_CRED_REGEN opt-in) → hard gate.

  Scenario: An existing database volume blocks credential regeneration
    Given the installer script
    When its credential generation guard is inspected
    Then it refuses to mint new credentials when the Postgres data volume already exists
