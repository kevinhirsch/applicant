# EPIC AGENTS / RC2 — Auto-apply reversible tweaks
# docs/stories/self-improving-agents.md, docs/adr/0009-self-improving-agents.md
#
# NOT YET WIRED — see epic_self_improving_agents.feature's header for the scaffold convention.

Feature: Reflection Coach auto-applies transparent, reversible tweaks

  @pending
  Scenario: A non-integral learned tweak auto-applies and is visible
    Given the effectiveness assessment recommends a non-integral criteria adjustment
    When the Reflection Coach applies it
    Then CriteriaService.apply_learned_adjustment records the delta and a human-readable summary
      in learned_adjustments
    And the change is visible to the user without them having to ask

  @pending
  Scenario: An integral-field tweak is proposed, not silently applied
    Given the effectiveness assessment recommends changing titles, locations, or salary_floor
    When the Reflection Coach files the recommendation
    Then it is staged as a proposed_integral learned adjustment
    And it requires explicit user confirmation before it takes effect

  @pending
  Scenario: Any auto-applied tweak is one-click reversible
    Given a tweak the Reflection Coach auto-applied
    When the user reverts it
    Then CriteriaService.edit_criteria(clear_learned=True) restores the prior state
    And the reversal is itself audited
