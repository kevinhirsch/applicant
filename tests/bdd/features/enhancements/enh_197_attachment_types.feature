Feature: Application attachments beyond résumé and cover letter
  # Issue #197 — no portfolio/attachment management beyond résumé and cover letter
# Engine: core/entities/generated_document.py (DocumentType). Today only RESUME,
# COVER_LETTER, and SCREENING_ANSWER exist; there is no support for portfolios,
# reference lists, transcripts, writing samples, certifications, or project documents.
# PENDING: extend the document model + library to carry arbitrary per-campaign
# attachments.

  Scenario: The document model already carries the three core material kinds
    Given the generated-document type catalogue
    When the supported document kinds are listed
    Then résumé, cover letter, and screening answer are all present

  Scenario: A portfolio attachment is a first-class material kind
    Given the generated-document type catalogue
    When a portfolio attachment kind is requested
    Then the document model recognizes it as a managed attachment type

  Scenario: Arbitrary application attachments can be attached to a campaign
    Given a campaign that allows reference lists and transcripts
    When such an attachment is stored against the campaign
    Then the attachment is retrievable as a managed campaign document
