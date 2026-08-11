Feature: Per-use-case model configuration (EPIC MODEL-CONFIG)
  As the operator
  I want every LLM use case bound to local OR any OpenAI-compatible endpoint from Settings
  So that no model/endpoint choice is hardcoded and defaults are preset but overridable

  Background:
    Given a setup service and model-endpoint registry sharing one config store
    And the tier ladder is local qwen with a DeepSeek cloud fallback

  Scenario: Fresh install works with zero config
    Given no per-use-case bindings are stored
    When I resolve the ladder for the "scoring" use case
    Then it is exactly the shared tier ladder
    And every documented use case is listed as configurable

  Scenario: Binding a use case to a custom OpenAI-compatible endpoint
    Given I add an OpenAI-compatible endpoint at "https://openrouter.ai/api/v1"
    When I bind the "drafting_cover_letter" use case to that endpoint with model "deepseek-v4-flash"
    And I resolve the ladder for the "drafting_cover_letter" use case
    Then the primary tier is "deepseek-v4-flash" at that endpoint
    And the shared ladder remains below it as the fallback

  Scenario: An arbitrary endpoint is usable for any use case
    Given I add an OpenAI-compatible endpoint at "https://api.deepseek.com/v1"
    When I bind the "chat" use case to that endpoint with model "deepseek-chat"
    Then the "chat" use case reports it is bound to that endpoint and model

  Scenario: Resetting a use case restores the shared-ladder default
    Given I add an OpenAI-compatible endpoint at "https://x.ai/v1"
    And I bind the "research" use case to that endpoint with model "grok"
    When I reset the "research" use case to default
    Then resolving the "research" ladder is exactly the shared tier ladder
