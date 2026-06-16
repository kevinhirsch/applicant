"""Tool-registry adapter (FR-UI-4).

# STAGE B — owned by Phase 4; flesh out here (persist to tool_settings table).

In-memory per-tool on/off registry. Unknown registered tools default to enabled.
The initial registry mirrors the dormant-surface tool list (Discovery, Scoring,
Pre-fill, ..., Notifications). Phase 4 persists toggles and enforces at dispatch.
"""

from __future__ import annotations

#: Initial tool registry (FR-UI-4 / docs/dormant-surfaces.md §5).
DEFAULT_TOOLS: tuple[str, ...] = (
    "discovery",
    "scoring",
    "prefill",
    "account_creation",
    "web_research",
    "resume_tailoring",
    "cover_letter_generation",
    "screening_answer_generation",
    "chat",
    "notifications",
)


class ToolRegistry:
    """ToolRegistryPort adapter (in-memory; defaults all tools enabled)."""

    def __init__(self) -> None:
        self._state: dict[str, bool] = {t: True for t in DEFAULT_TOOLS}

    def is_enabled(self, tool_key: str) -> bool:
        return self._state.get(tool_key, True)

    def set_enabled(self, tool_key: str, enabled: bool) -> None:
        self._state[tool_key] = enabled

    def all_tools(self) -> dict[str, bool]:
        return dict(self._state)
