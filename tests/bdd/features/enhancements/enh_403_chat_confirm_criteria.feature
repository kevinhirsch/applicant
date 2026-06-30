Feature: A chat-proposed criteria refocus can be committed from the front-door
  # Issue #403 — engine POST /api/chat/confirm-criteria (chat.py:83); no proxy/client
  # Requirement: A chat-proposed, confirmation-gated criteria change MUST be committable
  # from the front-door (a proxy + a client method that POSTs to /api/chat/confirm-criteria).

  Scenario: The front-door commits a chat-proposed criteria refocus
    Given the front-door chat engine client
    When a confirmation-gated criteria refocus is committed through the front-door
    Then the engine client exposes a confirm-criteria method distinct from confirm-attribute
