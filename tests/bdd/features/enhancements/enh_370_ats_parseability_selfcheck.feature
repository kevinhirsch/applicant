Feature: The generated résumé is round-tripped through an ATS-style parser before sending
  # Issue #370 — input parser ships (adapters/resume_parser/resume_parser.py);
  # the OUTPUT parseability self-check is new. Extends the résumé-render path (#178).
  # Requirement: After rendering, the engine MUST run an ATS-parseability self-check on
  # the generated résumé — extract text and confirm the contact block, section headers,
  # and key skills are recoverable — and MUST flag a failing render for review /
  # regeneration rather than submit it. GREEN: an ATS-style parser already recovers
  # contact + skills from a clean document. PENDING: no output-side self-check exists.

  Scenario: The input résumé parser recovers contact details and skills from a clean document
    Given a clean single-column résumé text
    When the résumé parser extracts it
    Then the contact email and the listed skills are recoverable

  Scenario: A clean single-column render passes the output parseability self-check
    Given a freshly rendered single-column résumé
    When the ATS-parseability self-check runs on the render
    Then the self-check reports it as machine-readable

  Scenario: An unparseable render is flagged rather than sent
    Given a rendered résumé whose text is not recoverable (e.g. text-as-image)
    When the ATS-parseability self-check runs on the render
    Then the self-check flags it for review or regeneration and it is not submitted
