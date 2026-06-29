# Issue #290 — Chat-driven campaign control — workspace/routes/applicant_chat_routes.py + chat_tools.py
# The chat surface can read state and run a few proxied actions (create campaign, send
# message, resolve pending action) — GREEN. But the assistant's tool belt cannot STEER
# the campaign in natural language: there is no engine chat tool for "create a campaign",
# "pause for the weekend", "approve today's digest". The @pending scenarios probe those
# missing steering tools and the proactive engine->chat push.

Feature: Chat-driven bidirectional campaign steering

  Scenario: The chat proxy exposes campaign listing and creation
    Given the front-door application
    When the mounted routes are inspected
    Then the chat surface exposes campaign list and campaign create paths

  Scenario: The chat proxy can resolve a pending action
    Given the front-door application
    When the mounted routes are inspected
    Then the chat surface exposes a pending-action resolve path

  @pending
  Scenario: The assistant can create a campaign from a natural-language command
    Given the assistant tool belt
    When the available tool schemas are listed
    Then a campaign-control tool for creating a campaign is offered

  @pending
  Scenario: The assistant can pause a campaign from a natural-language command
    Given the assistant tool belt
    When the available tool schemas are listed
    Then a campaign-control tool for pausing a campaign is offered

  @pending
  Scenario: The engine proactively pushes a digest summary into chat
    Given the engine has finished a discovery run
    When a proactive chat push is attempted
    Then a chat push channel delivers the digest summary with inline actions
