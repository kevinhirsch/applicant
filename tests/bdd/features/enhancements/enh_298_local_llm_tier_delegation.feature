# Issue #298 — Local LLM tier delegation — src/applicant/adapters/llm/openai_compatible.py
# The capability-ranked tier ladder with escalation already ships (GREEN): the adapter
# starts at a tier and escalates to the next when one fails or context overflows. The
# feature wants SMART delegation: a task classifier that routes by complexity (local-first
# for simple tasks, cloud for hard ones) and budget-aware spend tracking. No task
# classifier / per-task router exists, so those probes are @pending.

Feature: Smart local/cloud tier delegation

  Scenario: The LLM adapter escalates through the capability-ranked tier ladder
    Given the OpenAI-compatible LLM adapter
    When the tier-ladder escalation behaviour is inspected
    Then it advances to the next tier on failure or overflow

  @pending
  Scenario: A simple task is routed to the local tier by a classifier
    Given a task classifier that routes by complexity
    When a simple field-disambiguation task is classified
    Then it is routed to the local tier without calling the cloud

  @pending
  Scenario: Token spend is tracked per tier against a budget
    Given a per-tier budget tracker
    When tokens are spent on a tier
    Then the spend is accumulated per tier and checked against the budget
