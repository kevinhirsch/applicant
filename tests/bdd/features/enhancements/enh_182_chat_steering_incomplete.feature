Feature: Chat-driven steering of the autonomous loop
  # Issue #182 — src/applicant/application/services/chat_service.py
  # The chatbot can pause/resume, set throughput, and refocus criteria through chat
  # (GREEN). The residual gap: bulk digest steering such as "approve all today's digest
  # items" is not a routable control intent yet (@pending).

  Scenario: Chat can pause and resume the autonomous loop
    Given the chat loop-control intent parser
    When a pause directive and a resume directive are parsed
    Then both are recognized as steering directives the chat can route

  Scenario: Throughput and criteria refocus are steerable control kinds
    Given the chat control-action contract
    When the supported control kinds are listed
    Then pause, resume, throughput and criteria refocus are all steerable

  @pending
  Scenario: Chat can approve all of today's digest items
    Given the chat control-action contract
    When the user asks to approve all of today's digest items through chat
    Then an approve-all digest control kind is routed to the digest service
