"""Campaign entity — the scope root (FR-CRIT-4, FR-LEARN, FR-AGENT-1/2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from applicant.core.ids import CampaignId


class RunMode(str, Enum):
    """Agent run modes (FR-AGENT-2)."""

    CONTINUOUS = "continuous"  # 24/7
    FIXED_DURATION = "fixed_duration"
    UNTIL_N_VIABLE = "until_n_viable"


@dataclass(frozen=True)
class Campaign:
    """Scopes everything: criteria, attributes, resumes, credentials, learning.

    MVP-1 runs a single active campaign; the model is multi-ready (FR-CRIT-4).
    """

    id: CampaignId
    name: str
    run_mode: RunMode = RunMode.CONTINUOUS
    throughput_target: int = 15  # ~15/day default; hard cap 30 (FR-AGENT-1)
    exploration_budget: float = 0.1  # FR-DISC-5 / FR-LEARN-6
    active: bool = True
    schedule: dict = field(default_factory=dict)
    learning_state: dict = field(default_factory=dict)
