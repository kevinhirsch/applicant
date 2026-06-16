"""DetectionEvent entity — automation-detection signal (FR-PREFILL-6, FR-STEALTH)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from applicant.core.ids import ApplicationId, DetectionEventId


@dataclass(frozen=True)
class DetectionEvent:
    """A detection signal (CAPTCHA/Turnstile/Cloudflare/403/429) triggering cautious mode."""

    id: DetectionEventId
    application_id: ApplicationId
    signal_type: str
    detail: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
