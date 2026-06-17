"""Chat router (FR-CHAT-1, FR-FB-2/3).

The assistant chatbot: it takes conversational input, identifies gaps in the
campaign's attribute cloud / criteria, and proposes attribute/criteria updates.
Any integral change is surfaced as a PROPOSAL that requires explicit user
confirmation (the confirmation gate, FR-FB-3); non-integral updates may auto-apply.
The chatbot never commits an integral change on its own.

Backed by the ChatService (LLM port + attribute/criteria services), which degrades
gracefully to a deterministic reply when no LLM is configured. Gated behind the LLM
gate (FR-UI-5) and the Chat tool toggle (FR-UI-4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from applicant.app.deps import get_chat_service, require_llm_configured, require_tool_enabled
from applicant.core.errors import ConfirmationRequired
from applicant.core.ids import CampaignId

router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    dependencies=[Depends(require_llm_configured), Depends(require_tool_enabled("chat"))],
)


class ChatIn(BaseModel):
    campaign_id: str
    message: str


class ConfirmIn(BaseModel):
    campaign_id: str
    name: str
    value: str


@router.get("")
def index() -> dict:
    return {"surface": "chat", "phase": 4, "status": "live"}


@router.post("", status_code=200)
def send_message(body: ChatIn, chat=Depends(get_chat_service)) -> dict:
    """Conversational turn: reply + identified gaps + any proposed changes.

    Proposed changes carry ``requires_confirmation``; integral/sensitive changes are
    NOT auto-committed — the client must POST to ``/confirm`` (FR-FB-3). Non-integral
    proposals are auto-applied and reported with ``applied=true``.
    """
    result = chat.converse(CampaignId(body.campaign_id), body.message)
    return {
        "message": result.message,
        "gaps": result.gaps,
        "proposed_changes": [c.as_dict() for c in result.proposed_changes],
    }


@router.post("/confirm", status_code=200)
def confirm_change(body: ConfirmIn, chat=Depends(get_chat_service)) -> dict:
    """Commit an integral change the user explicitly confirmed (FR-FB-3)."""
    try:
        attr = chat.confirm_change(
            CampaignId(body.campaign_id), body.name, body.value
        )
    except ConfirmationRequired as exc:  # pragma: no cover - confirm=True path
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"committed": True, "name": attr.name, "value": attr.value}
