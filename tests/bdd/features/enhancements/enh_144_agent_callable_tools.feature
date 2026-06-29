# Issue #144 — FR-MIND-6 / FR-CUA-2 — application/services/loop_tools.py + chat_tools.py
# Memory/skills/recall and the bounded desktop action exposed as tools the autonomous
# loop's tool-capable model can CHOOSE to call mid-reasoning. The LoopToolset lifts the
# chat toolbox (memory.* / skill_manage / recall / desktop) and registers it for the loop,
# opt-in via LOOP_TOOLS and only when the model advertises tool calling; every call routes
# through the existing guards (staged-write review, advisory-not-authorization, the FR-CUA
# stop-boundary, the FR-UI-4 toggle). That SHIPS (GREEN). A single central engine-wide tool
# registry + dispatch (one ToolRegistry.handle_function_call for the whole engine) is the
# residual refactor and stays @pending.

Feature: The autonomous loop can call memory, skills, recall, and desktop as tools

  Scenario: The loop offers memory, skills, and recall as callable tools
    Given an agent-memory backend and a curation service wired into the loop toolset
    When the loop's tool schemas are collected
    Then memory, skills, and recall tools are offered to the model

  Scenario: The bounded desktop action is offered only when desktop assist is operable
    Given an agent-memory backend wired into the loop toolset
    When desktop assist is operable
    Then a bounded desktop tool is also offered
    But when desktop assist is not operable the desktop tool is withheld

  Scenario: The loop toolset is off by default
    Given the loop-tools setting is left at its default
    When the loop toolset is built
    Then no toolset is built and the loop runs exactly as before

  Scenario: The loop toolset is withheld when the model cannot call tools
    Given the loop-tools setting is enabled but the model does not advertise tool calling
    When the loop toolset is built
    Then no toolset is built

  Scenario: A memory write through a loop tool is staged for review, never silently applied
    Given an agent-memory backend and a curation service wired into the loop toolset
    When the model calls the remember tool with a note
    Then the note is staged for the user's approval rather than applied silently

  @pending
  Scenario: A single engine-wide tool registry dispatches every agent tool call
    Given the engine's central tool registry
    Then memory, skills, recall, and desktop are registered for one shared dispatch path
