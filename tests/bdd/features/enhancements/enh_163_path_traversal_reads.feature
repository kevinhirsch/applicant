Feature: File reads are contained to an allowed base directory
  # Issue #163 — workspace file-read call sites (personal_docs.py, document_processor.py, …)
  # A containment helper (inside_base_dir) already exists in src/app_helpers.py and correctly
  # rejects traversal — GREEN coverage of that core rule. The residual gap is that there is no
  # SHARED safe-join helper the flagged call sites can reuse, so the centralised seam is
  # @pending until it is added.

  Scenario: The containment helper rejects a traversal path
    Given the workspace path-containment helper
    When a path that escapes the base directory is checked
    Then the path is reported as outside the base directory
    And a path inside the base directory is reported as contained

  @pending
  Scenario: A shared safe-join helper centralises path containment
    Given the workspace path utilities module
    When a shared safe-join helper is requested
    Then a containment-enforcing safe-join helper is available for reuse
