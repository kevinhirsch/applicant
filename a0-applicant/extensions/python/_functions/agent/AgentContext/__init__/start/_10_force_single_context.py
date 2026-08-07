"""Single-conversation redesign (FR-UX): collapse new USER-context mints onto the canonical id.

AgentContext.__init__ is @extension.extensible, so this start hook sees the
constructor's kwargs before the real constructor runs. It only rewrites the id
when one was NOT provided (the "mint a fresh random context" path) and the
context type is USER (or unset, which defaults to USER).

It deliberately does NOT touch:
  - restores from persisted chats (they always pass an explicit id, so a live
    conversation is never clobbered),
  - TASK / BACKGROUND contexts (scheduler automation and MCP/background agents
    must never collapse into the user conversation).

This is defense-in-depth: the frontend no longer calls /chat_create at all, and
helpers.api.use_context already resolves empty ids to CANONICAL_CONTEXT_ID.
"""

from helpers.extension import Extension

CANONICAL_CONTEXT_ID = "main"


class ForceSingleContext(Extension):
    def execute(self, data: dict | None = None, **kwargs):
        if not isinstance(data, dict):
            return
        ctor_kwargs = data.get("kwargs")
        if not isinstance(ctor_kwargs, dict):
            return

        # Only USER contexts (or unset type, which AgentContext defaults to USER).
        ctx_type = ctor_kwargs.get("type")
        if ctx_type is not None and getattr(ctx_type, "value", ctx_type) != "user":
            return

        # Only genuinely-new mints: restores always pass an explicit id.
        if not ctor_kwargs.get("id"):
            ctor_kwargs["id"] = CANONICAL_CONTEXT_ID
