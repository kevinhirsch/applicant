"""Chat driving port (FR-CHAT-1, FR-FB-2).

Conversational input/gap-finding that updates attributes/criteria, subject to the
integral-change confirmation gate (FR-FB-3). Live in Phase 4 (grayed until then).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from applicant.core.ids import CampaignId


@dataclass(frozen=True)
class ChatReply:
    message: str
    proposed_changes: tuple[dict, ...] = ()  # each may require confirmation


@runtime_checkable
class ChatPort(Protocol):
    """Inbound port for the assistant chatbot."""

    def send_message(self, campaign_id: CampaignId, message: str) -> ChatReply: ...
