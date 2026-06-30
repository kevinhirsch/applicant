Feature: AI-suggested attribute card is fed by engine-surfaced proposals
  # Issue #273 — AI-suggested attribute card is always hidden
# Front-door: workspace/static/index.html (#applicant-suggested-card, ships `hidden`) +
# workspace/static/js/entities.js (un-hides it when the engine surfaces suggestions) +
# engine learning: application/services/learning_advanced.py (can propose attributes).
# GREEN: the front-door wiring exists — the card is revealed when the status payload
# carries suggested attributes. PENDING: no engine HTTP surface actually exposes the
# proposed attributes for operator approval, so the card's data source is never
# populated and the surface is never shown in practice.

  Scenario: The engine can derive a proposed attribute value
    Given the advanced-learning attribute suggestion
    When an attribute value is cross-referenced from inputs
    Then a proposed attribute suggestion type exists to carry it

  Scenario: The engine surfaces proposed attributes for operator approval
    Given the engine setup/profile status surface
    When the status payload is inspected for pending attribute suggestions
    Then proposed attributes are exposed for the approval card to display
