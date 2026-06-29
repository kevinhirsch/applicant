Feature: Truthfulness fail-closed — no unverified material is ever emitted
  # NFR-TRUTH-1 (MUST): No fabricated content in any generated application material.
  # Requirement: MaterialService MUST fail closed around the fabrication post-check —
  # if generation or parsing raises before the check, OR if the generated text contains
  # an unsupported (fabricated) claim, the service persists NOTHING and surfaces a clear
  # failure. The fabrication post-check is enforced at the persistence boundary, so no
  # unverified résumé / cover-letter / screening-answer text can ever reach storage.
  # Engine: application/services/material_service.py (_store_document / generate_* /
  # select_or_generate) + core/rules/truthfulness.py (assert_no_fabrication).

  Scenario: A cover-letter generation whose model raises persists no material
    Given a material service whose model raises on every generation
    And a true candidate source and a target application
    When a cover letter is generated for that application
    Then no generated document is persisted from the raising model
    And the persisted output never contains an unverified fabrication

  Scenario: A cover-letter generation returning a fabricated claim persists nothing
    Given a material service whose model returns a fabricated credential
    And a true candidate source and a target application
    When a cover letter is generated and the fabrication guard runs
    Then the truthfulness guard rejects the material with a clear failure
    And no generated document is persisted for that application

  Scenario: An essay screening answer returning a fabricated claim persists nothing
    Given a material service whose model returns a fabricated credential
    And a true candidate source and a target application
    When an essay screening answer is generated and the fabrication guard runs
    Then the truthfulness guard rejects the material with a clear failure
    And no generated document is persisted for that application

  Scenario: The persistence boundary refuses unverified material with no ground truth
    Given a material service over the true candidate source
    When generated material is persisted without a truthfulness ground truth
    Then the persistence boundary refuses it with a clear failure
    And no generated document is persisted for that application
