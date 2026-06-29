"""Retention service — PII retention sweep (#363).

A thin, named view over :class:`DataLifecycleService` (the one cohesive cascade), so
the retention concern has a stable seam without duplicating the prune logic
(lift-and-shift: one implementation, two named entry points).
"""

from __future__ import annotations

from typing import Any

from applicant.application.services.data_lifecycle_service import DataLifecycleService


class RetentionService:
    """Prune stored PII older than the configured retention window (#363)."""

    def __init__(self, storage: Any, *, pii_retention_days: int = 0) -> None:
        self._lifecycle = DataLifecycleService(
            storage, pii_retention_days=pii_retention_days
        )

    def prune_pii_older_than(self, days: int | None = None) -> dict:
        return self._lifecycle.prune_pii_older_than(days)
