# Issue #177 — A low field-match rate flags a probable wrong-ATS pre-fill for review
# (application/services/prefill_service.py) — FR-PREFILL-2/6.
# When the page model does not line up with the real form, field selectors miss and
# pre-fill silently fills (almost) nothing. The maximal pre-fill loop now tracks the
# field-match rate (fields filled vs detected) and flags a near-empty run for human
# review rather than offering garbage for submission.

Feature: A low field-match rate flags a probable wrong-ATS pre-fill for review

  Scenario: Pre-fill tracks how many detected fields it actually matched
    Given a pre-fill run over a form whose selectors do not match the chosen adapter
    When the maximal pre-fill loop walks the page
    Then the run records the field-match rate

  Scenario: A near-zero match rate flags the application instead of marking it pre-filled
    Given a pre-fill run that matched none of the detected fields
    When the loop finishes the page
    Then the application is flagged as a probable wrong-ATS run for operator review
