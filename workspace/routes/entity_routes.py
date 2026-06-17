# routes/entity_routes.py
"""HTTP API for the Entity / Relationship store (Phase 1, Smokey parity).

Owner-scoped; writes require the existing ``can_manage_memory`` privilege.
The agent reaches these via the generic ``app_api`` loopback tool, so no
change to the tool pipeline is needed in this phase.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from src.entity_store import entity_store
from src.auth_helpers import get_current_user, require_privilege

logger = logging.getLogger(__name__)


class EntityCreate(BaseModel):
    name: str
    type: str = "person"
    aliases: Optional[list] = None
    contact_id: Optional[str] = None


class FactCreate(BaseModel):
    text: str
    category: Optional[str] = None
    source: str = "manual"
    positive: bool = True
    weight: float = 1.0


class RelationshipCreate(BaseModel):
    dst_entity_id: str
    type: str


def setup_entity_routes() -> APIRouter:
    router = APIRouter()

    @router.get("/api/entities")
    async def list_entities(request: Request, type: Optional[str] = None, q: Optional[str] = None):
        owner = get_current_user(request)
        return {"entities": entity_store.list_entities(owner, type=type, q=q)}

    @router.get("/api/entities/recall")
    async def recall_entities(request: Request, q: str, k: int = 5):
        owner = get_current_user(request)
        return {"entities": entity_store.recall(owner, q, k=k)}

    @router.get("/api/entities/{entity_id}")
    async def get_entity(request: Request, entity_id: str):
        owner = get_current_user(request)
        e = entity_store.get_entity(owner, entity_id)
        if not e:
            raise HTTPException(404, "entity not found")
        return e

    @router.post("/api/entities")
    async def create_entity(request: Request, body: EntityCreate):
        require_privilege(request, "can_manage_memory")
        owner = get_current_user(request)
        try:
            return entity_store.add_entity(owner, body.name, type=body.type,
                                           aliases=body.aliases, contact_id=body.contact_id)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @router.delete("/api/entities/{entity_id}")
    async def delete_entity(request: Request, entity_id: str):
        require_privilege(request, "can_manage_memory")
        owner = get_current_user(request)
        if not entity_store.delete_entity(owner, entity_id):
            raise HTTPException(404, "entity not found")
        return {"ok": True}

    @router.post("/api/entities/{entity_id}/facts")
    async def add_fact(request: Request, entity_id: str, body: FactCreate):
        require_privilege(request, "can_manage_memory")
        owner = get_current_user(request)
        try:
            f = entity_store.add_fact(owner, entity_id, body.text, category=body.category,
                                      source=body.source, positive=body.positive, weight=body.weight)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if f is None:
            raise HTTPException(404, "entity not found")
        return f

    @router.delete("/api/entities/facts/{fact_id}")
    async def delete_fact(request: Request, fact_id: str):
        require_privilege(request, "can_manage_memory")
        owner = get_current_user(request)
        if not entity_store.delete_fact(owner, fact_id):
            raise HTTPException(404, "fact not found")
        return {"ok": True}

    @router.post("/api/entities/{entity_id}/relationships")
    async def add_relationship(request: Request, entity_id: str, body: RelationshipCreate):
        require_privilege(request, "can_manage_memory")
        owner = get_current_user(request)
        r = entity_store.add_relationship(owner, entity_id, body.dst_entity_id, body.type)
        if r is None:
            raise HTTPException(404, "entity not found")
        return r

    return router
