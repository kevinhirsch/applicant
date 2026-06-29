Feature: The front-door has a JS unit-test harness wired into CI
  # Issue #366 — workspace/package.json (no test runner), CLAUDE.md (node --check only)
  # Requirement: The front-door MUST have a JS unit-test harness (a configured test runner
  # with ≥1 real behavioral test that fails on a regression) and CI MUST invoke that JS test
  # suite alongside the existing `node --check`.
  #
  # workspace/package.json declares no jest/vitest/mocha and no `test` script today, and CI
  # validates JS with `node --check` only (syntax, not behavior). Both scenarios are @pending
  # until the harness and the CI step land.

  @pending
  Scenario: A JS test runner is configured with a real behavioral test
    Given the front-door package manifest
    When the JS test tooling is inspected
    Then a test runner and a runnable test script with at least one behavioral test are configured

  @pending
  Scenario: CI invokes the JS test suite alongside node --check
    Given the continuous-integration workflow
    When its steps are inspected
    Then it invokes the front-door JS test suite in addition to node --check
