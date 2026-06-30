Feature: The workspace compile check runs under the project interpreter
  # Issue #277 — .github/workflows/ci.yml (workspace compileall step)
  # The compileall syntax check uses bare `python`, not `uv run python`, so it runs against
  # the system interpreter without the workspace dependencies. compileall skips modules whose
  # imports fail, so third-party import syntax errors slip through. The step should invoke
  # `uv run python -m compileall ...` so it runs inside the synced project environment.

  Scenario: The compileall step runs inside the project environment
    Given the continuous-integration workflow
    When the workspace compileall step is inspected
    Then it invokes compileall through the project interpreter rather than bare python
