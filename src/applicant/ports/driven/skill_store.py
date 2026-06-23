"""SkillStore port (FR-MIND-2 — procedural skills the agent writes & improves).

After completing a non-trivial task the agent MAY author a reusable **skill** — a
structured playbook (``when to use / procedure / pitfalls / verification``, the
upstream ``SKILL.md`` body) — and improve it on re-encounter (``patch`` for
targeted updates, ``edit`` for rewrites). Skills use **progressive disclosure**:
``list_skills()`` returns L0 metadata only (cheap), ``load(name)`` returns the L1
body (the full playbook). This keeps token cost bounded (FR-MIND-13).

The dataclasses mirror the front-door ``SKILL.md`` shape already shipping under
``workspace/services/memory/skill_format.py`` (white-labeled), so a workspace-bridge
adapter can map straight onto it (``docs/spec/agent-intelligence.md`` §10).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

#: Skill ``scope`` discriminators (FR-MIND-2): campaign-scoped (a tenant's account
#: flow) or global (reusable across every campaign).
SKILL_SCOPE_GLOBAL = "global"
SKILL_SCOPE_CAMPAIGN = "campaign"
SKILL_SCOPES = (SKILL_SCOPE_GLOBAL, SKILL_SCOPE_CAMPAIGN)


@dataclass(frozen=True)
class SkillMeta:
    """L0 metadata for a skill (FR-MIND-2 progressive disclosure).

    The cheap index row: enough to decide whether to ``load`` the full body, with
    no procedure text. ``when_to_use`` is the trigger condition surfaced in the
    index so the agent can match a situation without paying for the L1 body.
    """

    name: str
    description: str = ""
    when_to_use: str = ""
    version: str = "1.0.0"
    scope: str = SKILL_SCOPE_GLOBAL
    campaign_id: str | None = None
    source: str = "learned"  # learned | taught | imported


@dataclass(frozen=True)
class Skill:
    """L1 full body of a procedural skill (FR-MIND-2).

    Mirrors ``workspace/services/memory/skill_format.py`` so a bridge adapter maps
    one-to-one. ``procedure`` / ``pitfalls`` / ``verification`` are the playbook
    sections the agent authors and improves over time.
    """

    name: str
    description: str = ""
    version: str = "1.0.0"
    when_to_use: str = ""
    procedure: tuple[str, ...] = ()
    pitfalls: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    scope: str = SKILL_SCOPE_GLOBAL
    campaign_id: str | None = None
    source: str = "learned"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def meta(self) -> SkillMeta:
        """Project this skill down to its L0 metadata (progressive disclosure)."""
        return SkillMeta(
            name=self.name,
            description=self.description,
            when_to_use=self.when_to_use,
            version=self.version,
            scope=self.scope,
            campaign_id=self.campaign_id,
            source=self.source,
        )


@runtime_checkable
class SkillStore(Protocol):
    """Outbound port for procedural skills (FR-MIND-2)."""

    def list_skills(self, scope: str | None = None, campaign_id: str | None = None) -> tuple[SkillMeta, ...]:
        """Return L0 metadata for every visible skill (no bodies — cheap)."""
        ...

    def load(self, name: str) -> Skill | None:
        """Return the L1 full body for ``name``, or ``None`` if unknown."""
        ...

    def create(self, skill: Skill) -> Skill:
        """Author a new skill. Returns the stored skill."""
        ...

    def patch(self, name: str, **fields: object) -> Skill | None:
        """Targeted update of named fields on an existing skill (upstream ``patch``).

        Returns the updated skill, or ``None`` if ``name`` is unknown.
        """
        ...

    def edit(self, name: str, skill: Skill) -> Skill | None:
        """Full rewrite of an existing skill (upstream ``edit``).

        Returns the rewritten skill, or ``None`` if ``name`` is unknown.
        """
        ...

    def delete(self, name: str) -> bool:
        """Delete a skill. Returns True if one was removed."""
        ...
