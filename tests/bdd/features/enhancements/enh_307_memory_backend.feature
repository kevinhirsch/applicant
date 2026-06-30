Feature: Vendor-able agent-memory backend behind the memory port
  # Issue #307 — research: docs/design/competitive-research.md
  # Build-vs-buy for the memory substrate: a permissive backend (mem0 / Letta /
  # Graphiti, all Apache-2.0) selectable behind the memory port, with the in-house
  # store as the default. Verified win to cite: p95 latency, NOT the refuted token
  # claim. All @pending: backend selection is not wired.

  Scenario: The memory backend is selectable behind a stable port
    Given a memory driven port with a pluggable backend
    When the backend is configured to a vendor-able implementation
    Then the engine writes and reads memory through the same port contract unchanged

  Scenario: Swapping the backend does not change the memory port contract
    Given two memory backends implementing the same port
    When the same store-and-recall sequence runs against each
    Then both satisfy the port's contract test identically

  Scenario: Temporal facts carry validity windows
    Given a temporal knowledge-graph memory backend
    When a fact is superseded by a newer fact
    Then the older fact is retained with a closed validity window rather than overwritten
