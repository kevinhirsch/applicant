# Issue #255 — workspace/mcp_servers/_common.py is orphaned
# _common.py defines truncate(), MAX_OUTPUT_CHARS and friends, but the MCP servers
# (email_server.py, memory_server.py, rag_server.py, image_gen_server.py) run as
# subprocesses and never import it. Cleanup shipped.

Feature: The shared MCP helper module is actually used or removed

  @pending
  Scenario: No MCP server imports the shared helper module
    Given the built-in MCP servers
    When each server module is scanned for an import of the shared helper
    Then none of them import it

  Scenario: The orphaned MCP helper module has been removed
    Given the built-in MCP servers
    Then the orphaned shared helper module no longer exists
