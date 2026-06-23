"""Agent-memory router (FR-MIND-1/2/3/7/9/12) — what the assistant remembers.

Read + light-write surface over the agent-learning substrate:

* ``GET  /api/agent-memory``                 curated-memory snapshot (env + user).
* ``GET  /api/agent-memory/skills``          saved playbooks, L0 metadata (cheap).
* ``GET  /api/agent-memory/skills/{name}``   one playbook's full body (L1).
* ``POST /api/agent-memory/forget``          forget a curated line (write, FR-MIND-9).
* ``GET  /api/agent-memory/curation``        proposals awaiting review (FR-MIND-9).
* ``POST /api/agent-memory/curation/{id}/approve``  apply a staged proposal.
* ``POST /api/agent-memory/curation/{id}/deny``     discard a staged proposal.

Each snapshot entry carries a stable ``ref`` (a content hash of kind + text) so the
front door can target one line for a **forget** without a DB row id. A forget is a
*write*, so it routes through the same review-before-write policy as an add
(FR-MIND-9): staged for approval by default, applied directly only when the operator
has relaxed memory approval.

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

import hashlib

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


def _entry_ref(e) -> str:
    """A stable, content-derived ref for one curated line (FR-MIND-1).

    No DB row id is exposed; the ref is just ``sha1(kind|text)`` so the front door can
    point a forget at the exact line the user is looking at, and the same line maps to
    the same ref across reads.
    """
    return hashlib.sha1(f"{e.kind}|{e.text}".encode()).hexdigest()[:16]


def _entry_dict(e) -> dict:
    return {
        "ref": _entry_ref(e),
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


class ForgetRequest(BaseModel):
    """Ask the assistant to forget one curated line (FR-MIND-1 remove)."""

    ref: str | None = None
    text: str | None = None
    scope: str | None = None
    campaign_id: str | None = None


@router.post("/forget")
def forget_memory(
    body: ForgetRequest,
    agent_memory=Depends(get_agent_memory),
    curation=Depends(get_curation_service),
) -> dict:
    """Forget a curated memory line — a WRITE, gated by review-before-write (FR-MIND-9).

    Target the line by its stable ``ref`` (preferred; resolved against the current
    snapshot to the exact text) or by ``text``. The removal routes through the
    curation service's write-approval policy: with approval on (the default) it is
    STAGED for you to approve in the Portal and nothing is removed yet; with memory
    approval relaxed it is removed immediately. Never silently bypasses the policy.
    """
    if not (body.ref or body.text):
        raise HTTPException(status_code=400, detail="Tell me which note to forget.")

    # Resolve the ref (or text) to the exact stored line so the substring removal is
    # precise and the confirmation preview is honest — never a fabricated entry.
    snap = agent_memory.memory.snapshot(scope=body.scope, campaign_id=body.campaign_id)
    target_text: str | None = None
    for e in snap.all():
        if body.ref and _entry_ref(e) == body.ref:
            target_text = e.text
            break
        if body.text and e.text == body.text:
            target_text = e.text
            break
    if target_text is None:
        # Fall back to the caller-supplied text (e.g. a line not in the bounded view);
        # if there is nothing to match on, there is nothing to forget.
        target_text = body.text
    if not target_text:
        raise HTTPException(status_code=404, detail="I could not find that note to forget.")

    result = curation.stage_forget(target_text, preview=target_text, source_run_id="user")
    return {
        "ok": True,
        "applied": int(result.get("applied", 0)),
        "staged": int(result.get("staged", 0)),
        "id": result.get("id"),
        "text": target_text,
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
