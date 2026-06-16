"""Detection-monitor adapter (FR-PREFILL-6, FR-STEALTH).

# STAGE B — owned by Phase 2; flesh out here.

Classifies CAPTCHA/Turnstile/Cloudflare/403/429 signals into a DetectionEvent that
drives cautious mode. Never bypasses/solves a challenge.
"""

from __future__ import annotations

from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.ids import ApplicationId


class DetectionMonitor:
    """DetectionMonitorPort adapter (stub: detects nothing until Phase 2)."""

    def evaluate(self, application_id: ApplicationId, page_signals: dict) -> DetectionEvent | None:
        # STAGE B: real signal classification.
        return None
