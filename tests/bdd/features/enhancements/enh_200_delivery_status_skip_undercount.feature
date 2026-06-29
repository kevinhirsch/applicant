Feature: Delivery-status integration-skip count is accurate
  # Issue #200 — docs/delivery-status.md vs tests/integration/
  # The doc claims 14 integration-gated skips; a real count of skip markers in the
  # integration suite is higher. The undercounting doc is the gap (@pending).

  @pending
  Scenario: The documented skip count matches the real integration suite
    Given the integration test suite skip markers
    When the documented integration-gated skip count is compared to the real count
    Then the documented count is not below the real number of default skips
