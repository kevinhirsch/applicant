Feature: Résumé rendering degrades honestly when render binaries are absent
  # Issue #178 — TeX/LibreOffice rendering degrades to stubs when binaries are absent
  # Engine render adapters: adapters/resume_tailoring/latex_tailor.py + docx_tailor.py
  # (FR-RESUME-3/4). render_mode="auto" runs the real compile/convert only when a TeX
  # engine / LibreOffice is on PATH, otherwise it degrades to a deterministic estimate.
  # GREEN: the path-selection logic is hermetically testable — auto + no binary never
  # attempts a real compile, and a forced compile with no binary reports an honest
  # "approximate preview" rather than pretending it is a faithful render. PENDING: a real
  # font-embedded PDF compile needs the binaries (integration), and plain "auto" can
  # still silently produce an estimate without telling the user.

  Scenario: With no TeX engine on PATH the LaTeX adapter does not attempt a real compile
    Given a LaTeX résumé adapter in auto render mode with no TeX engine available
    When a résumé artifact is rendered
    Then the real compile is not attempted

  Scenario: A forced render with no TeX engine reports an approximate preview, not a faithful match
    Given a LaTeX résumé adapter forced to render with no TeX engine available
    When a résumé artifact is rendered
    Then the result is flagged as an approximate preview rather than a faithful match

  Scenario: With no converter on PATH the docx adapter does not attempt a real convert
    Given a docx résumé adapter in auto render mode with no converter available
    When a docx artifact is rendered
    Then the real convert is not attempted

  @pending
  Scenario: A real font-embedded PDF is produced and inspected
    Given a LaTeX résumé adapter with the render tools installed
    When a résumé artifact is rendered for real
    Then a real PDF is produced with every font embedded
