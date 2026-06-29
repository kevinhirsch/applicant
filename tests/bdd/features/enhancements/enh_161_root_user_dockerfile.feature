Feature: Application container images declare a non-root runtime user
  # Issue #161 — workspace/Dockerfile, docker/Dockerfile, docker/updater.Dockerfile
  # The application images do not declare a USER directive, so the main process runs as
  # root, widening the blast radius of a compromise. A dedicated USER line before the
  # entrypoint is not present yet → @pending probes per image.

  @pending
  Scenario: The engine image drops to an unprivileged user
    Given the engine application Dockerfile
    When its runtime user is inspected
    Then a non-root USER directive is declared before the runtime entrypoint

  @pending
  Scenario: The front-door image drops to an unprivileged user
    Given the front-door application Dockerfile
    When its runtime user is inspected
    Then a non-root USER directive is declared before the runtime entrypoint
