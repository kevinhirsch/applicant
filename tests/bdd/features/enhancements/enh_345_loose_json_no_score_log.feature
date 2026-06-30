# Issue #345 — scoring_service.py:308-323 (_parse_json_loose silent no-score)
# Requirement: When the model returns JSON that parses but lacks a "score" key, the
# scorer MUST emit a warning naming the mis-shaped output before degrading to the
# embedding fallback — the fallback stays safe but is no longer silent to operators.
Feature: Loose-JSON parse without a score is observable

  # GREEN — what ships today: loose parsing extracts a JSON object from noisy text.
  Scenario: A JSON object embedded in noisy model output is recovered
    Given the loose-JSON parser
    When it is given model output with a JSON object wrapped in prose
    Then the embedded object is returned as a dictionary

  # GREEN — what ships today: a well-shaped score reply yields the score key.
  Scenario: A well-shaped reply yields the score and rationale keys
    Given the loose-JSON parser
    When it is given a clean JSON reply with a score and a rationale
    Then the parsed dictionary carries the score key

  # PENDING — the residual gap: a score-less reply must be logged, not silently dropped.
  Scenario: A parsed reply that lacks a score is logged before the fallback
    Given a scoring service whose model returns JSON without a score key
    When the model-backed base score is attempted
    Then a warning is logged that the model returned no score before the embedding fallback
