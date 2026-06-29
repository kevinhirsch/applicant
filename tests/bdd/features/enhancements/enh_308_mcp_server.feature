Feature: Expose the engine as an MCP server
  # Issue #308 — research: docs/design/competitive-research.md
  # The engine is FastAPI, so fastapi_mcp (MIT) can expose its endpoints as an MCP
  # server with near-zero glue — an instant integration surface for external agents.
  # All @pending: no MCP surface is mounted yet.

  @pending
  Scenario: The engine mounts an MCP server surface
    Given a freshly booted Applicant engine
    When an MCP client lists the available tools
    Then the engine advertises its capabilities as MCP tools

  @pending
  Scenario: MCP tool calls reuse the same guarded application services
    Given the engine exposed as an MCP server
    When an MCP tool invokes a consequential action
    Then it passes through the same review/stop-boundary gates as the HTTP surface
