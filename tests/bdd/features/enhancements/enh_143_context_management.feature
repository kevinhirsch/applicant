# Issue #143 — FR-MIND-8 / FR-MIND-13 — application/services/context_manager.py
# Engine-side context management: middle-turn compression once context crosses a
# configurable threshold (with parent/child lineage), and provider-gated prefix caching
# (the Anthropic cache_control analogue) applied only where the configured provider
# advertises support — a clean no-op for local Ollama / OpenAI-compatible lanes. The
# ContextManager service, the prefix-cache helpers, and the CONTEXT_COMPRESS_THRESHOLD /
# PREFIX_CACHE settings all SHIP, so every scenario here is GREEN.

Feature: Engine context management compresses middle turns and gates prefix caching

  Scenario: Middle turns compress once context crosses the threshold
    Given a long multi-turn conversation past the compression threshold
    When the context manager compresses it
    Then the middle turns collapse into one bounded summary turn
    And the system tier and the most recent turns are preserved

  Scenario: Compression records parent/child lineage of what it subsumed
    Given a long multi-turn conversation past the compression threshold
    When the context manager compresses it
    Then the lineage records which earlier turns the summary subsumes

  Scenario: Compression is a no-op when disabled or under budget
    Given a conversation with the compression threshold disabled
    When the context manager compresses it
    Then the turns come back unchanged

  Scenario: Prefix caching applies only when the provider advertises support
    Given a provider profile that advertises prefix-cache support
    When prefix-cache breakpoints are applied to the request
    Then the stable-prefix cache breakpoint is stamped on the request

  Scenario: Prefix caching is a clean no-op for local Ollama and OpenAI-compatible lanes
    Given the built-in local and OpenAI-compatible provider profiles
    When prefix-cache breakpoints are applied to the request
    Then no cache breakpoint is added for those providers

  Scenario: The prefix-cache posture can be turned off entirely
    Given a provider profile that advertises prefix-cache support
    When the operator sets the prefix-cache posture to off
    Then no cache breakpoint is added even for a supporting provider
