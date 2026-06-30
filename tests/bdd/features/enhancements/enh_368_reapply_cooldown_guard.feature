Feature: The agent never re-applies to the same company+role within a cooldown
  # Issue #368 — application-level guard (new); contrast discovery dedup #196
  # Requirement: Before applying, the engine MUST check the user's own application
  # history and skip (or hold) a posting matching an already-applied company+role
  # within a configurable cooldown window; after the window elapses the same role is
  # eligible again. Discovery dedup (#196) collapses near-duplicate LISTINGS within a
  # run — that is GREEN — but it does not stop APPLYING to the same role twice.

  Scenario: Near-duplicate listings within one discovery run are collapsed
    Given two near-identical postings surface in one discovery run
    When the discovery results are deduplicated
    Then only one of the near-identical listings survives

  Scenario: A posting matching a prior application within cooldown is not re-applied
    Given the user already applied to a company and role
    When the same company and role is considered again within the cooldown window
    Then the application-history guard skips or holds it instead of re-applying

  Scenario: The same role after the cooldown is eligible again
    Given the user applied to a company and role long enough ago to clear the cooldown
    When the same company and role is considered again after the cooldown window
    Then the application-history guard treats it as eligible to apply
