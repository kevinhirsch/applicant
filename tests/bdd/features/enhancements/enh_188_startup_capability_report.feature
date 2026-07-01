Feature: The engine reports which capabilities are real versus stubbed at startup
  # Issue #188 — app/main.py /healthz readiness, adapters that degrade to stubs
  # The engine silently degrades to stubs when binaries are missing (no TeX, no LibreOffice,
  # no fc-cache, no Chrome, no Postgres). GREEN: a readiness probe exists and reports a
  # degraded status when the database is unreachable. PENDING: there is no startup capability
  # report that names each external binary and whether the real path or the stub is in use.

  Scenario: The readiness probe reports a healthy engine over its core dependencies
    Given a freshly booted Applicant instance
    When the readiness probe is called
    Then it returns a green status with its dependency checks named

  Scenario: The readiness probe degrades rather than going green on an unreachable database
    Given a storage layer whose database cannot be reached
    When the readiness probe evaluates the database check
    Then a degraded result is reported instead of a false green

  Scenario: A startup report names each external binary and whether it is real or stubbed
    Given the engine's capability self-report
    When the report is generated at boot
    Then it lists the resume renderer, the browser, and the orchestrator as real or stub
