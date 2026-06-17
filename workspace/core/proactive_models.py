"""Database models for the Entity/Relationship store (Applicant parity).

These tables back the Entity/Relationship store (Phase 1). They live in a
dedicated module to keep ``core/database.py`` manageable, but they register on
the shared ``Base`` and are created by the normal ``Base.metadata.create_all``
call in ``init_db`` — ``init_db`` imports this module so the classes are
registered first.

All tables are owner-scoped (``owner`` column; ``null`` = legacy/shared) and
queried through ``src.auth_helpers.owner_filter`` like the rest of the app.
New tables are created automatically on startup; no column migration needed.
"""

from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    Float,
    ForeignKey,
    JSON,
    Index,
)

from core.database import Base, TimestampMixin


# ---------------------------------------------------------------------------
# Entity + Relationship store (Phase 1)
# ---------------------------------------------------------------------------

class Entity(TimestampMixin, Base):
    """A person, place, project, org, or thing the assistant tracks."""
    __tablename__ = "entities"

    id         = Column(String, primary_key=True, index=True)
    owner      = Column(String, nullable=True, index=True)  # username; null = legacy/shared
    type       = Column(String, nullable=False, default="person")  # person|place|project|org|thing
    name       = Column(String, nullable=False)
    aliases    = Column(JSON, nullable=True)                # list[str] of alternate names
    # Optional link to an existing CardDAV contact instead of duplicating it.
    contact_id = Column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_entities_owner_type", "owner", "type"),
        Index("ix_entities_owner_name", "owner", "name"),
    )


class EntityFact(TimestampMixin, Base):
    """An attributed fact about an entity, carrying Beta-distribution confidence.

    ``confidence`` is the surfaced value ``alpha / (alpha + beta)``; it is stored
    so queries can sort/filter without recomputing. ``alpha``/``beta`` are the
    Beta parameters updated as corroborating/contradicting evidence arrives.
    """
    __tablename__ = "entity_facts"

    id         = Column(String, primary_key=True, index=True)
    owner      = Column(String, nullable=True, index=True)
    entity_id  = Column(String, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    text       = Column(Text, nullable=False)
    category   = Column(String, nullable=True)             # identity|preference|fact|relationship|...
    source     = Column(String, nullable=True)             # chat|email|manual|inferred
    confidence = Column(Float, nullable=False, default=0.5)
    alpha      = Column(Float, nullable=False, default=1.0)
    beta       = Column(Float, nullable=False, default=1.0)
    uses       = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_entity_facts_owner_entity", "owner", "entity_id"),
    )


class EntityRelationship(TimestampMixin, Base):
    """A typed, directed relationship between two entities (with confidence)."""
    __tablename__ = "entity_relationships"

    id            = Column(String, primary_key=True, index=True)
    owner         = Column(String, nullable=True, index=True)
    src_entity_id = Column(String, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    dst_entity_id = Column(String, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    type          = Column(String, nullable=False)         # works_with|manages|spouse|member_of|located_in|...
    confidence    = Column(Float, nullable=False, default=0.5)

    __table_args__ = (
        Index("ix_entity_rel_owner_src", "owner", "src_entity_id"),
    )

