# Issue #325 — workspace/src/ai_interaction.py (lines 982, 1021, 1053)
# Requirement: The front-door MUST emit a diagnostic (a logger warning) when a memory
# vector-store add/remove fails, instead of swallowing it with `except Exception: pass`,
# so an unhealthy ChromaDB vector store is detectable rather than letting memories
# silently desync from the canonical store.
# Memory vector CRUD (add/remove) is wrapped in bare `except Exception: pass`. GREEN: the
# canonical JSON memory is the source of truth and a vector-store failure must not lose
# the memory. @pending: the vector failure is silent — no warning is logged, so a down
# vector store goes undetected and memories silently desync.

Feature: Memory vector-store failures surface a diagnostic instead of silence

  Scenario: A vector-store add failure does not lose the canonical memory
    Given the front-door memory action over a healthy canonical store
    When the vector index add raises
    Then the memory is still persisted to the canonical store rather than lost

  @pending
  Scenario: A vector-store add failure is logged as a warning rather than swallowed
    Given the front-door memory action over a healthy canonical store
    When the vector index add raises
    Then a warning naming the vector-store failure is logged rather than silently discarded
