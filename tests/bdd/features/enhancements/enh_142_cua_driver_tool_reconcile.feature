# Issue #142 — FR-CUA-2 — adapters/sandbox/computer_use/cua_driver.py
# The MCP/stdio transport maps the bounded desktop vocabulary onto driver tool names
# (_TOOL_NAMES + _HEALTH_TOOL) and validates them against the driver's own tools/list at
# startup, warning loudly on any mismatch. The name/schema map + the validation seam SHIP
# (GREEN). Reconciling the map against the REAL cua-driver binary's published schema is the
# integration leg (skip-when-absent) and stays @pending.

Feature: The cua-driver adapter maps and reconciles the bounded desktop tool vocabulary

  Scenario: Every bounded desktop action maps to a driver tool name
    Given the cua-driver tool-name registry
    Then every bounded desktop action and the health preflight has a mapped tool name

  Scenario: The startup handshake reconciles the tool map against the driver's tools/list
    Given a cua-driver session talking to a driver that advertises the mapped tools
    When the session handshake runs and lists the driver's tools
    Then the mapped tool names are confirmed present with no mismatch warning

  Scenario: A driver missing a mapped tool is flagged loudly, not silently
    Given a cua-driver session talking to a driver missing one mapped tool
    When the session handshake runs and lists the driver's tools
    Then the missing tool is reported as a reconciliation warning

  @pending
  @integration
  Scenario: The tool argument schemas are reconciled against the real cua-driver binary
    Given a real cua-driver binary baked into the sandbox image
    When a capture and a benign click are round-tripped against it
    Then the argument keys and the health_report shape match the live driver schema
