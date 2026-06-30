# Issue #211 — LLM escalation / application/services/prefill_service.py:_escalate_mapping
# A failing-but-configured LLM is caught with `except Exception: return None`, silently
# degrading EVERY unmapped field to a missing-attr block — one confusing pending action per
# field, with no indication the LLM was the root cause. GREEN: when the LLM errors, mapping
# returns None and the field falls through (no crash). @pending: a single "LLM unavailable"
# diagnostic is surfaced after the first failure.

Feature: A failing LLM surfaces one diagnostic rather than dozens of confusing blocks

  Scenario: A failing LLM mapping degrades the field without crashing
    Given a configured LLM that raises on every mapping call
    When the engine escalates an ambiguous field to the LLM
    Then the mapping returns nothing and the loop does not crash

  Scenario: A failing LLM emits one "unavailable" diagnostic for the whole run
    Given a configured LLM that raises on every mapping call
    When the engine escalates an ambiguous field to the LLM
    Then a single diagnostic event reports the LLM was unavailable
