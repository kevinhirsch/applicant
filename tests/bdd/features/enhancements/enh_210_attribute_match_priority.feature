# Issue #210 — attribute lookup priority / application/services/prefill_service.py:_lookup
# _lookup now uses priority tiers: exact name match > alias match > loose/fuzzy match.
# The @pending scenario below is active and asserts exact-name priority.

Feature: Attribute lookup prefers the best match, not merely the first

  Scenario: The current lookup returns a matching attribute deterministically
    Given two attributes that both match a field label
    When the engine looks up a value for that label
    Then a matching value is returned deterministically by list order

  Scenario: An exact name match wins over a merely-aliased alternate
    Given a field labelled "Phone" with both a primary phone and an aliased alternate
    When the engine looks up a value for that label
    Then the primary phone value wins over the alternate
