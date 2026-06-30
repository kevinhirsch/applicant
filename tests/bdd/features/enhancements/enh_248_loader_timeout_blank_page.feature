Feature: Loading overlay removal tied to app initialization
  # Issue #248 — workspace/static/index.html
  # The loader is removed by a fixed five-second timer regardless of whether the SPA
  # initialized, so a failed module load leaves a blank page with no error. The
  # timer-driven removal is the gap (@pending).

  Scenario: The page ships a loading overlay element
    Given the front-door page markup
    When the loading overlay is looked for
    Then a loading overlay element is present

  Scenario: The loader is removed on initialization, not by a fixed timer
    Given the front-door page markup
    When the loader-removal logic is inspected
    Then the loader is not torn down by a fixed five-second timeout alone
