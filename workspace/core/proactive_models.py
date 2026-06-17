"""Database models for the proactive-assistant features (Smokey parity).

These tables back the Entity/Relationship store (Phase 1) and the Awareness
loop (Phase 2). They live in a dedicated module to keep ``core/database.py``
manageable, but they register on the shared ``Base`` and are created by the
normal ``Base.metadata.create_all`` call in ``init_db`` — ``init_db`` imports
this module so the classes are registered first.

All tables are owner-scoped (``owner`` column; ``null`` = legacy/shared) and
queried through ``src.auth_helpers.owner_filter`` like the rest of the app.
New tables are created automatically on startup; no column migration needed.
"""

from sqlalchemy import (
    Column,
    String,
    Text,
    Boolean,
    DateTime,
    Integer,
    Float,
    ForeignKey,
    JSON,
    Index,
)

from core.database import Base, TimestampMixin, EncryptedText


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


# ---------------------------------------------------------------------------
# Awareness loop (Phase 2)
# ---------------------------------------------------------------------------

class AwarenessSignal(TimestampMixin, Base):
    """A short-lived raw input collected by the awareness loop."""
    __tablename__ = "awareness_signals"

    id         = Column(String, primary_key=True, index=True)
    owner      = Column(String, nullable=True, index=True)
    kind       = Column(String, nullable=False)            # calendar|email|memory|system|custom
    payload    = Column(JSON, nullable=True)
    salience   = Column(Float, nullable=False, default=0.0)
    expires_at = Column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("ix_awareness_signals_owner_kind", "owner", "kind"),
    )


class AwarenessTrigger(TimestampMixin, Base):
    """A user- or agent-defined rule that fires a proactive notification/action.

    ``alpha``/``beta`` accumulate outcome feedback (Phase 5) so noisy triggers
    can have their effective threshold tuned over time.
    """
    __tablename__ = "awareness_triggers"

    id                = Column(String, primary_key=True, index=True)
    owner             = Column(String, nullable=True, index=True)
    name              = Column(String, nullable=False, default="Untitled Trigger")
    description       = Column(Text, nullable=True)
    condition         = Column(JSON, nullable=True)         # rule spec; null/llm => fuzzy LLM eval
    channel           = Column(String, nullable=False, default="ntfy")  # ntfy|browser|email
    enabled           = Column(Boolean, nullable=False, default=True)
    risk_tier         = Column(String, nullable=False, default="low")   # low|medium|high (for actions)
    cooldown_seconds  = Column(Integer, nullable=False, default=0)
    last_fired_at     = Column(DateTime, nullable=True)
    salience_threshold = Column(Float, nullable=False, default=0.0)
    alpha             = Column(Float, nullable=False, default=1.0)
    beta              = Column(Float, nullable=False, default=1.0)

    __table_args__ = (
        Index("ix_awareness_triggers_owner_enabled", "owner", "enabled"),
    )


class AwarenessNotification(TimestampMixin, Base):
    """A proactive notification the awareness loop emitted (with outcome)."""
    __tablename__ = "awareness_notifications"

    id         = Column(String, primary_key=True, index=True)
    owner      = Column(String, nullable=True, index=True)
    trigger_id = Column(String, ForeignKey("awareness_triggers.id", ondelete="SET NULL"), nullable=True, index=True)
    title      = Column(String, nullable=True)
    body       = Column(Text, nullable=True)
    channel    = Column(String, nullable=True)
    status     = Column(String, nullable=False, default="sent")   # sent|suppressed|failed
    # Outcome feedback for the self-correcting loop (Phase 5): useful|dismissed|acted|null
    outcome    = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_awareness_notif_owner_created", "owner", "created_at"),
    )


# ---------------------------------------------------------------------------
# Home Assistant integration (Phase 4)
# ---------------------------------------------------------------------------

class HomeAssistantConfig(TimestampMixin, Base):
    """Per-owner Home Assistant connection + allowlist.

    The long-lived access token is Fernet-encrypted at rest (EncryptedText).
    ``allowlist`` is the set of entity ids / domains the agent may touch — there
    is no blanket control; an empty allowlist means nothing is controllable.
    """
    __tablename__ = "homeassistant_config"

    id        = Column(String, primary_key=True, index=True)
    owner     = Column(String, nullable=True, index=True, unique=True)  # one config per user
    base_url  = Column(String, nullable=True)            # e.g. http://homeassistant.local:8123
    token     = Column(EncryptedText, nullable=True)     # long-lived access token (encrypted)
    enabled   = Column(Boolean, nullable=False, default=False)
    allowlist = Column(JSON, nullable=True)              # list[str] of entity_ids / "domain.*"

