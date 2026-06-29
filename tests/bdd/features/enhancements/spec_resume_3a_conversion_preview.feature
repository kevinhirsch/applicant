Feature: Résumé conversion preview can be accepted or rejected
  # FR-RESUME-3a — service: src/applicant/application/services/conversion_service.py
  # Requirement: At onboarding the engine MUST build a real LaTeX conversion preview and
  # let the user ACCEPT it (LaTeX becomes the primary engine) or REJECT it (fall back to
  # the docx engine), with the choice persisted per campaign.

  Scenario: Accepting the preview makes LaTeX the primary engine
    Given a conversion service with a stubbed LaTeX compile
    When a conversion preview is built and accepted
    Then the campaign's material engine is LaTeX

  Scenario: Rejecting the preview falls back to the docx engine
    Given a conversion service with a stubbed LaTeX compile
    When a conversion preview is built and rejected
    Then the campaign's material engine is docx
