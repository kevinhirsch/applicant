Feature: The feature-state endpoint does not leak engine configuration
  # Issue #231 — workspace/app.py:149 adds /api/applicant/features to AUTH_EXEMPT_EXACT
  # The unauthenticated endpoint returns compute_features(), which reflects which LLM and
  # notification channels are configured and which surfaces are live — deployment-internal
  # detail. A sanitised public variant that reveals no configuration state does not exist
  # yet → @pending probe on that intended seam.

  Scenario: A sanitised public feature view hides configuration state
    Given the workspace feature-state module
    When a configuration-free public feature view is requested
    Then a sanitised public feature view is available that omits engine configuration state
