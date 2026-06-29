Feature: Onboarding continues through chat — proactive essentials probe
  # Issue #406 — product decision: the OOBE wizard may stay minimal AS LONG AS the
  # engine proactively probes for required-to-apply data not manually prefilled and
  # continues onboarding conversationally. The capability ships (EssentialsNudgeService
  # + chat gap-collection); both scenarios are now GREEN — the probe ships AND it is
  # enabled by default in production (#406 hardening).
  # Requirement: The engine MUST proactively surface missing required-to-apply
  # essentials and let the user resolve them in chat, enabled by default in production.

  Scenario: The engine can detect missing essentials and build a proactive nudge
    Given the essentials-nudge service
    When essentials are still missing for a campaign
    Then it builds a plain-language nudge naming what is still needed

  Scenario: Proactive onboarding-continuation is enabled by default in production
    Given the production deployment configuration
    When the essentials-nudge cadence default is read
    Then it is enabled (not off) so onboarding continues without manual setup
