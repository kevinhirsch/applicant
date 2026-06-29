# Issue #222 — LLM escalation defence in depth / application/services/prefill_service.py:_escalate_mapping
# The escalation prompt joins ALL attribute names — including sensitive ones (gender, race,
# ethnicity) — so the LLM SEES them; a new EEO attribute whose name is not in the substring
# markers could be mapped and slip past the gate. GREEN: a sensitive field is never itself
# escalated to an LLM guess. @pending: sensitive attribute names are filtered out of the
# escalation prompt entirely.

Feature: Sensitive attribute names are kept out of the LLM escalation prompt

  Scenario: A sensitive field is never escalated to an LLM guess
    Given a configured LLM and a sensitive form field
    When the engine considers escalating the field's mapping
    Then no LLM call is made for the sensitive field

  @pending
  Scenario: Sensitive attribute names are excluded from the escalation prompt text
    Given a configured LLM and an attribute cloud containing a demographic attribute
    When the engine builds the escalation prompt for a non-sensitive field
    Then the demographic attribute name does not appear in the prompt
