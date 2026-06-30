# Issue #257 — workspace/static/js/calendar/reminders.js is orphaned
# reminders.js is never imported by any module and no HTML references it. calendar.js
# imports only calendar/utils.js; the live reminder logic lives in notes.js. Cleanup
# shipped.

Feature: Calendar reminder logic lives in one place

  Scenario: No module imports the orphaned reminders module
    Given the workspace browser modules
    When every module is scanned for an import of the calendar reminders module
    Then no module imports it
    And the calendar module imports only its own utilities helper

  Scenario: The live reminder logic lives in the notes module
    Given the workspace browser modules
    Then the notes module contains the reminder scheduling logic

  Scenario: The orphaned reminders module has been removed
    Given the workspace browser modules
    Then the orphaned calendar reminders module no longer exists
