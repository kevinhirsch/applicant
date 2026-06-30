# Issue #209 — _is_screening_question classifies by word count >=6 (application/services/prefill_service.py) — FR-ANSWER-1
# GREEN: regression proving the CURRENT heuristic — an essay question is classified as
#        a screening question, and a short data field is NOT.
# PENDING: the bug — a 6-word factual data field ("Current Street Address Line 2") is
#          misclassified as a screening question; the fix excludes known data patterns.

Feature: Data fields are not misclassified as essay screening questions

  Scenario: A free-text essay prompt is treated as a screening question
    Given the screening-question classifier
    When a free-text essay prompt field is classified
    Then it is treated as a screening question

  Scenario: A short plain data field is not a screening question
    Given the screening-question classifier
    When a short first-name field is classified
    Then it is not treated as a screening question

  Scenario: A six-word address data field is not misclassified as a screening question
    Given the screening-question classifier
    When a six-word address line field is classified
    Then it is not treated as a screening question
