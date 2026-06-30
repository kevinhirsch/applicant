from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from applicant.core.ids import ApplicationId, RejectionSignalId


class RejectionSource(str, Enum):
    EMAIL = "email"
    ATS_STATUS = "ats_status"
    MANUAL = "manual"

@dataclass(frozen=True)
class RejectionSignal:
    id: RejectionSignalId
    application_id: ApplicationId
    source: RejectionSource
    signal_text: str = ""
    confidence: float = 1.0
    detail: dict = field(default_factory=dict)
    detected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
