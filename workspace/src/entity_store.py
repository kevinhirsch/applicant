"""Owner-scoped service over the Entity / Fact / Relationship tables (Phase 1).

CRUD plus lightweight dedup, Beta-confidence updates, and keyword recall. This
is the canonical access layer; routes and (later) the agent tool go through it.
Vector recall is intentionally deferred — keyword scoring first, like the rest
of the memory subsystem started.

Every query is owner-scoped: a user sees their own rows plus legacy/shared
(``owner IS NULL``) rows, matching ``src.auth_helpers.owner_filter`` semantics.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from core.database import SessionLocal
from core.proactive_models import Entity, EntityFact, EntityRelationship
from src import entity_confidence as conf

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())


def _tokens(text: str) -> set:
    return {t for t in "".join(c.lower() if c.isalnum() else " " for c in (text or "")).split() if t}


def _jaccard(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _entity_dict(e: Entity) -> Dict[str, Any]:
    return {
        "id": e.id,
        "owner": e.owner,
        "type": e.type,
        "name": e.name,
        "aliases": e.aliases or [],
        "contact_id": e.contact_id,
        "created_at": e.created_at.isoformat() if e.created_at else None,
        "updated_at": e.updated_at.isoformat() if e.updated_at else None,
    }


def _fact_dict(f: EntityFact) -> Dict[str, Any]:
    return {
        "id": f.id,
        "entity_id": f.entity_id,
        "text": f.text,
        "category": f.category,
        "source": f.source,
        "confidence": round(f.confidence, 4),
        "alpha": f.alpha,
        "beta": f.beta,
        "uses": f.uses,
    }


def _rel_dict(r: EntityRelationship) -> Dict[str, Any]:
    return {
        "id": r.id,
        "src_entity_id": r.src_entity_id,
        "dst_entity_id": r.dst_entity_id,
        "type": r.type,
        "confidence": round(r.confidence, 4),
    }


# Owner predicate: own rows + legacy/shared (null owner).
def _owned(query, model, owner: Optional[str]):
    if not owner:
        return query
    return query.filter((model.owner == owner) | (model.owner.is_(None)))


class EntityStore:
    """Stateless facade; opens a short-lived DB session per call."""

    # ----- entities -----------------------------------------------------
    def add_entity(self, owner: Optional[str], name: str, type: str = "person",
                   aliases: Optional[List[str]] = None, contact_id: Optional[str] = None,
                   dedup: bool = True) -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("entity name required")
        db = SessionLocal()
        try:
            if dedup:
                existing = _existing_entity(db, owner, name, aliases or [], type)
                if existing is not None:
                    return {**_entity_dict(existing), "_deduped": True}
            e = Entity(id=_new_id(), owner=owner, type=type or "person", name=name,
                       aliases=aliases or [], contact_id=contact_id)
            db.add(e)
            db.commit()
            db.refresh(e)
            return _entity_dict(e)
        finally:
            db.close()

    def list_entities(self, owner: Optional[str], type: Optional[str] = None,
                      q: Optional[str] = None) -> List[Dict[str, Any]]:
        db = SessionLocal()
        try:
            query = _owned(db.query(Entity), Entity, owner)
            if type:
                query = query.filter(Entity.type == type)
            rows = query.order_by(Entity.updated_at.desc()).all()
            out = [_entity_dict(e) for e in rows]
            if q:
                ql = q.lower()
                out = [e for e in out if ql in e["name"].lower()
                       or any(ql in a.lower() for a in e["aliases"])]
            return out
        finally:
            db.close()

    def get_entity(self, owner: Optional[str], entity_id: str) -> Optional[Dict[str, Any]]:
        db = SessionLocal()
        try:
            e = _owned(db.query(Entity).filter(Entity.id == entity_id), Entity, owner).first()
            if not e:
                return None
            facts = _owned(db.query(EntityFact).filter(EntityFact.entity_id == entity_id),
                           EntityFact, owner).order_by(EntityFact.confidence.desc()).all()
            rels = _owned(db.query(EntityRelationship).filter(
                EntityRelationship.src_entity_id == entity_id), EntityRelationship, owner).all()
            d = _entity_dict(e)
            d["facts"] = [_fact_dict(f) for f in facts]
            d["relationships"] = [_rel_dict(r) for r in rels]
            return d
        finally:
            db.close()

    def delete_entity(self, owner: Optional[str], entity_id: str) -> bool:
        db = SessionLocal()
        try:
            e = _owned(db.query(Entity).filter(Entity.id == entity_id), Entity, owner).first()
            if not e:
                return False
            db.delete(e)  # facts/rels cascade via FK ondelete=CASCADE
            db.commit()
            return True
        finally:
            db.close()

    # ----- facts --------------------------------------------------------
    def add_fact(self, owner: Optional[str], entity_id: str, text: str,
                 category: Optional[str] = None, source: str = "chat",
                 positive: bool = True, weight: float = 1.0) -> Optional[Dict[str, Any]]:
        text = (text or "").strip()
        if not text:
            raise ValueError("fact text required")
        db = SessionLocal()
        try:
            e = _owned(db.query(Entity).filter(Entity.id == entity_id), Entity, owner).first()
            if not e:
                return None
            # Reinforce an existing near-duplicate fact rather than duplicating.
            facts = db.query(EntityFact).filter(EntityFact.entity_id == entity_id).all()
            match = next((f for f in facts if _jaccard(f.text, text) >= 0.6), None)
            if match is not None:
                match.alpha, match.beta = conf.observe(match.alpha, match.beta, positive, weight)
                match.confidence = conf.confidence(match.alpha, match.beta)
                match.uses = (match.uses or 0) + 1
                db.commit()
                db.refresh(match)
                return {**_fact_dict(match), "_reinforced": True}
            a, b = conf.observe(conf.PRIOR_ALPHA, conf.PRIOR_BETA, positive, weight)
            f = EntityFact(id=_new_id(), owner=owner, entity_id=entity_id, text=text,
                           category=category, source=source, alpha=a, beta=b,
                           confidence=conf.confidence(a, b))
            db.add(f)
            db.commit()
            db.refresh(f)
            return _fact_dict(f)
        finally:
            db.close()

    def delete_fact(self, owner: Optional[str], fact_id: str) -> bool:
        db = SessionLocal()
        try:
            f = _owned(db.query(EntityFact).filter(EntityFact.id == fact_id), EntityFact, owner).first()
            if not f:
                return False
            db.delete(f)
            db.commit()
            return True
        finally:
            db.close()

    # ----- relationships ------------------------------------------------
    def add_relationship(self, owner: Optional[str], src_entity_id: str,
                         dst_entity_id: str, type: str) -> Optional[Dict[str, Any]]:
        if not type:
            raise ValueError("relationship type required")
        db = SessionLocal()
        try:
            for eid in (src_entity_id, dst_entity_id):
                if _owned(db.query(Entity).filter(Entity.id == eid), Entity, owner).first() is None:
                    return None
            r = EntityRelationship(id=_new_id(), owner=owner, src_entity_id=src_entity_id,
                                   dst_entity_id=dst_entity_id, type=type, confidence=0.5)
            db.add(r)
            db.commit()
            db.refresh(r)
            return _rel_dict(r)
        finally:
            db.close()

    # ----- recall -------------------------------------------------------
    def recall(self, owner: Optional[str], query: str, k: int = 5) -> List[Dict[str, Any]]:
        """Keyword recall over entities, returning each with its top facts."""
        ents = self.list_entities(owner)
        scored = []
        for e in ents:
            hay = " ".join([e["name"], *(e["aliases"] or [])])
            score = _jaccard(hay, query)
            if query.lower() in e["name"].lower():
                score = max(score, 0.8)
            if score > 0:
                full = self.get_entity(owner, e["id"]) or e
                scored.append((score, full))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [e for _, e in scored[:k]]


def _existing_entity(db, owner, name, aliases, type) -> Optional[Entity]:
    candidates = _owned(db.query(Entity).filter(Entity.type == type), Entity, owner).all()
    names = {name.lower(), *[a.lower() for a in aliases]}
    for c in candidates:
        c_names = {c.name.lower(), *[(a or "").lower() for a in (c.aliases or [])]}
        if names & c_names:
            return c
    return None


# Module-level singleton for convenience (matches MemoryManager-style usage).
entity_store = EntityStore()
