Feature: The converting-role centroid works directly but is never populated by the live loop
  # Issue #238 — learning_service.py: record_converting_role is dead code
# record_converting_role() folds a converted role's JD into the Phase-1 centroid
# (converting_role_signature["vector"]), but it is never called anywhere in the live
# code. The live conversion loop folds only the DISCRETE signature via the advanced
# learning service, leaving the centroid vector empty, so converting_alignment() always
# returns 0.0. GREEN: the method works correctly when invoked directly. PENDING: a real
# conversion through the live loop never populates the Phase-1 centroid vector.

  Scenario: Folding a converted role directly populates the centroid vector
    Given a fresh learning model for a campaign
    When a converted role description is folded into the centroid
    Then the converting-role signature carries a non-empty centroid vector
    And the alignment of a similar role is greater than zero

  @pending
  Scenario: A real conversion through the live loop populates the Phase-1 centroid
    Given a campaign whose application converts through the submission loop
    When the conversion loop closes
    Then the Phase-1 converting-role centroid vector is populated by that conversion
