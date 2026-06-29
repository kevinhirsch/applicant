# Issue #316 — src/applicant/app/lifespan.py:137-151 (app lifespan shutdown path)
# Requirement: On shutdown the engine MUST drain/stop the scheduler loop AND flush
# durable workflow checkpoints and close every leasable resource (sandbox sessions,
# browser, credential vault) — not only cancel the task and dispose the DB engine.
Feature: Graceful shutdown drains work and releases resources

  # GREEN — what ships today: the scheduler loop is stopped and the DB engine disposed.
  Scenario: The shutdown path stops the scheduler loop and disposes the database engine
    Given the application lifespan source
    When the shutdown branch is inspected
    Then it cancels the scheduler task and disposes the database engine

  # PENDING — the residual gap: in-flight work is abandoned and resources leak.
  @pending
  Scenario: Shutdown flushes pending workflow checkpoints before exiting
    Given the application lifespan source
    When a graceful shutdown is requested with workflows mid-flight
    Then it flushes the pending workflow checkpoints so no in-progress step is abandoned

  @pending
  Scenario: Shutdown cleans up leaked sandbox sessions and adapters
    Given the application lifespan source
    When a graceful shutdown is requested with active sandbox sessions
    Then it closes the sandbox sessions, the browser, and the credential vault
