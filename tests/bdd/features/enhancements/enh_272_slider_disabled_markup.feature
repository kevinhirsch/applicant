Feature: Aggressiveness slider operability follows the dormant registry, not hardcoded markup
  # Issue #272 / #187 — aggressiveness slider is now LIVE in the dormant registry
# Front-door markup: workspace/static/index.html (#applicant-aggr-slider) +
# engine dormant registry: src/applicant/dormant.py (resume_aggressiveness). This is the
# UI twin of #187. The slider is rendered permanently disabled in static markup, so even
# though resume_aggressiveness is now "live" in the dormant registry the control
# would still be disabled in markup. GREEN: the registry correctly records the surface as
# live after #187. PENDING: the slider's enabled/disabled state is not derived from the
# registry status.

  Scenario: The aggressiveness surface is registered as live after #187
    Given the dormant-surface registry
    When the résumé-aggressiveness surface is looked up
    Then it is recorded as a live surface

  Scenario: The slider's operability follows the registry status, not hardcoded markup
    Given the résumé-aggressiveness control markup
    When the surface is read for a hardcoded disabled state
    Then the control is not statically disabled in the markup
