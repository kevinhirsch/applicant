# Issue #295 — Tasks integration — pending actions as first-class workspace tasks
# Applicant pending actions exist as engine entities and surface in the Portal (the in-app
# notification/action center) — that part ships. The feature wants each pending action
# mirrored into the workspace TASKS surface (priority, due date, deep link) with task
# completion advancing the engine pipeline. There is no Applicant<->Tasks bridge today, so
# the integration probes are @pending.

Feature: Pending actions as a first-class task system

  Scenario: There is no Applicant task-bridge route file yet
    Given the front-door route directory
    When the Applicant route files are listed
    Then there is no Applicant tasks route file

  @pending
  Scenario: Every pending action is mirrored as a workspace task
    Given the engine has an open pending action
    When the task bridge runs
    Then a corresponding workspace task is created with priority and a deep link

  @pending
  Scenario: Completing a review task advances the engine pipeline
    Given a material-review task linked to an application
    When the task is marked approved
    Then the engine advances the application to final approval
