# Issue #285 — _is_context_error false positives (adapters/llm/openai_compatible.py) — FR-MIND
# GREEN: the fix — match specific error codes ("context_length_exceeded",
#        "maximum context length") instead of the bare substring "context".

Feature: Context-overflow detection matches the real error, not the word context

  Scenario: A genuine context-length error is detected as a context error
    Given the context-error classifier
    When a context-length-exceeded error envelope is checked
    Then it is detected as a context error

  Scenario: An unrelated error mentioning the word context is not a context error
    Given the context-error classifier
    When a content-filter error envelope mentioning the context of the request is checked strictly
    Then it is not flagged as a context error
