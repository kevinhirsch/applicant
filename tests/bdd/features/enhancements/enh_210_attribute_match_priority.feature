# Issue #210 — attribute lookup priority / application/services/prefill_service.py:_lookup
# _lookup returns the FIRST attribute matching a label — no priority. When two attributes
# match (e.g. "Phone" matches both `phone` and a `phone_alternate` alias), iteration order
# wins arbitrarily. GREEN: the current first-match behaviour is deterministic. @pending: an
# exact name match is preferred over an aliased alternate.

Feature: Attribute lookup prefers the best match, not merely the first

  Scenario: The current lookup returns a matching attribute deterministically
    Given two attributes that both match a field label
    When the engine looks up a value for that label
    Then a matching value is returned deterministically by list order

  @pending
  Scenario: An exact name match wins over a merely-aliased alternate
    Given a field labelled "Phone" with both a primary phone and an aliased alternate
    When the engine looks up a value for that label
    Then the primary phone value wins over the alternate
