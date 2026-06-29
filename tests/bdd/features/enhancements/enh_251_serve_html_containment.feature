Feature: HTML serving is contained to its base directory
  # Issue #251 — workspace/app.py _serve_html_with_nonce (around lines 777-783)
  # _serve_html_with_nonce opens file_path with no containment check. The inside_base_dir helper
  # exists (src/app_helpers.py) and works (GREEN), but no HTML-serving route calls it, so a
  # future route passing user input would be traversable → @pending probe on the guarded seam.

  Scenario: The containment helper distinguishes inside from outside the base
    Given the HTML base directory containment helper
    When an escaping HTML path is checked against the base directory
    Then the escaping HTML path is reported as outside the base directory

  @pending
  Scenario: HTML serving refuses a path outside its base directory
    Given the HTML-serving helper and a path outside its base directory
    When the HTML-serving helper is asked to serve that path
    Then the HTML-serving helper refuses the out-of-base path
