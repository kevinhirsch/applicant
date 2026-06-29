Feature: The installer surfaces a failed source pull instead of swallowing it
  # Issue #281 — scripts/install.sh (self-bootstrap reuse-checkout path)
  # `git pull --ff-only --quiet || true` swallows every pull failure — network errors, auth
  # failures, detached HEAD, merge conflicts — so the install proceeds and builds from stale
  # or corrupt source with no warning. The pull must distinguish a real error from
  # already-up-to-date and warn or abort rather than discarding the failure unconditionally.

  @pending
  Scenario: A failed pull during bootstrap is not silently discarded
    Given the installer script
    When its checkout-reuse pull step is inspected
    Then a pull failure is detected and surfaced rather than swallowed with an unconditional true
