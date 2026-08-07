"""AtsBoard entity — persisted runtime add/remove ATS boards (Greenhouse/Lever)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from applicant.core.ids import AtsBoardId


@dataclass(frozen=True)
class AtsBoard:
    """A user-added keyless ATS board (Greenhouse board token / Lever company slug).

    ``campaign_id`` is ``None`` or ``"__system__"`` when the board applies to all
    campaigns. ``source_key`` is the dedup identity used by the runtime registry
    (``greenhouse:{token}`` or ``lever:{company}``).
    """

    id: AtsBoardId
    campaign_id: str | None
    provider: str
    token: str
    source_key: str
    enabled: bool = True
    created_at: datetime | None = None
