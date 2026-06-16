"""RevisionSession entity — interactive redline loop (FR-RESUME-8)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from applicant.core.ids import GeneratedDocumentId, RevisionSessionId


class RevisionStatus(str, Enum):
    OPEN = "open"
    APPROVED = "approved"
    DECLINED = "declined"


@dataclass(frozen=True)
class RevisionTurn:
    """One add/subtract/free-text turn plus the AI's response."""

    kind: str  # "add" | "subtract" | "free_text"
    instruction: str
    ai_response: str = ""


@dataclass(frozen=True)
class RevisionSession:
    """Interactive add/subtract/free-text redline loop over a material."""

    id: RevisionSessionId
    material_id: GeneratedDocumentId
    status: RevisionStatus = RevisionStatus.OPEN
    turns: tuple[RevisionTurn, ...] = ()
    redline_state: dict = field(default_factory=dict)
