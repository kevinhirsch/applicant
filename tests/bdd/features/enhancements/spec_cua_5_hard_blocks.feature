Feature: Dangerous desktop key-combos and type-patterns are hard-blocked
  # FR-CUA-5 — core rule: src/applicant/core/rules/computer_use.py
  # Requirement: The engine MUST refuse a dangerous desktop key-combo or type-pattern
  # (lock/log-out/force-delete chords; curl|bash, rm -rf /, fork-bomb commands) in the
  # pure core regardless of approval state, while allowing safe combos/text.

  Scenario: A lock-screen key chord is refused
    Given the computer-use hard-block core rule
    When a lock-screen key combination is checked
    Then the dangerous key combination is refused
    And a benign key combination is allowed

  Scenario: A remote-exec type pattern is refused
    Given the computer-use hard-block core rule
    When a curl-pipe-to-shell command is checked as type text
    Then the dangerous type text is refused
    And ordinary type text is allowed
