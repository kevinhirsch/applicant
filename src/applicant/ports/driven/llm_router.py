"""LLM routing port — smart delegation between local and cloud models.

Issue #298: Local LLM tier delegation allows the engine to route tasks to the
most appropriate model endpoint based on task type, required capabilities, latency
requirements, and cost preferences. This port defines the interface; adapters
implement the actual routing strategy.
"""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, Protocol, runtime_checkable


class TaskType(StrEnum):
    """Categories of LLM tasks with different capability requirements."""
    CHAT = auto()
    EXTRACTION = auto()
    SUMMARIZATION = auto()
    REASONING = auto()
    CODE = auto()
    CREATIVE = auto()
    EMBEDDING = auto()


class Capability(StrEnum):
    """Capabilities that an endpoint may support."""
    FUNCTION_CALLING = auto()
    STRUCTURED_OUTPUT = auto()
    VISION = auto()
    CONTEXT_128K = auto()
    CONTEXT_1M = auto()
    TOOL_USE = auto()
    SYSTEM_PROMPT = auto()


class CostTier(StrEnum):
    """Cost preference for model selection."""
    LOWEST = auto()       # free / local only
    BALANCED = auto()     # reasonable cost for capability
    UNLIMITED = auto()    # best model regardless of cost


@runtime_checkable
class LlmRouterPort(Protocol):
    """Port for selecting the best LLM endpoint for a given task."""

    def select_endpoint(
        self,
        task: TaskType,
        *,
        required_capabilities: set[Capability] | None = None,
        cost_tier: CostTier = CostTier.BALANCED,
        prefer_local: bool = False,
    ) -> dict[str, Any] | None:
        """Return the best-matching endpoint config for ``task``.

        Returns ``None`` when no suitable endpoint is configured.
        """
        ...

    def list_available(self) -> list[dict[str, Any]]:
        """Return all currently available endpoints with their capabilities.

        Each record includes ``id``, ``name``, ``base_url``, ``category``,
        ``capabilities``, ``cost_tier``, and ``online`` status.
        """
        ...

    def health(self) -> dict[str, Any]:
        """Return routing status: available endpoints per tier, fallback info."""
        ...
