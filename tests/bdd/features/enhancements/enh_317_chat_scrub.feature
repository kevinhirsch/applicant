Feature: Engine chat replies are scrubbed before being forwarded to the browser
  # Issue #317 — workspace/routes/applicant_chat_routes.py:168-170 (send_message)
  # Requirement: The chat proxy MUST pass the engine's reply through a scrubber that
  # strips internal implementation detail (campaign/application UUIDs, credential
  # references, debug state) before returning it to the browser.

  Scenario: Internal identifiers are stripped from the forwarded chat reply
    Given an engine chat reply containing an internal campaign UUID
    When the chat proxy forwards the reply to the browser
    Then the internal UUID is scrubbed from the forwarded payload
