"""Tool-registry adapter (FR-UI-4).

# STAGE B — owned by Phase 4; flesh out here (persist to tool_settings table).

Per-tool on/off registry implementing ``ToolRegistryPort``. The initial registry
mirrors the dormant-surface tool list (docs/dormant-surfaces.md §5): Discovery,
Scoring, Pre-fill, Account-Creation, Web-Research, Resume-Tailoring,
Cover-Letter-Generation, Screening-Answer-Generation, Chat, Notifications.

Toggles are enforced at tool dispatch (``ensure_enabled``) and persisted to the
``tool_settings`` table when a persistence sink is supplied. The default in-memory
mode keeps the contract simple for tests; unknown registered tools default to
enabled so a newly added tool is never silently dark (NFR-EXT-1 extensibility).
"""

from __future__ import annotations

from typing import Protocol

from applicant.core.errors import DomainError

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

#: Human-readable labels for the FR-UI-4 toggle panel.
TOOL_LABELS: dict[str, str] = {
    "discovery": "Discovery",
    "scoring": "Scoring",
    "prefill": "Pre-fill",
    "account_creation": "Account-Creation",
    "web_research": "Web-Research",
    "resume_tailoring": "Resume-Tailoring",
    "cover_letter_generation": "Cover-Letter-Generation",
    "screening_answer_generation": "Screening-Answer-Generation",
    "chat": "Chat",
    "notifications": "Notifications",
}


class ToolDisabledError(DomainError):
    """Raised when a disabled tool is dispatched (FR-UI-4 enforcement)."""


class ToolSettingsSink(Protocol):
    """Optional persistence sink for ``tool_settings`` (driven side).

    Any object exposing ``load() -> dict[str, bool]`` and
    ``save(state: dict[str, bool]) -> None`` may back the registry; the in-memory
    default is used when no sink is supplied.
    """

    def load(self) -> dict[str, bool]: ...
    def save(self, state: dict[str, bool]) -> None: ...


class ToolRegistry:
    """ToolRegistryPort adapter (defaults all tools enabled; optional persistence).

    When ``sink`` is provided, every toggle is written through to ``tool_settings``
    and the persisted state is loaded on construction so toggles survive restarts.
    """

    def __init__(self, sink: ToolSettingsSink | None = None) -> None:
        self._sink = sink
        self._state: dict[str, bool] = {t: True for t in DEFAULT_TOOLS}
        if sink is not None:
            try:
                self._state.update({k: bool(v) for k, v in sink.load().items()})
            except Exception:
                # First boot / empty table — keep defaults (no dead UI, no crash).
                pass
        # FR-MIND-6 (#144): the ONE engine-wide dispatch surface for every agent tool
        # call (memory / skills / recall / desktop). Per-campaign tool sets register
        # their dispatcher here so a model's ``function_call`` is routed through a single
        # shared path that also enforces the FR-UI-4 toggle — instead of each campaign's
        # LoopToolset/ChatToolbox owning its own private dispatch with no central gate.
        self._dispatchers: dict[str, object] = {}

    # --- central agent-tool dispatch (FR-MIND-6, #144) --------------------
    def register_dispatcher(self, key: str, dispatcher: object) -> None:
        """Register a tool dispatcher (e.g. a campaign's ``LoopToolset``) under ``key``.

        The dispatcher must expose ``dispatch(name, arguments) -> str`` (the shape
        ``LoopToolset``/``ChatToolbox`` already implement). Registering it routes its
        tool calls through the single :meth:`handle_function_call` path.
        """
        self._dispatchers[key] = dispatcher

    def handle_function_call(
        self, name: str, arguments: str, *, key: str | None = None, tool_key: str | None = None
    ) -> str:
        """Dispatch ONE agent tool/function call through the central registry (#144).

        This is the single engine-wide entry point every agent tool call flows through:
        memory (``remember``/``forget``), skills (``save_playbook``/``update_playbook``),
        recall, and the bounded ``desktop`` action. It enforces the FR-UI-4 toggle for
        the owning tool (``tool_key``) FIRST, then delegates to the registered
        dispatcher's existing guarded ``dispatch`` (staged-write review, advisory-only,
        the FR-CUA stop-boundary stay where they live — this adds the shared gate, it
        does not re-implement them).

        Raises ``ToolDisabledError`` when the owning tool is toggled off, or
        ``KeyError`` when no dispatcher is registered for ``key``.
        """
        if tool_key is not None:
            self.ensure_enabled(tool_key)
        if key is None:
            if len(self._dispatchers) != 1:
                raise KeyError(
                    "handle_function_call requires an explicit dispatcher key when "
                    f"{len(self._dispatchers)} dispatchers are registered"
                )
            (dispatcher,) = self._dispatchers.values()
        else:
            dispatcher = self._dispatchers[key]
        return dispatcher.dispatch(name, arguments)

    def is_enabled(self, tool_key: str) -> bool:
        return self._state.get(tool_key, True)

    def set_enabled(self, tool_key: str, enabled: bool) -> None:
        self._state[tool_key] = bool(enabled)
        if self._sink is not None:
            self._sink.save(dict(self._state))

    def all_tools(self) -> dict[str, bool]:
        return dict(self._state)

    # --- dispatch enforcement (FR-UI-4) -----------------------------------
    def ensure_enabled(self, tool_key: str) -> None:
        """Raise ``ToolDisabledError`` if ``tool_key`` is toggled off.

        Tool dispatchers call this before running a tool so a disabled tool can
        never execute (the toggle is authoritative, not advisory).
        """
        if not self.is_enabled(tool_key):
            label = TOOL_LABELS.get(tool_key, tool_key)
            raise ToolDisabledError(f"Tool '{label}' is disabled by the operator.")

    def registry_view(self) -> list[dict]:
        """Registry rows for the FR-UI-4 toggle panel (key, label, enabled)."""
        return [
            {"key": k, "label": TOOL_LABELS.get(k, k), "enabled": v}
            for k, v in self._state.items()
        ]
