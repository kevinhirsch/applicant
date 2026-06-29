Feature: A "deliver digest now" control sends the digest on demand
  # Issue #401 — proxy applicant_email_routes.py:210 + client deliver_digest / JS consumer
  # Requirement: The front-door MUST expose a "deliver/refresh digest now" control that
  # calls the existing proxy and reflects the result.

  Scenario: The engine client and proxy for deliver-now already exist
    Given the front-door engine client and email proxy module
    When the deliver-digest seam is inspected
    Then the engine client exposes a deliver-digest method
    And the email proxy module routes a deliver path

  @pending
  Scenario: A front-door control invokes deliver-now
    Given the digest surface in the front-door
    When the deliver-now control is wired
    Then a JS consumer calls the deliver-digest proxy path
