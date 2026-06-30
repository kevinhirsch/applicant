Feature: LLM/agent output rendered in chat is sanitized against HTML/script injection
  # Issue #354 — workspace/static/js/chatRenderer.js (innerHTML via markdownModule) + markdown.js
  # Requirement: All LLM/agent output rendered into the chat DOM MUST be sanitized so
  # script-capable tags, inline event handlers, and dangerous URL schemes cannot execute
  # (the markdown processor escapes text and scrubs preserved raw-HTML fragments).

  Scenario: The markdown sanitizer drops script tags and inline event handlers
    Given the chat markdown HTML sanitizer
    When a fragment with a script tag and an onerror handler is sanitized
    Then the script tag and the event handler are removed

  Scenario: A javascript: URL in a preserved link is neutralized
    Given the chat markdown HTML sanitizer
    When a link whose href is a javascript: URL is sanitized
    Then the dangerous href is stripped

  Scenario: Every chat innerHTML seam routes through one shared sanitizer
    Given the chat renderer module
    When it is inspected for a single shared sanitize call guarding raw-string innerHTML
    Then a reusable sanitizer guards each model-derived innerHTML assignment
