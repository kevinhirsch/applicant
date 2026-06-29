Feature: The real-adapter integration tests actually run in a CI lane
  # Issue #181 — .github/workflows/ci-integration.yml, tests/integration/*
  # The default green suite exercises only the fake/stub lane; the @pytest.mark.integration
  # tests skip on missing deps. GREEN: a dedicated integration workflow now runs
  # `pytest -m integration` against real Postgres / TeX / browser on a schedule + manual
  # dispatch and fails fast when a runtime dependency is missing. PENDING residual: nothing
  # records, per skipped test, that a real-adapter boundary went un-exercised on a given run.

  Scenario: A dedicated integration workflow exercises the real-adapter lane
    Given the continuous-integration workflow set
    When the integration lane is inspected
    Then it runs the integration-marked tests against real dependencies on a schedule

  Scenario: The integration lane fails fast when a runtime dependency is missing
    Given the integration continuous-integration workflow
    When its dependency preflight is inspected
    Then a missing renderer or browser binary aborts the lane instead of silently skipping

  @pending
  Scenario: Each skipped real-adapter boundary is recorded as an un-exercised gap
    Given the integration coverage ledger
    When the suite skips a real-adapter test for a missing dependency
    Then the un-exercised boundary is surfaced as a tracked gap rather than vanishing
