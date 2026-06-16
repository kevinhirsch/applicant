"""Chat router (FR-CHAT-1, FR-FB-2/3).

# STAGE B — owned by Phase 3 (assists Phase 3 material input/gap-finding).

The assistant chatbot: it takes conversational input, identifies gaps in the
campaign's attribute cloud / criteria, and proposes attribute/criteria updates.
Any integral change is surfaced as a PROPOSAL that requires explicit user
confirmation (the confirmation gate, FR-FB-3); non-integral updates may auto-apply.
The chatbot never commits an integral change on its own. Gated behind the LLM gate.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from applicant.app.container import Container
from applicant.app.deps import get_container, require_llm_configured
from applicant.core.rules.confirmation_gate import requires_confirmation

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_llm_configured)])


class ChatIn(BaseModel):
    campaign_id: str
    message: str


def _identify_gaps(campaign_id: str, container: Container) -> list[str]:
    """Cheap gap-finder: which core attributes are missing for the campaign."""
    have = {
        a.name.lower()
        for a in container.storage.attributes.list_for_campaign(campaign_id)  # type: ignore[arg-type]
    }
    core = ["first name", "last name", "email address", "phone", "current job title"]
    return [c for c in core if c not in have]


@router.get("")
def index() -> dict:
    return {"surface": "chat", "phase": 3, "status": "live"}


@router.post("", status_code=200)
def send_message(body: ChatIn, container: Container = Depends(get_container)) -> dict:
    """Conversational turn: reply + any proposed changes (confirmation-gated).

    Proposed changes carry ``requires_confirmation``; the client must echo a
    confirmation before the change commits (FR-FB-3). The chatbot itself never
    auto-commits an integral change.
    """
    gaps = _identify_gaps(body.campaign_id, container)
    proposed: list[dict] = []
    # Heuristic: a "my <attr> is <value>" style message proposes an attribute set.
    text = body.message.strip()
    if " is " in text.lower():
        # Treat a stated value as an integral attribute change -> needs confirmation.
        proposed.append(
            {
                "kind": "attribute",
                "raw": text,
                "is_integral": True,
                "requires_confirmation": requires_confirmation(is_integral=True),
            }
        )

    if gaps:
        reply = (
            "Thanks. I still need a few details to apply confidently: "
            + ", ".join(gaps)
            + ". I will not change anything integral without your confirmation."
        )
    else:
        reply = "Got it. Anything you want me to propose will be confirmed before it commits."

    return {
        "message": reply,
        "gaps": gaps,
        "proposed_changes": proposed,
    }
