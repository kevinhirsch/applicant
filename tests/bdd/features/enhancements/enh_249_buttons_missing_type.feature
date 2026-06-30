Feature: Non-submit buttons declare type=button
  # Issue #249 — workspace/static/index.html
  # Many buttons omit an explicit type, defaulting to submit, so a button inside a form
  # can accidentally submit it. The large set of type-less buttons is the gap (@pending).

  Scenario: The front-door page declares many buttons
    Given the front-door page markup
    When the buttons are counted
    Then the page contains many button elements

  Scenario: Every button declares an explicit type
    Given the front-door page markup
    When the buttons without an explicit type are counted
    Then no button is left to default to a submit type
