Feature: Form controls carry associated labels for screen readers
  # Issue #247 — workspace/static/index.html
  # The front-door page has many form controls but very few explicit label-for
  # associations; most rely on placeholder/title text that screen readers do not surface
  # reliably. The placeholder-as-label barrier is the gap (@pending).

  Scenario: The front-door page renders many form controls
    Given the front-door page markup
    When the form controls are counted
    Then the page contains many input, select and textarea controls

  @pending
  Scenario: Most form controls have an associated label
    Given the front-door page markup
    When the explicitly associated labels are counted against the controls
    Then most controls carry a label rather than relying on placeholder text
