# Issue #304 — Remove: Cookbook integration with Applicant (descoped, except local-LLM tier)
# Cookbook-to-Applicant wiring is descoped EXCEPT for local-model serving, which must flow
# through the standard tier-ladder, not Cookbook-specific integration points. Cookbook is
# not an Applicant feature section (GREEN — that absence holds). But a Cookbook-specific
# coupling still exists: the engine's internal callback exposes a Cookbook local-models
# lane and config carries a cookbook_local_host. The acceptance criterion is ABSENCE of
# that Cookbook-specific coupling, so the @pending scenarios probe its removal.

Feature: Cookbook integration with Applicant is descoped except the tier ladder

  Scenario: Cookbook is not an Applicant feature section
    Given the Applicant feature-state layer
    When the Applicant section registry is inspected
    Then there is no cookbook section in the registry

  @pending
  Scenario: The internal callback channel exposes no Cookbook-specific lane
    Given the front-door internal callback routes
    When the internal routes are inspected
    Then no Cookbook-specific local-models lane is exposed

  @pending
  Scenario: The engine config carries no Cookbook-specific setting
    Given the engine settings
    When the settings fields are inspected
    Then there is no Cookbook-specific host setting
