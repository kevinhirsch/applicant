"""Loop-side agent toolbox — the SAME guarded tools, registered for the 24/7 loop.

The chat path already has an agent-callable toolbox (``ChatToolbox`` in
``chat_tools.py``): ``remember``/``forget``/``save_playbook``/``update_playbook``/
``recall``/``desktop``, each routed through the existing guards (curation staging for
review, the advisory-not-authorization rule, the desktop stop-boundary, and the
per-tool on/off toggles). This module does NOT re-implement any of that. It LIFTS the
chat toolbox and registers it as a tool set the **autonomous loop's** tool-capable
model can choose to call mid-reasoning — closing the gap that memory/skills/recall and
the bounded desktop action were only ever injected as passive context, never callable.

``LoopToolset`` is a thin wrapper that:

* OWNS a ``ChatToolbox`` (the existing implementations + guards), so every schema and
  every dispatch goes through the same staged-write / advisory-only / stop-boundary /
  toggle path the chat tools already use — there is no second policy here;
* exposes :meth:`tool_schemas` (the JSON schemas surfaced to a tool-capable model) and
  :meth:`dispatch` (one guarded tool call) by delegation;
* adds :meth:`run` — a bounded tool-dispatch loop (mirrors ``chat_service``'s
  ``_reply_with_tools``) so the loop's model can iterate tool calls and finish in text.

It is OPT-IN. The container builds it only when ``LOOP_TOOLS`` is enabled AND the
configured model advertises tool calling; default OFF ⇒ no toolset is built and the
loop behaves byte-identically to today (no schemas registered, no dispatch path).
"""

from __future__ import annotations

from typing import Any

from applicant.application.services.chat_tools import MAX_TOOL_ROUNDS, ChatToolbox
from applicant.observability.logging import get_logger
from applicant.ports.driven.llm import ChatMessage

log = get_logger(__name__)


class LoopToolset:
    """The autonomous loop's registered, agent-callable tool set (reuses ``ChatToolbox``).

    All collaborators are optional/defaulted and threaded straight into the reused
    ``ChatToolbox``; a missing one simply means the corresponding tool is not offered
    (the schema list omits it) and a stray call returns a graceful "not available"
    string. Nothing here can bypass review-before-write or the stop-boundary — those
    live in the toolbox + the core rules it calls.
    """

    def __init__(
        self,
        *,
        campaign_id: Any,
        agent_memory=None,
        curation_service=None,
        tool_registry=None,
        computer_use=None,
        desktop_operable: bool = False,
    ) -> None:
        # LIFT-AND-SHIFT: the loop's tools ARE the chat tools. We hold one ChatToolbox
        # and delegate schema + dispatch to it, so the guards (staging, advisory-only,
        # FR-CUA boundary, FR-UI-4 toggle) are exercised exactly once, in one place.
        self._box = ChatToolbox(
            campaign_id=campaign_id,
            agent_memory=agent_memory,
            curation_service=curation_service,
            tool_registry=tool_registry,
            computer_use=computer_use,
            desktop_operable=desktop_operable,
        )

    # --- registry surface (schemas + dispatch) ----------------------------
    def tool_schemas(self) -> list[dict[str, Any]]:
        """JSON schemas for every AVAILABLE tool (delegates to the reused toolbox)."""
        return self._box.tool_schemas()

    def dispatch(self, name: str, arguments: str) -> str:
        """Run one tool call through the reused toolbox's guards; return a result string."""
        return self._box.dispatch(name, arguments)

    def has_tools(self) -> bool:
        """True when at least one tool is offerable (so the loop is worth entering)."""
        return self._box.has_tools()

    # --- bounded tool-dispatch loop (mirrors chat_service) -----------------
    def run(self, llm, system: str, prompt: str, *, max_tokens: int = 256) -> str | None:
        """Drive the loop's tool-capable model over this tool set; return final text.

        Mirrors ``chat_service._reply_with_tools`` exactly (same dispatch shape): each
        round asks the model with the tool schemas, dispatches any requested calls
        through the guarded toolbox, feeds the results back, and repeats until the model
        returns plain text or the round cap is hit. Returns ``None`` (caller falls back
        to its single-shot path) when the model never used a tool or no model/tool path
        is available — so an absent or non-tool model is a clean no-op.
        """
        if llm is None or not callable(getattr(llm, "complete_with_tools", None)):
            return None
        schemas = self.tool_schemas()
        if not schemas:
            return None
        messages = [
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=prompt),
        ]
        used_a_tool = False
        for _ in range(MAX_TOOL_ROUNDS):
            try:
                result = llm.complete_with_tools(messages, schemas, max_tokens=max_tokens)
            except Exception:  # pragma: no cover - defensive: never break the tick
                return None
            calls = tuple(getattr(result, "tool_calls", ()) or ())
            if not calls:
                text = (getattr(result, "text", "") or "").strip()
                return text if used_a_tool else (text or None)
            used_a_tool = True
            messages.append(ChatMessage(role="assistant", content="", tool_calls=calls))
            for call in calls:
                tool_result = self.dispatch(call.name, call.arguments)
                messages.append(
                    ChatMessage(role="tool", content=tool_result, tool_call_id=call.id)
                )
        # Round cap hit: one plain-text wrap-up (no tools), like the chat path.
        try:
            final = llm.complete(messages, max_tokens=max_tokens)
            return (getattr(final, "text", "") or "").strip() or None
        except Exception:  # pragma: no cover - defensive
            return None


def build_loop_toolset(
    *,
    setting: str,
    llm,
    campaign_id: Any,
    agent_memory=None,
    curation_service=None,
    tool_registry=None,
    computer_use=None,
    desktop_operable: bool = False,
) -> LoopToolset | None:
    """Build the loop toolset ONLY when opted in AND the model supports tools.

    Returns ``None`` (byte-identical default behavior — no registered tools) unless:
    ``setting`` is "auto"/"on", the configured model advertises tool calling
    (``supports_tools()``) and exposes ``complete_with_tools``, and at least one tool is
    actually offerable. Any of these false ⇒ the loop runs exactly as today.
    """
    if (setting or "off").strip().lower() not in ("auto", "on", "true", "1"):
        return None
    supports = getattr(llm, "supports_tools", None)
    if not callable(supports):
        return None
    try:
        if not supports():
            return None
    except Exception:  # pragma: no cover - defensive
        return None
    if not callable(getattr(llm, "complete_with_tools", None)):
        return None
    toolset = LoopToolset(
        campaign_id=campaign_id,
        agent_memory=agent_memory,
        curation_service=curation_service,
        tool_registry=tool_registry,
        computer_use=computer_use,
        desktop_operable=desktop_operable,
    )
    return toolset if toolset.has_tools() else None
