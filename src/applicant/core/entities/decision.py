"""Decision entity — approve/decline with feedback (FR-DIG-3/5, FR-FB-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from applicant.core.ids import ApplicationId, DecisionId


class DecisionType(str, Enum):
    APPROVE = "approve"
    DECLINE = "decline"


@dataclass(frozen=True)
class Decision:
    """A digest decision; declines carry feedback that feeds learning + criteria."""

    id: DecisionId
    application_id: ApplicationId
    type: DecisionType
    feedback_text: str = ""
    criteria_delta: dict = field(default_factory=dict)
