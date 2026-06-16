Feature: Resume uploads right and looks right
  # master spec §10 (FR-RESUME-3/4/6/7, FR-FONT-2)

  Scenario: A role warranting it gets a selected or generated variant that passes the fidelity check
    Given a campaign with an approved base resume variant
    And a posting whose required terms are only partly covered by the base resume
    When the engine selects or generates a resume variant for the posting
    Then a new variant is forked from the base with parent lineage
    And the new variant is not yet approved
    And the rendered artifact passes the compile-and-visually-inspect fidelity check
    And the rendered fonts are embedded and no em-dash remains

  Scenario: The docx fallback engine renders a fidelity-checked artifact too
    # FR-RESUME-3/4: LaTeX and docx-XML are substitutable under one fidelity contract.
    Given a campaign whose chosen material engine is docx
    When the docx engine renders the base resume artifact
    Then the docx artifact passes the compile-and-visually-inspect fidelity check
    And the docx fonts are embedded and no em-dash remains
