"""Agent-memory router (FR-MIND-1/2/3/7/9/12) — what the assistant remembers.

Read + light-write surface over the agent-learning substrate:

* ``GET  /api/agent-memory``                 curated-memory snapshot (env + user).
* ``GET  /api/agent-memory/skills``          saved playbooks, L0 metadata (cheap).
* ``GET  /api/agent-memory/skills/{name}``   one playbook's full body (L1).
* ``GET  /api/agent-memory/curation``        proposals awaiting review (FR-MIND-9).
* ``POST /api/agent-memory/curation/{id}/approve``  apply a staged proposal.
* ``POST /api/agent-memory/curation/{id}/deny``     discard a staged proposal.

The stores are the container's ``agent_memory`` adapter trio (default ``in_memory``,
hermetic; ``bridge`` reaches the front-door substrate over the callback channel).
Approve/deny operate on the process-lived ``CurationService`` so the human stays in
the loop (review-before-write, FR-MIND-9). Nothing here can grant authority — applied
memory/skills are advisory context only (FR-MIND-11); the safety boundary derives its
own ground truth regardless.

Gated behind the LLM-settings gate (FR-UI-5): the substrate is meaningless before a
model is connected.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from applicant.app.deps import (
    get_agent_memory,
    get_curation_service,
    require_llm_configured,
)
from applicant.application.services.curation_service import proposal_to_dict

router = APIRouter(
    prefix="/api/agent-memory",
    tags=["agent_memory"],
    dependencies=[Depends(require_llm_configured)],
)


def _entry_dict(e) -> dict:
    return {
        "text": e.text,
        "kind": e.kind,
        "scope": e.scope,
        "campaign_id": e.campaign_id,
    }


@router.get("")
def memory_snapshot(
    scope: str | None = None,
    campaign_id: str | None = None,
    agent_memory=Depends(get_agent_memory),
) -> dict:
    """The bounded, curated memory the assistant carries (FR-MIND-1).

    Split into environment lessons and user preferences so the UI can label them.
    Reads only — edits to memory go through curation review (FR-MIND-9).
    """
    snap = agent_memory.memory.snapshot(scope=scope, campaign_id=campaign_id)
    return {
        "environment": [_entry_dict(e) for e in snap.environment],
        "user": [_entry_dict(e) for e in snap.user],
        "truncated": bool(snap.truncated),
    }


@router.get("/skills")
def list_skills(
    scope: str | None = None,
    campaign_id: str | None = None,
    agent_memory=Depends(get_agent_memory),
) -> dict:
    """Saved playbooks, metadata only (FR-MIND-2 progressive disclosure, L0)."""
    metas = agent_memory.skills.list_skills(scope=scope, campaign_id=campaign_id)
    return {
        "items": [
            {
                "name": m.name,
                "description": m.description,
                "when_to_use": m.when_to_use,
                "version": m.version,
                "scope": m.scope,
                "campaign_id": m.campaign_id,
                "source": m.source,
            }
            for m in metas
        ]
    }


@router.get("/skills/{name}")
def load_skill(name: str, agent_memory=Depends(get_agent_memory)) -> dict:
    """One saved playbook's full body (FR-MIND-2, L1)."""
    skill = agent_memory.skills.load(name)
    if skill is None:
        raise HTTPException(status_code=404, detail="That saved playbook was not found.")
    return {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "when_to_use": skill.when_to_use,
        "procedure": list(skill.procedure),
        "pitfalls": list(skill.pitfalls),
        "verification": list(skill.verification),
        "scope": skill.scope,
        "campaign_id": skill.campaign_id,
        "source": skill.source,
        "tags": list(skill.tags),
    }


@router.get("/curation")
def list_curation(curation=Depends(get_curation_service)) -> dict:
    """Proposals the assistant has staged for your review (FR-MIND-7/-9).

    Each item is a memory note or saved-playbook change the assistant proposed from
    its recent work; nothing is applied until you approve it.
    """
    items = [proposal_to_dict(p) for p in curation.list_staged()]
    return {"count": len(items), "items": items}


class CurationActionResult(BaseModel):
    ok: bool
    id: str


@router.post("/curation/{proposal_id}/approve")
def approve_curation(proposal_id: str, curation=Depends(get_curation_service)) -> dict:
    """Approve a staged proposal — apply it to what the assistant remembers."""
    if not curation.approve(proposal_id):
        raise HTTPException(status_code=404, detail="That proposal is no longer pending.")
    return {"ok": True, "id": proposal_id}


@router.post("/curation/{proposal_id}/deny")
def deny_curation(proposal_id: str, curation=Depends(get_curation_service)) -> dict:
    """Deny a staged proposal — discard it without applying."""
    if not curation.deny(proposal_id):
        raise HTTPException(status_code=404, detail="That proposal is no longer pending.")
    return {"ok": True, "id": proposal_id}
