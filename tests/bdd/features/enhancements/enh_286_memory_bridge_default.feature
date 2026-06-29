# Issue #286 — Memory backend default — src/applicant/adapters/memory/factory.py + app/config.py
# The agent-memory factory ships both an in_memory backend (hermetic, isolated) and a
# bridge backend (reaches the workspace memory/skills/recall substrate). The bridge
# adapters are fully implemented (GREEN), but the DEFAULT is in_memory, so workspace-
# curated memories never reach the engine unless the operator sets MIND_BACKEND=bridge.
# The @pending scenario probes the desired production default (bridge).

Feature: Agent memory can bridge to the workspace, but defaults to isolated

  Scenario: The bridge memory adapters are implemented
    Given the agent-memory factory
    When the bridge backend is selected
    Then the trio is backed by workspace-bridge adapters

  Scenario: The in-memory backend is available for the hermetic test lane
    Given the agent-memory factory
    When the in-memory backend is selected
    Then the trio is backed by in-process adapters

  @pending
  Scenario: The bridge backend is the production default
    Given the engine default configuration
    When the configured memory backend is read
    Then it is the bridge so workspace memories reach the engine by default
