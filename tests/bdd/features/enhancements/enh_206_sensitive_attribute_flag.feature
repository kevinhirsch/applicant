# Issue #206 — sensitive-field detection / core/rules/sensitive_fields.py + prefill _resolve_value
# The sensitive gate keys on the form-field LABEL (is_sensitive_field), never on the
# attribute's own is_sensitive flag. A label the substring matcher misses (false negative)
# but whose attribute is marked is_sensitive=True flows through the non-sensitive path
# without the decide_sensitive_fill gate. GREEN: the label-based rule fires for known EEO
# labels. @pending: an attribute flagged sensitive is gated even when the label is missed.

Feature: An attribute marked sensitive is gated even when the label is not recognised

  Scenario: A recognised EEO label routes through the sensitive policy
    Given a form field whose label is a recognised demographic field
    When the sensitive-field rule classifies the label
    Then the field is treated as sensitive

  @pending
  Scenario: An attribute flagged sensitive is gated despite an unrecognised label
    Given an attribute marked sensitive whose label the substring matcher misses
    When the engine resolves a value for that field
    Then the value is routed through the sensitive-field policy, not the plain path
