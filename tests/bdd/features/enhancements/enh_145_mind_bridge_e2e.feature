# Issue #145 — FR-MIND §10 — adapters/memory/factory.py + adapters/memory/bridge.py
# Two production paths are wired but only hermetically tested: MIND_BACKEND=bridge (the
# engine reaching the front-door memory/skills substrate over the token-gated internal
# channel) and the real cua-driver smoke. The backend selection + the degrade-when-the-
# channel-is-off behavior SHIP (GREEN). The live engine<->workspace round-trip and the
# baked-driver desktop smoke require a multi-container stack and stay @pending/integration.

Feature: MIND_BACKEND=bridge selects the workspace substrate and degrades cleanly offline

  Scenario: Selecting the bridge backend wires the workspace-bridge adapters
    Given the mind backend is set to bridge
    When the agent-memory trio is built
    Then the bridge-backed memory, skills, and recall adapters are wired

  Scenario: The default backend stays the hermetic in-memory trio
    Given the mind backend is left at its default
    When the agent-memory trio is built
    Then the in-memory memory, skills, and recall adapters are wired

  Scenario: The bridge degrades to empty results when the internal channel is off
    Given the bridge backend with the engine-to-workspace channel turned off
    When memory is added and a snapshot is read back
    Then the bridge degrades to an empty result rather than raising

  @pending
  @integration
  Scenario: A bridge round-trip reflects the live workspace substrate
    Given a live workspace with the internal token set and MIND_BACKEND=bridge
    When the engine adds a memory entry and reads the snapshot back
    Then the entry is reflected from the workspace substrate

  @pending
  @integration
  Scenario: A curation approval persists through to the workspace substrate
    Given a curation proposal approved in the portal against a live workspace
    When the approval is applied
    Then the change persists into the workspace substrate
