Feature: Document library has cross-surface visibility into résumé variant outcomes
  # Issue #289 — document library shows Applicant résumés but variant selection is engine-side only
# Front-door: workspace/static/js/documentLibrary.js (Applications tab fetches the
# engine's résumé/cover-letter library via /api/applicant/documents/*) + engine:
# core/entities/resume_variant.py. GREEN: the document library CAN display Applicant
# documents and the variant fit-scoring exists engine-side. PENDING: there is no
# cross-surface concept of which résumé was submitted to which job, nor a conversion-rate
# signal exposed to the document library.

  Scenario: A résumé variant carries its per-posting fit score
    Given a résumé variant scored against a job description
    When the fit coverage is computed
    Then the variant records a coverage score for that posting

  @pending
  Scenario: A résumé variant exposes which job it was submitted to
    Given a résumé variant stored for a campaign
    When the variant is inspected for its submission target
    Then it records which job posting it was submitted to

  @pending
  Scenario: A résumé variant exposes a conversion-rate signal
    Given a résumé variant with submissions and outcomes
    When the variant is inspected for its conversion rate
    Then it reports how many submissions led to interviews
