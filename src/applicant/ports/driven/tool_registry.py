"""ToolRegistry port (FR-UI-4).

Per-tool on/off toggles (Discovery, Scoring, Pre-fill, ... Notifications). Toggles
are enforced at tool dispatch; backed by the ``tool_settings`` table.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ToolRegistryPort(Protocol):
    """Outbound port for per-tool enable/disable settings."""

    def is_enabled(self, tool_key: str) -> bool:
        """True if the tool is enabled (default True for unknown registered tools)."""
        ...

    def set_enabled(self, tool_key: str, enabled: bool) -> None:
        """Toggle a tool on/off."""
        ...

    def all_tools(self) -> dict[str, bool]:
        """Return the full registry (tool_key -> enabled)."""
        ...
