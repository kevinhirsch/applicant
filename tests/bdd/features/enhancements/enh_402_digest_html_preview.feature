Feature: The digest email can be previewed as it will be sent
  # Issue #402 — proxy applicant_email_routes.py:201 + client digest_email / JS consumer
  # Requirement: The front-door SHOULD offer a "preview the email as sent" view backed by
  # the existing rendered-HTML digest-email endpoint.

  Scenario: The engine client and proxy for the digest-email HTML already exist
    Given the front-door engine client and email proxy module
    When the digest-email HTML seam is inspected
    Then the engine client exposes a digest-email method
    And the email proxy module routes a digest-email path

  @pending
  Scenario: A front-door view renders the digest email preview
    Given the digest surface in the front-door
    When the email-preview view is wired
    Then a JS consumer renders the rendered digest-email HTML
