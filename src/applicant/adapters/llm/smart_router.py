"""LLM routing adapter — smart delegation between local and cloud models.

Uses the configured ``ModelEndpointService`` to discover available endpoints,
then applies a routing strategy based on task type, capability requirements,
and cost preferences (issue #298).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from applicant.observability.logging import get_logger
from applicant.ports.driven.llm_router import (
    Capability,
    CostTier,
    TaskType,
)

if TYPE_CHECKING:
    from applicant.ports.driven.llm import TierLadder

log = get_logger(__name__)

# Map from task types to minimum required capabilities.
_TASK_CAPABILITY_MAP: dict[TaskType, set[Capability]] = {
    TaskType.CHAT: {Capability.SYSTEM_PROMPT},
    TaskType.EXTRACTION: {Capability.STRUCTURED_OUTPUT},
    TaskType.SUMMARIZATION: {Capability.CONTEXT_128K},
    TaskType.REASONING: {Capability.FUNCTION_CALLING, Capability.STRUCTURED_OUTPUT},
    TaskType.CODE: {Capability.FUNCTION_CALLING, Capability.TOOL_USE},
    TaskType.CREATIVE: {Capability.SYSTEM_PROMPT},
    TaskType.EMBEDDING: set(),
}

# Common local model URL patterns used by health() and select_endpoint().
_LOCAL_PATTERNS = ("localhost", "127.0.0.1", "0.0.0.0", ":11434", "ollama")


class SmartLlmRouter:
    """Routes LLM tasks to the best available endpoint based on task needs.

    Uses the ``ModelEndpointService`` to list endpoints and applies a
    capability-based scoring strategy.
    """

    def __init__(self, endpoint_service: Any) -> None:
        self._endpoint_service = endpoint_service

    def select_endpoint(
        self,
        task: TaskType,
        *,
        required_capabilities: set[Capability] | None = None,
        cost_tier: CostTier = CostTier.BALANCED,
        prefer_local: bool = False,
    ) -> dict[str, Any] | None:
        required = _TASK_CAPABILITY_MAP.get(task, set())
        if required_capabilities:
            required |= required_capabilities

        endpoints = self._endpoint_service.list_endpoints(refresh=False)
        if not endpoints:
            log.warning("llm_router_no_endpoints", task=str(task))
            return None

        # Filter by cost tier
        local_keywords = ("localhost", "127.0.0.1", "0.0.0.0", ":11434", "ollama")
        def _is_local(ep: dict) -> bool:
            base = (ep.get("base_url", "") or "").lower()
            return any(k in base for k in local_keywords) or ep.get("category") == "local"

        online = [ep for ep in endpoints if ep.get("online", False)]
        if not online:
            log.warning("llm_router_no_online_endpoints", task=str(task))
            return None

        local = [ep for ep in online if _is_local(ep)]
        cloud = [ep for ep in online if not _is_local(ep)]

        if cost_tier == CostTier.LOWEST:
            candidates = local or cloud
        elif cost_tier == CostTier.UNLIMITED:
            candidates = cloud or local
        else:  # BALANCED
            candidates = online

        if prefer_local and local:
            candidates = local + [c for c in candidates if not _is_local(c)]

        # Score candidates: capability match is primary signal
        scored: list[tuple[int, dict[str, Any]]] = []
        for ep in candidates:
            caps = _capabilities_for(ep)
            matching = required & caps
            score = len(matching) * 10
            # Small nudge for local when prefer_local is set
            if prefer_local and _is_local(ep):
                score += 1
            scored.append((score, ep))

        scored.sort(key=lambda x: -x[0])
        best = scored[0][1]
        log.info(
            "llm_router_selected",
            task=str(task),
            endpoint=best.get("name", best.get("base_url", "")),
            score=scored[0][0],
        )
        return best

    def list_available(self) -> list[dict[str, Any]]:
        endpoints = self._endpoint_service.list_endpoints(refresh=False)
        out = []
        for ep in endpoints:
            if not ep.get("online", False):
                continue
            caps = _capabilities_for(ep)
            out.append({
                "id": ep.get("id"),
                "name": ep.get("name", ""),
                "base_url": ep.get("base_url", ""),
                "category": ep.get("category", "api"),
                "online": True,
                "capabilities": sorted(c.name for c in caps),
            })
        return out

    def health(self) -> dict[str, Any]:
        endpoints = self._endpoint_service.list_endpoints(refresh=False)
        online = [ep for ep in endpoints if ep.get("online", False)]
        local = [ep for ep in online if any(p in (ep.get("base_url", "") or "").lower() for p in _LOCAL_PATTERNS)]
        cloud = [ep for ep in online if ep not in local]
        return {
            "endpoints_total": len(endpoints),
            "endpoints_online": len(online),
            "local_available": len(local),
            "cloud_available": len(cloud),
            "has_local_fallback": len(local) > 0,
        }


def _norm_base(url: str) -> str:
    """Normalize a base URL for tier<->endpoint matching (lowercased, no trailing /)."""
    return (url or "").strip().lower().rstrip("/")


def order_ladder_by_router(
    ladder: TierLadder | None,
    router: SmartLlmRouter,
    *,
    task: TaskType = TaskType.CHAT,
    cost_tier: CostTier = CostTier.BALANCED,
    prefer_local: bool = False,
) -> TierLadder | None:
    """Reorder ``ladder`` so the router-preferred endpoint's tier is walked first.

    Additive and reversible: this NEVER drops a tier and NEVER rewrites a tier's
    config — it only REORDERS the existing :class:`TierLadder`, putting the tier
    whose ``base_url`` matches the router-selected endpoint at the front so the
    existing context-window fallback in ``OpenAICompatibleLLM`` still walks every
    remaining tier in its original relative order. When the router cannot pick an
    endpoint, or no tier matches the selected endpoint's URL, the ladder is
    returned unchanged — so a misconfigured router can never strand the engine.

    Because the LLM adapter dispatches local vs. cloud purely on the active
    tier's provider/``base_url`` (``_call_ollama`` vs. ``_call_openai``), moving a
    LOCAL endpoint's tier to the front is exactly what makes the engine CALL the
    local model: routing reaches the live path through tier order.
    """
    if ladder is None or not ladder.tiers:
        return ladder
    try:
        selected = router.select_endpoint(
            task, cost_tier=cost_tier, prefer_local=prefer_local
        )
    except Exception:  # pragma: no cover - defensive: never break LLM construction
        log.warning("llm_router_select_failed", exc_info=True)
        return ladder
    if not selected:
        return ladder

    target = _norm_base(selected.get("base_url", ""))
    if not target:
        return ladder

    tiers = list(ladder.tiers)
    preferred_idx = next(
        (i for i, t in enumerate(tiers) if _norm_base(t.base_url) == target),
        None,
    )
    if preferred_idx is None or preferred_idx == 0:
        # Selected endpoint isn't (or is already) the first configured tier.
        return ladder

    from applicant.ports.driven.llm import TierLadder as _TierLadder

    reordered = [tiers[preferred_idx]] + [
        t for i, t in enumerate(tiers) if i != preferred_idx
    ]
    log.info(
        "llm_router_ladder_reordered",
        moved_to_front=selected.get("name", target),
        provider=tiers[preferred_idx].provider,
    )
    return _TierLadder(tiers=reordered)


def _capabilities_for(ep: dict[str, Any]) -> set[Capability]:
    """Derive capabilities from endpoint metadata.

    Local models (category="local") support basic chat/system-prompt.
    Cloud API models support function calling, structured output, tool use.
    The most capable models also handle vision and 128K+ context.
    """
    caps: set[Capability] = set()
    cat = ep.get("category", "")
    base_url = ep.get("base_url", "")

    # All LLM endpoints support system prompts
    caps.add(Capability.SYSTEM_PROMPT)

    if cat == "api":
        caps.add(Capability.FUNCTION_CALLING)
        caps.add(Capability.STRUCTURED_OUTPUT)
        caps.add(Capability.TOOL_USE)
        caps.add(Capability.CONTEXT_128K)
        # Vision-capable if the name suggests it
        name = (ep.get("name", "") + " " + base_url).lower()
        if any(k in name for k in ("vision", "gpt-4", "claude-3", "gemini-pro-vision", "llava")):
            caps.add(Capability.VISION)
    else:
        # Local / generic: basic capabilities only
        caps.add(Capability.CONTEXT_128K)

    return caps
