Feature: Applicant materials as first-class documents in the library
  # Issue #293 — deep document-library integration of Applicant materials as first-class docs
# Front-door: workspace/static/js/documentLibrary.js + engine document/variant model.
# This is a forward-looking feature: variants stored as documents with rich metadata
# (fit score, conversion rate, lineage), version history, "use THIS résumé as my new
# base", template library with merge fields, and bulk operations. GREEN: variant parent
# lineage already exists engine-side. PENDING: the document-library integration surface
# (promote-to-base, templates, bulk ops) is not built.

  Scenario: A résumé variant already tracks its parent lineage
    Given a résumé variant forked from a parent
    When the lineage chain is walked
    Then the parent appears in the variant's lineage

  @pending
  Scenario: A document-library résumé can be promoted to the new base résumé
    Given a stored résumé variant in the document library
    When the operator promotes it to the new base résumé
    Then the engine adopts it as the base it tailors from

  @pending
  Scenario: A cover-letter template with merge fields is filled per application
    Given a cover-letter template with merge fields
    When the engine fills the template for an application
    Then the merge fields are populated from the application context
