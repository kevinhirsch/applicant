Feature: Adding a model endpoint uses a typed request model with a validated model_type
  # Issue #319 — src/applicant/app/routers/model_endpoints.py:40-61 (add_endpoint)
  # Requirement: The add-endpoint route MUST validate its inputs with a typed model —
  # model_type constrained to a known enum and skip_probe a real bool — instead of
  # five bare Form() strings parsed by hand.

  Scenario: The string skip_probe flag is parsed to enable the live probe
    Given the model-endpoint add route
    When skip_probe is given as the string "false"
    Then the live model probe is enabled

  @pending
  Scenario: model_type is constrained to a known set of values
    Given the model-endpoint add route signature
    When the model_type parameter type is inspected
    Then it is constrained to an enum of allowed types, not a bare string
