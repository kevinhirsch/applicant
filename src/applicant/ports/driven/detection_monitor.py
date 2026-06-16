"""DetectionMonitor port (FR-PREFILL-6, FR-STEALTH).

Surfaces automation-detection signals (CAPTCHA/Turnstile/Cloudflare/403/429) that
trigger cautious mode: checkpoint, pause, notify with live-session handoff. Never
bypass/solve a challenge.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from applicant.core.entities.detection_event import DetectionEvent
from applicant.core.ids import ApplicationId


@runtime_checkable
class DetectionMonitorPort(Protocol):
    """Outbound port for detecting anti-automation signals."""

    def evaluate(self, application_id: ApplicationId, page_signals: dict) -> DetectionEvent | None:
        """Return a ``DetectionEvent`` if ``page_signals`` indicate detection, else ``None``."""
        ...
