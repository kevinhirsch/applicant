Feature: The live ATS dry-run fails on a browser fault instead of silently passing
  # Issue #275 — tests/integration/test_ats_prefill_dryrun.py
  # An in-body pytest.xfail() turns a real failure (browser detects 0 fillable fields)
  # into an expected XFAIL at runtime, so CI stays green when the form changes, the
  # browser fails, or the page is behind an auth gate. The zero-field branch must become a
  # real failure (or a declarative, condition-scoped expected-fail), not a runtime xfail.

  @pending
  Scenario: A zero-field detection result is a real failure, not a runtime xfail
    Given the live ATS dry-run test source
    When the zero-fields-detected branch is inspected
    Then it does not call pytest.xfail inside the test body to mask the failure
