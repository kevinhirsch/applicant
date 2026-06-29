Feature: The internal-tool bypass can be disabled
  # Issue #266 — workspace/core/middleware.py:16 INTERNAL_TOOL_TOKEN
  # When APPLICANT_INTERNAL_TOKEN is unset, INTERNAL_TOOL_TOKEN auto-generates a random value,
  # so the internal-tool loopback bypass is ALWAYS active by default with no flag to turn it
  # off. A config flag to disable the path entirely does not exist yet → @pending probe.

  @pending
  Scenario: An explicit flag turns off the internal-tool bypass
    Given the workspace middleware module
    When a flag to disable the internal-tool bypass is requested
    Then a configuration flag that disables the internal-tool path exists
