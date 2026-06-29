Feature: The alembic.ini DB URL is an obviously-invalid placeholder, not real-looking creds
  # Issue #349 — alembic.ini:9 (sqlalchemy.url placeholder)
  # Requirement: The static alembic.ini sqlalchemy.url MUST be an obviously-fake
  # placeholder (e.g. "placeholder") so it cannot be mistaken for a real credential
  # and cannot silently connect anywhere; the live URL is injected from Settings.

  @pending
  Scenario: The static placeholder URL uses an obviously-invalid value
    Given the static alembic configuration file
    When the placeholder sqlalchemy.url is read
    Then it is an obviously-fake placeholder rather than realistic credentials
