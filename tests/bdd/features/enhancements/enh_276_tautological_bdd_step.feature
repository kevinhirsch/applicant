Feature: The zero-command-line acceptance step asserts something concrete
  # Issue #276 — tests/bdd/steps/test_p0_steps.py (~line 121)
  # The "no command line was required" step literally asserts True, so it passes even if it
  # is never reached (regex mismatch, binding failure). The fix replaces the tautology with
  # a concrete check that setup actually happened over the HTTP surface. The @pending→xfail
  # convention is already handled in conftest; this scenario specs the FIX = the no-op gone.

  Scenario: The zero-command-line step contains no tautological assertion
    Given the P0 acceptance step source
    When the zero-command-line step body is inspected
    Then it verifies setup happened over HTTP rather than asserting a bare truth
