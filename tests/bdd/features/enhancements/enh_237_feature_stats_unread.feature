Feature: Approve and decline signals are recorded but never bias scoring
  # Issue #237 — learning_service.py: feature_stats accumulated but never read
# record_decision() writes approve/decline signals into feature_stats, and load_model /
# persist_model round-trip them, but no code path reads feature_stats to bias scoring,
# discovery or selection. GREEN: the approve/decline fold and durable round-trip are
# real. PENDING: nothing consumes feature_stats to actually bias a future score, so the
# approve/decline feedback loop is open.

  Scenario: An approve and a decline both land in the per-feature stats
    Given a fresh learning model for a campaign
    When a senior role is approved and a junior role is declined
    Then the per-feature stats record one approve bucket and one decline bucket

  Scenario: Recorded per-feature stats survive a load and persist round-trip
    Given a learning model with recorded per-feature stats
    When the model is persisted and reloaded
    Then the per-feature stats are restored from storage

  Scenario: Accumulated taste signals actually bias the next viability score
    Given a campaign that has approved a feature and declined another
    When a posting matching the declined feature is scored
    Then the recorded feature stats lower its viability score relative to the unbiased baseline
