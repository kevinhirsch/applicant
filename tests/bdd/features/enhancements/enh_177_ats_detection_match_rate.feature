# Issue #177 — No ATS detection on pre-fill failure (application/services/prefill_service.py) — FR-PREFILL-2/6
# When the wrong ATS adapter is applied, field selectors miss and pre-fill silently
# fills nothing. There is no field-match-rate heuristic that flags a low-match run
# for operator review. PENDING — the detection seam does not exist yet.

Feature: A low field-match rate flags a probable wrong-ATS pre-fill for review

  @pending
  Scenario: Pre-fill tracks how many detected fields it actually matched
    Given a pre-fill run over a form whose selectors do not match the chosen adapter
    When the maximal pre-fill loop walks the page
    Then the run records the field-match rate

  @pending
  Scenario: A near-zero match rate flags the application instead of marking it pre-filled
    Given a pre-fill run that matched none of the detected fields
    When the loop finishes the page
    Then the application is flagged as a probable wrong-ATS run for operator review
