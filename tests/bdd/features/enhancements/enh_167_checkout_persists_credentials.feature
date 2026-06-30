Feature: CI checkout steps do not persist Git credentials on the runner
  # Issue #167 — .github/workflows/ci.yml, ci-integration.yml, workspace/.github/workflows/ci.yml
  # The main engine CI checkout now sets persist-credentials: false (GREEN). The integration
  # lane and the vendored front-door workflow checkouts do NOT yet, leaving job credentials in
  # the runner's git config → @pending probes on those two workflows.

  Scenario: The engine CI checkout disables credential persistence
    Given the engine CI workflow checkout step
    When the checkout options are inspected
    Then credential persistence is disabled on that checkout

  Scenario: The integration CI checkout disables credential persistence
    Given the integration CI workflow checkout step
    When the checkout options are inspected
    Then credential persistence is disabled on the integration checkout

  Scenario: The front-door CI checkout disables credential persistence
    Given the front-door CI workflow checkout step
    When the checkout options are inspected
    Then credential persistence is disabled on the front-door checkout
