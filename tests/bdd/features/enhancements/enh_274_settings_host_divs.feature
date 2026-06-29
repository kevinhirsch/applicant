Feature: Settings tab host divs live in real markup
  # Issue #274 — workspace/static/index.html
  # The notifications/fonts/sandbox/update settings tabs need their host divs present and
  # NOT buried inside an HTML comment block, so a future comment cleanup cannot delete the
  # setup UI. On this branch the host divs are real markup — GREEN regression.

  Scenario: The settings host divs are present in the page
    Given the front-door page markup
    When the settings tab host divs are looked up
    Then the notifications, fonts, sandbox and update host divs all exist

  Scenario: The settings host divs are not buried inside a comment block
    Given the front-door page markup
    When each settings host div is checked against the surrounding comments
    Then none of the host divs sit inside an HTML comment block
