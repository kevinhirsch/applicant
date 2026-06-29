Feature: Digest score reuse keys on criteria only, ignoring learning state
  # Issue #239 — scoring_service.py: score_for_digest cache key ignores learning state
# score_for_digest reuses a persisted score keyed only by criteria_sig (titles, keywords,
# work modes, locations, salary floor, free text). It does NOT fold in the learning-model
# state, so after conversions shift the converting-role signature the digest keeps
# returning the stale pre-conversion score until the user edits their criteria. GREEN:
# criteria-keyed reuse is real and a criteria change forces a re-score. PENDING: a change
# in learning state alone does not invalidate the cached score.

  Scenario: An unchanged-criteria digest reuses the persisted score
    Given a posting already scored against fixed criteria
    When the digest re-scores it with the same criteria
    Then the persisted score is reused without recomputation

  Scenario: Editing the criteria forces a fresh digest score
    Given a posting already scored against fixed criteria
    When the digest re-scores it after the criteria change
    Then a fresh score is computed for the new criteria

  Scenario: A new conversion invalidates a stale digest score
    Given a posting scored at cold start before any conversions
    When the campaign learns a converting-role signature that aligns with the posting
    And the digest re-scores it with unchanged criteria
    Then the digest reflects the higher learning-biased score rather than the stale one
