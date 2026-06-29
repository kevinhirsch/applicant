Feature: CI is not blocked indefinitely when the self-hosted runner is offline
  # Issue #278 — .github/workflows/ci.yml (runs-on)
  # CI pins runs-on: self-hosted with the ubuntu-latest fallback commented out. If the
  # self-hosted runner goes offline, every PR queues with no automatic failover. The fix
  # provides an active hosted fallback (a runner group, a matrix, or labels that resolve to a
  # hosted runner when the self-hosted one is down) rather than a manual comment swap.

  @pending
  Scenario: The CI job has an active hosted fallback runner
    Given the continuous-integration workflow
    When its runner selection is inspected
    Then a hosted fallback is wired in rather than left commented out
